"""RepoAgentRunner — execute a single-shot generator agent in a repo workspace.

Closes bug B6 from the dogfooding report. `WorkspaceDirManager.create_repo_workspace`
scaffolds a clone directory but stops there — the posture-fix route returned a
``workspace_id`` pointing at an inert folder and no PR was ever opened.

This runner:

1. Builds a Pydantic AI ``Model`` from canonical AI state and a repo-action
   agent (bash/edit/read/gh tools), with ``GH_TOKEN``/``CLIFF_REPO_URL`` in
   the deps env.
2. Runs the agent in-process (``agent.run``) with ``auto_approve=True`` — the
   ``output_type`` (``RepoActionOutput``) carries ``pr_url`` directly, so
   there is no JSON contract to parse.
3. Persists the outcome to ``history/status.json`` inside the workspace so the
   posture route can report status back to the UI without a new DB table.

Repo-action runs auto-approve every gated tool (clone/edit/push/PR): the user
already authorised the single action by clicking "Let Cliff open a PR", and
there is no interactive approval path in a background posture-fix run.

Contract: the runner never raises. All outcomes — success, bad model output,
model error, timeout — collapse into a ``RepoAgentStatus`` row persisted to
disk. Callers poll the status file.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel
from pydantic_ai.exceptions import (
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.provider import ProviderConfigurationError, build_model
from cliff.agents.runtime.repo_actions import (
    RepoActionOutput,
    build_repo_action_agent,
    build_repo_action_prompt,
)
from cliff.services.pr_verifier import verify_pr_url

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from cliff.workspace.workspace_dir_manager import WorkspaceKind

    EnvResolver = Callable[[], Awaitable[dict[str, str]]]
    ModelResolver = Callable[[], Awaitable[str | None]]

logger = logging.getLogger(__name__)


# Give the generator up to 10 minutes end-to-end. Git clone + push + gh PR
# create is measured in tens of seconds on GitHub; the rest is LLM latency.
DEFAULT_TIMEOUT_SECONDS = 600.0

# Stall detection is intentionally absent: a tool-using agent can go quiet
# for long stretches while the model thinks between tool invocations
# (especially during a multi-step clone→detect→write→commit→push→PR flow).
# A premature stall cancel would kill the run after it had already produced
# side effects (cloned repo, checked out a branch). We rely on the overall
# ``DEFAULT_TIMEOUT_SECONDS`` (10 min) to bound the run instead.

RepoAgentPhase = Literal["queued", "running", "pr_created", "already_present", "failed"]

# Maps runner phases to ``workspace.state`` values. Terminal phases flip the
# partial unique index predicate off so a retry of the same posture check
# is no longer blocked by ``idx_workspace_active_per_check``.
_PHASE_TO_WORKSPACE_STATE: dict[str, str] = {
    "queued": "pending",
    "running": "running",
    "pr_created": "succeeded",
    "already_present": "succeeded",
    "failed": "failed",
}


async def _sync_workspace_state(workspace_id: str, phase: str) -> None:
    """Best-effort UPDATE ``workspace.state`` from a runner phase.

    Repo-action workspaces live in the ``workspace`` table since ADR-0030;
    the partial unique index on ``source_check_name`` only releases when
    state leaves ``pending`` / ``running``. Unit tests often run the runner
    without a DB (``_db is None``) — silently skip in that case.
    """
    from cliff.db.connection import _db
    from cliff.db.repo_workspace import set_workspace_state

    if _db is None:
        return
    target = _PHASE_TO_WORKSPACE_STATE.get(phase)
    if target is None:
        return
    try:
        await set_workspace_state(_db, workspace_id, target)
    except Exception:
        logger.exception(
            "failed to sync workspace.state for %s (phase=%s)",
            workspace_id,
            phase,
        )


class RepoAgentStatus(BaseModel):
    """On-disk status snapshot. One JSON file per repo workspace."""

    workspace_id: str
    kind: str  # WorkspaceKind.value
    status: RepoAgentPhase
    pr_url: str | None = None
    branch_name: str | None = None
    error: str | None = None
    started_at: str
    finished_at: str | None = None
    # Last ~2000 chars of the agent's SSE text, persisted so the UI can show
    # users *why* a run failed instead of generic "Agent finished without
    # opening a PR". Added for B16 (fake PR URL surfaced as a helpful log).
    agent_log_tail: str | None = None
    # Raw JSON payload from the generator's structured_output block, kept so
    # the UI can surface rich per-kind details (e.g. the file_path an agent
    # wrote) without us having to bake every template's schema into this model.
    structured_output: dict[str, Any] | None = None


def _status_path(workspace_root: Path) -> Path:
    return workspace_root / "history" / "status.json"


def read_status(workspace_root: Path) -> RepoAgentStatus | None:
    """Return the last persisted status for a repo workspace, or None.

    Posture route handlers call this on every poll — must never raise.
    """
    path = _status_path(workspace_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        return RepoAgentStatus.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("corrupt status file at %s: %s", path, exc)
        return None


def _write_status(workspace_root: Path, status: RepoAgentStatus) -> None:
    path = _status_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic-ish write so a concurrent poll never reads half a file.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(status.model_dump_json(indent=2))
    tmp.replace(path)


class RepoAgentRunner:
    """Runs the generator agent attached to a repo-action workspace.

    Decoupled from ``AgentExecutor``: no DB row, no SSE permission queue, no
    ``AgentRun`` schema validation. Posture workspaces have exactly one agent
    run and discard themselves when it's done.
    """

    def __init__(
        self,
        *,
        env_resolver: EnvResolver,
        model_resolver: ModelResolver,
    ) -> None:
        # Resolve the app-level AI provider env + active model at run time
        # (ADR-0047 / IMPL-0022 PR #3c) — the generator is now an in-process
        # Pydantic AI agent, not an OpenCode subprocess.
        self._env_resolver = env_resolver
        self._model_resolver = model_resolver

    async def run(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        kind: WorkspaceKind,
        repo_url: str,
        gh_token: str | None,
        params: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> RepoAgentStatus:
        """Execute the generator agent end-to-end.

        Never raises. Failures are captured in the returned ``RepoAgentStatus``
        with ``status="failed"`` and ``error`` filled in.
        """
        started = datetime.now(UTC).isoformat()
        running = RepoAgentStatus(
            workspace_id=workspace_id,
            kind=kind.value,
            status="running",
            started_at=started,
        )
        _write_status(workspace_root, running)
        await _sync_workspace_state(workspace_id, "running")

        # Build the model from the canonical AI state.
        try:
            ai_env = await self._env_resolver()
            model_id = await self._model_resolver()
            model = build_model(ai_env, model_id)
        except ProviderConfigurationError as exc:
            return await self._finalize(
                workspace_root,
                running,
                status="failed",
                error=f"AI provider not configured: {exc}",
            )

        # Tool subprocess env: the GitHub token + repo URL. ``bash`` merges
        # this over ``os.environ`` so git/gh keep PATH etc.
        env_vars: dict[str, str] = {"CLIFF_REPO_URL": repo_url}
        if gh_token:
            env_vars["GH_TOKEN"] = gh_token
            env_vars["GITHUB_TOKEN"] = gh_token

        deps = WorkspaceDeps(
            workspace_id=workspace_id,
            workspace_dir=str(workspace_root),
            finding={},
            env_vars=env_vars,
            auto_approve=True,  # one-shot, pre-approved — no HITL surface
        )
        agent = build_repo_action_agent(model, kind)
        user_prompt = build_repo_action_prompt(
            kind, repo_url=repo_url, params=params or {}
        )

        try:
            result = await asyncio.wait_for(
                agent.run(user_prompt, deps=deps), timeout=timeout
            )
        except TimeoutError:
            logger.warning("repo agent %s timed out after %ss", workspace_id, timeout)
            return await self._finalize(
                workspace_root,
                running,
                status="failed",
                error=f"Agent timed out after {timeout:.0f}s",
            )
        except (
            ModelHTTPError,
            UnexpectedModelBehavior,
            UsageLimitExceeded,
            UserError,
        ) as exc:
            logger.warning("repo agent %s run failed: %s", workspace_id, exc)
            return await self._finalize(
                workspace_root,
                running,
                status="failed",
                error=f"Agent run failed: {type(exc).__name__}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — never leak to caller
            logger.exception(
                "unexpected error in repo agent runner for %s", workspace_id
            )
            return await self._finalize(
                workspace_root,
                running,
                status="failed",
                error=f"Unexpected error: {exc}",
            )

        output: RepoActionOutput = result.output
        structured = output.model_dump()

        # Persist the full message transcript for operator diagnostics —
        # the analogue of the old SSE-text dump.
        with contextlib.suppress(Exception):
            (workspace_root / "history" / "agent-response.txt").write_bytes(
                result.all_messages_json()
            )
        log_tail = _tail(output.result_card_markdown or output.summary or "")

        if output.status == "pr_created":
            # B16: the agent cannot be trusted to emit a real PR URL. Hit
            # GitHub's API before we tell the user "PR opened".
            verification = await verify_pr_url(output.pr_url, token=gh_token)
            if verification.ok:
                return await self._finalize(
                    workspace_root,
                    running,
                    status="pr_created",
                    pr_url=verification.html_url or output.pr_url,
                    branch_name=output.branch_name,
                    structured_output=structured,
                )
            return await self._finalize(
                workspace_root,
                running,
                status="failed",
                error=(
                    f"PR verification failed: {verification.reason}. "
                    f"Agent claimed pr_url={output.pr_url!r}."
                ),
                structured_output=structured,
                agent_log_tail=log_tail,
            )
        if output.status == "already_present":
            return await self._finalize(
                workspace_root,
                running,
                status="already_present",
                structured_output=structured,
            )
        # status == "failed" (or anything else): surface the agent's reason.
        return await self._finalize(
            workspace_root,
            running,
            status="failed",
            error=output.error_details or "Agent finished without opening a PR",
            structured_output=structured,
            agent_log_tail=log_tail,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _finalize(
        self,
        workspace_root: Path,
        running: RepoAgentStatus,
        *,
        status: RepoAgentPhase,
        pr_url: str | None = None,
        branch_name: str | None = None,
        error: str | None = None,
        structured_output: dict[str, Any] | None = None,
        agent_log_tail: str | None = None,
    ) -> RepoAgentStatus:
        final = running.model_copy(
            update={
                "status": status,
                "pr_url": pr_url,
                "branch_name": branch_name,
                "error": error,
                "structured_output": structured_output,
                "agent_log_tail": agent_log_tail,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        _write_status(workspace_root, final)
        await _sync_workspace_state(running.workspace_id, status)
        logger.info(
            "repo agent %s (%s) finished: status=%s pr_url=%s error=%s",
            running.workspace_id,
            running.kind,
            status,
            pr_url,
            error,
        )
        return final


# ---------------------------------------------------------------------------
# Private helpers — separated from the class to keep it mockable without
# monkey-patching instance methods.
# ---------------------------------------------------------------------------


# Keep the log excerpt short enough to live in a JSON field and render in a
# sidebar without scrollbars, but long enough to show the last ``gh pr create``
# output (which is the bit that explains why PR creation failed).
_LOG_TAIL_CHARS = 2000


def _tail(text: str) -> str | None:
    """Return the last ~2000 chars of *text* with a truncation marker."""
    if not text:
        return None
    if len(text) <= _LOG_TAIL_CHARS:
        return text
    return "…(truncated)…\n" + text[-_LOG_TAIL_CHARS:]
