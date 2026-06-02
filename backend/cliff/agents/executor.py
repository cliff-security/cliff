"""AgentExecutor — runs a single sub-agent end-to-end.

The executor is the bridge between "user wants to run an agent" and
"agent results are persisted everywhere." It sends a prompt to the
workspace's OpenCode process, collects the response, parses it, and
persists results to context files, sidebar state, and the DB.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx
from pydantic_ai.exceptions import (
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)

from cliff.agents.errors import (
    AgentBusyError,
    AgentProcessError,
    AgentRateLimitError,
    AgentTimeoutError,
)
from cliff.agents.output_parser import ParseResult
from cliff.agents.runtime._prompts import build_user_prompt
from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.no_tools import (
    NO_TOOLS_AGENT_TYPES,
    derive_summary,
    run_no_tools_agent,
)
from cliff.agents.runtime.provider import (
    ProviderConfigurationError,
    build_model,
)
from cliff.agents.runtime.remediation_executor import (
    build_agent as build_executor_agent,
)
from cliff.agents.runtime.tools.mcp import build_mcp_toolsets
from cliff.agents.sidebar_mapper import map_and_upsert
from cliff.db.repo_agent_run import (
    create_agent_run,
    get_agent_run,
    get_pa_message_history,
    list_agent_runs,
    update_agent_run,
)
from cliff.db.repo_finding import get_finding, update_finding
from cliff.db.repo_workspace import get_workspace
from cliff.models import AgentRun, AgentRunCreate, AgentRunUpdate, FindingUpdate
from cliff.services.evidence_guard import guard_evidence_output
from cliff.services.pr_verifier import verify_pr_url
from cliff.services.reference_verifier import clean_references
from cliff.workspace.workspace_dir import AGENT_TYPE_TO_SECTION, CONTEXT_SECTIONS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import aiosqlite
    from pydantic_ai.models import Model

    from cliff.workspace.context_builder import WorkspaceContextBuilder

logger = logging.getLogger(__name__)

# Overall ceiling for a non-tool agent run — a generous backstop, not the
# primary failure mechanism. Under low concurrency a structured-output
# completion finishes in well under 20 s, but under ~6-way concurrency the
# provider serialises/rate-limits and a *still-progressing* run can take
# 80-120 s (Q01-B12 — a tighter 75 s ceiling killed those mid-stream). The
# real fast-fail for a genuinely *hung* agent is the no-output stall in
# ``_collect_response`` (Q01-B10), which fires long before this. Tool
# agents (remediation_executor) override this — see ``execute`` — to 600 s.
DEFAULT_TIMEOUT: float = 150.0
# Extra buffer for asyncio.wait_for when permission waits are possible.
# The real timeout is enforced by stall detection, which accounts for
# time spent waiting for user permission decisions.
PERMISSION_WAIT_BUFFER: float = 600.0

# ---------------------------------------------------------------------------
# Provider rate-limit backoff (EF-B17)
# ---------------------------------------------------------------------------
# Upstream LLM providers (Anthropic, OpenRouter, OpenAI) start returning 429
# when the workspace pool runs more than one concurrent agent. OpenCode wraps
# the upstream 429 into a ``session.error`` SSE event that surfaces to the
# executor as an ``AgentRateLimitError``. Under pool>=2 (the Wave-2 cap)
# this used to fail the run on the first throttle; we now retry with
# exponential backoff + jitter up to ``RATE_LIMIT_MAX_ATTEMPTS`` before
# terminating the run with status ``rate_limited``.
#
# Tests monkey-patch these to 0.0 to avoid sleeping in unit suites.
RATE_LIMIT_MAX_ATTEMPTS: int = 3
RATE_LIMIT_BASE_DELAY_SECONDS: float = 2.0
RATE_LIMIT_MAX_DELAY_SECONDS: float = 16.0

def _rate_limit_backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter for retry ``attempt`` (1-based).

    attempt=1 -> base, attempt=2 -> 2*base, attempt=3 -> 4*base, capped at
    ``RATE_LIMIT_MAX_DELAY_SECONDS``. Adds up to one base-delay of jitter
    so concurrent workspaces don't all wake at the same instant.
    """
    base = RATE_LIMIT_BASE_DELAY_SECONDS
    exp = base * (2 ** max(attempt - 1, 0))
    jitter = random.uniform(0.0, base) if base > 0 else 0.0
    return min(exp + jitter, RATE_LIMIT_MAX_DELAY_SECONDS)

# ---------------------------------------------------------------------------
# Permission tier classification for tool-use approval.
# Keys are the "permission" field from OpenCode's permission.asked events.
# "auto" = grant immediately, "user" = surface to user for approval.
# Unknown tools default to "user" (safe default).
# ---------------------------------------------------------------------------

TOOL_TIERS: dict[str, str] = {
    "read": "auto",
    "webfetch": "auto",
    "bash": "user",
    "edit": "user",
    "mcp": "user",
}

# Agents that need tool access to do their job (e.g. git, gh CLI).
# Their bash/edit requests are classified per-command (see
# ``_classify_tool_request``) rather than blanket-approved.
_TOOL_AGENT_TYPES: set[str] = {"remediation_executor"}

# Tool-request classification for the remediation_executor. Three tiers:
#   "auto"  — grant immediately (routine git/gh/build commands)
#   "ask"   — escalate to the user for approval (destructive-but-conceivable,
#             or reaching outside the workspace)
#   "deny"  — reject immediately without asking (never legitimate for a
#             remediation agent; denying gives the agent fast feedback
#             instead of stalling on an approval that will never come)
#
# This is a denylist — defense-in-depth against a *confused* agent, layered
# on top of GIT_CEILING_DIRECTORIES and the hardened agent prompt. It is NOT
# a security boundary against a malicious agent; that needs process
# sandboxing (separate ADR). The remediation_executor's normal workflow
# (git clone/checkout/add/commit/push, gh pr create, build/test runners)
# matches none of these patterns and stays on the "auto" path.

# Never legitimate — hard-deny, don't even ask.
_CATASTROPHIC_BASH: tuple[str, ...] = (
    ":(){",          # fork bomb
    "mkfs",
    " dd ",
    "sudo ",
    "> /etc",
    ">/etc",
    "> /usr",
    ">/usr",
    "> /bin",
    ">/bin",
    "/etc/shadow",
    "/etc/passwd",
)

# Destructive or workspace-escaping, but conceivably part of a real fix —
# escalate to the user rather than hard-deny. (Per CEO: "removing a file
# requires asking for permission.")
_GATED_BASH: tuple[str, ...] = (
    "rm -",          # rm -rf, rm -f, …
    "rmdir",
    "git reset --hard",
    "git clean",
    "git push --force",
    "git push -f",
    "chmod ",
    "chown ",
    "cd /",
    "cd ~",
    "$home",
    "~/.ssh",
    "~/.aws",
    "~/.config",
)


def _is_pipe_to_shell(cmd: str) -> bool:
    """``curl …`` / ``wget …`` are fine on their own; piped into a shell
    they're remote code execution. Only the piped shape is dangerous."""
    fetches = ("curl ", "wget ")
    shells = ("| sh", "|sh", "| bash", "|bash", "|sh ", "| sh ")
    return any(f in cmd for f in fetches) and any(s in cmd for s in shells)


def _classify_tool_request(tool: str, patterns: list[str]) -> str:
    """Return ``"auto"``, ``"ask"``, or ``"deny"`` for an executor tool call.

    - ``bash`` — ``deny`` for catastrophic commands, ``ask`` for
      destructive-but-conceivable ones (rm, git reset --hard, …),
      ``auto`` for everything else.
    - ``edit`` — ``ask`` if the target path is absolute or climbs out of
      the workspace via ``..``; otherwise ``auto``.
    - ``external_directory`` — ``ask``. OpenCode raises this permission
      precisely when a tool reaches *outside* the workspace cwd, so it is
      the literal "the agent tried to leave the directory" signal.
    - anything else / unparseable — ``ask`` (safe default).
    """
    if tool == "external_directory":
        return "ask"

    if tool == "bash":
        cmd = " ".join(patterns).lower() if patterns else ""
        if not cmd:
            return "ask"  # can't inspect it → don't blanket-approve
        if _is_pipe_to_shell(cmd):
            return "deny"
        if any(bad in cmd for bad in _CATASTROPHIC_BASH):
            return "deny"
        if any(bad in cmd for bad in _GATED_BASH):
            return "ask"
        return "auto"

    if tool == "edit":
        for path in patterns:
            p = path.strip()
            if p.startswith("/") or p.startswith("~") or "../" in p:
                return "ask"
        return "auto"

    # mcp, unknown tools
    return "ask"


# Per-agent guidance appended to the prompt. Currently only the enricher,
# whose ``references`` array is shipped verbatim into the evidence sidebar
# as authoritative citations — weaker models fabricate specific identifiers
# (404ing GHSA IDs, commit URLs with garbled SHAs). The verifier in the
# executor is the deterministic safety net; this just lowers the rate at
# the source. (Q01-B08.)
_AGENT_GUIDANCE: dict[str, str] = {
    "finding_enricher": (
        "## Reference rules (strict)\n\n"
        "The \"references\" array is shown to a security engineer as "
        "authoritative citations. A fabricated citation is worse than a "
        "missing one.\n\n"
        "- ONLY include a URL you are confident resolves. When unsure, "
        "omit it — a short all-real list beats a long list with one "
        "fabricated entry.\n"
        "- Prefer the NVD page for a CVE you cite "
        "(https://nvd.nist.gov/vuln/detail/<CVE>) and generic "
        "authoritative docs (OWASP, CWE/MITRE, the vendor advisory index).\n"
        "- NEVER invent a GitHub advisory (GHSA-...) ID or a commit SHA. "
        "If you have not actually seen a specific identifier, do not "
        "construct one — omit the reference entirely.\n"
    ),
    "evidence_collector": (
        "## Completeness rules\n\n"
        "Every field must be a genuine best-effort answer — an empty "
        "``affected_files`` or a null ``current_version`` is a worse "
        "outcome than an imperfect one.\n\n"
        "- ``current_version``: the version currently in the repo. The "
        "finding's asset label already carries it (e.g. ``minimist@1.2.5`` "
        "-> ``1.2.5``) — never return null for a dependency finding.\n"
        "- ``affected_files``: for a dependency finding the manifest and "
        "lock files that pin the package (``package.json``, "
        "``package-lock.json``, ``yarn.lock``, …) are always affected — "
        "list them rather than returning an empty array.\n"
        "- ``fix_safety``: a major-version jump (e.g. 4.x -> 7.x) is "
        "``breaking_change`` or worse — never ``safe_bump``.\n"
    ),
}


def _load_workspace_data(
    workspace_dir: str, agent_type: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Read finding data and prior agent results from the workspace directory.

    Returns (finding_dict, prior_context_dict). Prior context only includes
    sections from agents earlier in the pipeline than the current one.
    """
    import json

    ctx_dir = Path(workspace_dir) / "context"

    # Read finding — must exist
    finding_path = ctx_dir / "finding.json"
    if not finding_path.exists():
        raise AgentProcessError(
            f"finding.json missing from workspace: {workspace_dir}"
        )
    finding = json.loads(finding_path.read_text())

    # Read prior context — only sections before this agent in the pipeline
    current_section = AGENT_TYPE_TO_SECTION.get(agent_type)
    if current_section:
        cutoff = CONTEXT_SECTIONS.index(current_section)
        prior_sections = CONTEXT_SECTIONS[:cutoff]
    else:
        prior_sections = CONTEXT_SECTIONS

    prior_context: dict[str, dict[str, Any]] = {}
    for section in prior_sections:
        section_path = ctx_dir / f"{section}.json"
        if section_path.exists():
            prior_context[section] = json.loads(section_path.read_text())

    return finding, prior_context


# ---------------------------------------------------------------------------
# Finding status auto-advance after agent completions (WP6 / T6.1).
# Status only moves forward — never regresses.
# ---------------------------------------------------------------------------

_STATUS_ORDINAL: dict[str, int] = {
    "new": 0,
    "triaged": 1,
    "in_progress": 2,
    "remediated": 3,
    "validated": 4,
    "closed": 5,
    "exception": 5,
}

# Agents that unconditionally advance status (forward-only check still applies).
_AGENT_STATUS_ADVANCE: dict[str, str] = {
    "finding_enricher": "triaged",
    "remediation_planner": "in_progress",
}


async def _advance_finding_status(
    db: aiosqlite.Connection,
    workspace_id: str,
    agent_type: str,
    structured_output: dict[str, Any],
) -> str | None:
    """Advance the finding status if appropriate after an agent completion.

    Returns the new status string if advanced, or None if no change.
    Status only moves forward (higher ordinal) — never regresses.
    """
    # 1. Determine target status
    target = _AGENT_STATUS_ADVANCE.get(agent_type)

    if agent_type == "remediation_executor" and structured_output.get("status") == "pr_created":
        target = "remediated"
    elif agent_type == "validation_checker" and structured_output.get("verdict") == "fixed":
        target = "validated"

    if not target:
        return None

    # 2. Resolve workspace -> finding
    workspace = await get_workspace(db, workspace_id)
    if not workspace:
        return None
    finding = await get_finding(db, workspace.finding_id)
    if not finding:
        return None

    # 3. Forward-only check
    current_ord = _STATUS_ORDINAL.get(finding.status, 0)
    target_ord = _STATUS_ORDINAL.get(target, 0)
    if target_ord <= current_ord:
        return None

    # 4. Update — also persist pr_url when the executor successfully opened a
    # PR (EF-B14). The pr_url has already been verified live on GitHub by
    # the verification step earlier in run(), so we know it's real. Skip the
    # write when the Finding already has a pr_url so an explicit user-supplied
    # value (PATCH /findings/{id}) is never clobbered.
    update_fields: dict[str, Any] = {"status": target}
    if (
        agent_type == "remediation_executor"
        and structured_output.get("status") == "pr_created"
        and structured_output.get("pr_url")
        and not finding.pr_url
    ):
        update_fields["pr_url"] = structured_output["pr_url"]
    await update_finding(db, finding.id, FindingUpdate(**update_fields))
    logger.info(
        "Finding %s status advanced: %s -> %s (agent: %s)",
        finding.id, finding.status, target, agent_type,
    )
    return target


def _humanize_process_error(raw: str) -> str:
    """Map opaque ``AgentProcessError`` strings to actionable user-facing text.

    Most agent failures actually originate at the AI provider (OpenRouter,
    Anthropic, OpenAI) and reach us through OpenCode as opaque "OpenCode
    error: …" wrappers. We unwrap the common ones — insufficient credits,
    rate limits, unauthorized — into short markdown the sidebar can render
    verbatim, with a remediation link where one exists. Falling back on the
    raw string is fine for unknown cases since it still surfaces in
    ``evidence_json`` for debugging.
    """
    lowered = raw.lower()
    if "more credits" in lowered or (
        "insufficient" in lowered and "credit" in lowered
    ):
        return (
            "**Out of AI provider credits.** OpenRouter rejected the request "
            "because your account balance can't fund this agent run. "
            "[Add credits](https://openrouter.ai/settings/credits) or switch "
            "to a cheaper model in Settings → AI provider, then click "
            "Approve to retry."
        )
    if "rate limit" in lowered or "429" in lowered or "too many requests" in lowered:
        return (
            "**AI provider rate limit hit.** The provider asked us to slow "
            "down. Wait a minute and click Approve to retry, or switch to a "
            "different model in Settings → AI provider."
        )
    if (
        "unauthorized" in lowered
        or "401" in lowered
        or "invalid api key" in lowered
        # Anthropic/OpenAI return this verbatim when the outbound request
        # carries no credential at all — the BYOK auth-propagation failure
        # mode. It is deterministic, so surface the actionable message
        # immediately rather than letting it read as a generic engine error.
        or "missing authentication" in lowered
        or "authentication header" in lowered
    ):
        return (
            "**AI provider rejected the credentials.** The configured API "
            "key is missing, revoked, or wrong for this model. Re-connect "
            "the provider in Settings → AI provider."
        )
    if "context length" in lowered or "context_length_exceeded" in lowered:
        return (
            "**Request exceeded the model's context window.** The finding "
            "or workspace context is too large for the configured model. "
            "Try a higher-context model in Settings → AI provider."
        )
    # Unknown — surface the raw text so the user has *something* to act on,
    # rather than the previous generic "Workspace AI engine unavailable."
    return f"**Workspace AI engine error.** {raw}"


@dataclass
class AgentExecutionResult:
    """Result returned by the executor after running an agent."""

    agent_run_id: str
    agent_type: str
    # EF-B17 — ``rate_limited`` joins ``failed`` as a non-success terminal
    # state. Callers that key off ``status == 'failed'`` should also treat
    # ``rate_limited`` as terminal-non-success; see ``pipeline.run_pipeline``.
    #
    # ``awaiting_permission`` (ADR-0047 / IMPL-0022 PR #2) is a NON-terminal
    # pause: the remediation_executor called a gated tool and the run is
    # parked on a DeferredToolRequests marker until the user approves/denies
    # via POST .../permission, which resumes it. ``run_pipeline`` stops on
    # it (can't proceed past a pending approval) but it is NOT a failure.
    status: Literal["completed", "failed", "rate_limited", "awaiting_permission"]
    parse_result: ParseResult
    sidebar_updated: bool = False
    context_version: int | None = None
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass
class _PaExecutorOutcome:
    """Result of one ``_run_pa_executor`` call — either the run completed
    (``parse_result`` set) or it paused on a gated tool
    (``permission_request`` + ``message_history_json`` set for resume)."""

    parse_result: ParseResult | None
    permission_request: dict[str, Any] | None
    message_history_json: str | None


def _build_permission_marker(reqs: DeferredToolRequests) -> dict[str, Any]:
    """Shape a ``DeferredToolRequests`` into the ``permission_request`` marker
    the frontend renders (``tool`` + ``patterns``) plus the ``tool_call_ids``
    the resume path needs to resolve each pending approval.

    Cliff's gated tools always raise ``ApprovalRequired`` (→ ``approvals``),
    so that list is non-empty in practice. We still guard the empty case:
    PA also models *external* deferred ``calls`` (a mechanism Cliff doesn't
    use), and an ``approvals``-empty ``DeferredToolRequests`` must park the
    run cleanly rather than ``IndexError`` out of the dispatch path.
    """
    approvals = reqs.approvals
    tool_call_ids = [p.tool_call_id for p in approvals]
    metadata = reqs.metadata or {}
    if approvals:
        primary = approvals[0]
        meta = metadata.get(primary.tool_call_id, {})
        tool = meta.get("tool", primary.tool_name)
        patterns = meta.get("patterns") or []
    else:
        tool = "unknown"
        patterns = []
    return {
        "tool": tool,
        "patterns": patterns,
        "tool_call_ids": tool_call_ids,
    }


def _summarize_executor(output: dict[str, Any]) -> str:
    """One-line summary for a remediation_executor run (the ``no_tools``
    ``derive_summary`` table covers only the six no-tools agents)."""
    status = output.get("status")
    pr_url = output.get("pr_url")
    if status == "pr_created" and pr_url:
        return f"Opened draft PR: {pr_url}"
    if status == "needs_approval":
        return "Paused — remediation needs approval."
    if status == "failed":
        return output.get("error_details") or "Remediation failed."
    return output.get("changes_summary") or "Changes applied."


class AgentExecutor:
    """Executes a single sub-agent within a workspace.

    Lifecycle:
        1. Check no other agent is running (→ AgentBusyError)
        2. Create AgentRun DB row (status=running)
        3. Get/start workspace OpenCode process
        4. Create fresh session, send prompt, collect response
        5. Parse response, persist to context + sidebar + DB
        6. Return AgentExecutionResult
    """

    def __init__(
        self,
        context_builder: WorkspaceContextBuilder,
        *,
        ai_env_resolver: Callable[[], Awaitable[dict[str, str]]] | None = None,
        ai_model_resolver: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        """Construct the executor.

        ``ai_env_resolver`` / ``ai_model_resolver`` (ADR-0047 / IMPL-0022)
        — the canonical AI-state callables the Pydantic AI path consumes
        to build a fresh ``Model`` per agent run. Optional so unit tests
        that do not exercise the PA path can leave them unset.
        """
        self._context_builder = context_builder
        self._ai_env_resolver = ai_env_resolver
        self._ai_model_resolver = ai_model_resolver
        self._active_runs: dict[str, str] = {}  # workspace_id -> agent_run_id

    def get_active_run_id(self, workspace_id: str) -> str | None:
        """Get the currently active agent run ID for a workspace."""
        return self._active_runs.get(workspace_id)

    def _cleanup_workspace_state(
        self,
        workspace_id: str,
        agent_run_id: str,
        *,
        agent_type: str = "",
        status: str = "completed",
    ) -> None:
        """Clear the active-run marker for a workspace after a run ends.

        ``agent_type`` / ``status`` are kept on the signature for call-site
        compatibility — they fed the old SSE ``agent_run_completed`` event
        (removed in PR2.D); the frontend now learns the outcome from the
        polled agent-runs query.
        """
        self._active_runs.pop(workspace_id, None)

    async def execute(
        self,
        workspace_id: str,
        agent_type: str,
        db: aiosqlite.Connection,
        *,
        workspace_dir: str,
        timeout: float = DEFAULT_TIMEOUT,
        on_progress: Callable[[str], None] | None = None,
        env_vars: dict[str, str] | None = None,
        user_note: str | None = None,
    ) -> AgentExecutionResult:
        """Execute a single agent run.

        Args:
            workspace_id: The workspace to run in.
            agent_type: One of the AgentType literals.
            db: Database connection.
            workspace_dir: Path to the workspace directory on disk.
            timeout: Maximum seconds to wait for the agent.
            on_progress: Optional callback for streaming text chunks.
            user_note: PRD-0006 Phase 2 — user refinement note. Only honored
                when ``agent_type == 'remediation_planner'``; ignored for
                other agents. Re-runs replace ``SidebarState.plan`` per the
                existing executor semantics.

        Returns:
            AgentExecutionResult with status and parsed output.

        Raises:
            AgentBusyError: If another agent is already running.
            AgentProcessError: If the workspace process can't start.
        """
        start_time = time.monotonic()

        # 1. Check no other agent is running
        await self.check_not_busy(db, workspace_id)

        # 2. Create AgentRun record
        agent_run = await create_agent_run(
            db,
            workspace_id,
            AgentRunCreate(agent_type=agent_type, status="running"),
        )

        # Mark the workspace busy for the run's lifetime. The frontend
        # learns about start/finish + any pending approval from the polled
        # agent-runs query (the SSE progress channel was removed in PR2.D).
        self._active_runs[workspace_id] = agent_run.id

        # Tool agents (e.g. remediation_executor) need more time for
        # git clone, push, and PR creation. ``effective_timeout`` is
        # initialised pre-try so the ``except AgentTimeoutError`` handler
        # below can render the user-facing error label even for early-path
        # timeouts.
        effective_timeout = (
            max(timeout, 600.0)
            if agent_type in _TOOL_AGENT_TYPES
            else timeout
        )

        try:
            # 3. Load workspace data — finding row + prior agent context.
            # The PA no-tools path needs nothing more; the OpenCode tool-
            # agent path additionally spins up a workspace OpenCode
            # process below.
            finding_data, prior_ctx = _load_workspace_data(
                workspace_dir, agent_type
            )

            if agent_type in _TOOL_AGENT_TYPES:
                # ========= Pydantic AI tool-agent path (ADR-0047) =========
                # The remediation_executor runs in-process with the five
                # tool functions (bash/edit/read/webfetch/gh). When it calls
                # a gated tool (rm -rf, edit outside the workspace, …) the
                # tool raises ApprovalRequired and the run returns a
                # DeferredToolRequests output — we park the marker + message
                # history on the agent_run row and stop; the user resumes it
                # via POST .../permission. (The old OpenCode subprocess path
                # is deleted in PR2.E; its now-orphaned plumbing —
                # _send_and_collect, the permission queue — goes with it.)
                outcome = await self._run_pa_executor(
                    WorkspaceDeps(
                        workspace_id=workspace_id,
                        workspace_dir=workspace_dir,
                        finding=finding_data,
                        prior_context=prior_ctx,
                        env_vars=env_vars or {},
                        user_note=None,
                    ),
                    effective_timeout,
                    db=db,
                )
                if outcome.permission_request is not None:
                    return await self._park_for_permission(
                        db, workspace_id, agent_run, outcome, start_time
                    )
                # By contract a non-paused outcome always carries a
                # parse_result; guard the typed Optional so a contract
                # violation surfaces as a failed run, not an AttributeError
                # crash in _finalize_run.
                if outcome.parse_result is None:
                    raise AgentProcessError(
                        "executor run returned neither a result nor a "
                        "permission request"
                    )
                parse_result = outcome.parse_result
            else:
                # ============ Pydantic AI no-tools path ================
                # ADR-0047 / IMPL-0022 PR #1 — six no-tools agents run
                # in-process through Pydantic AI. No subprocess, no SSE,
                # no parse retry: PA validates against the per-agent
                # ``output_type`` and the framework retries on validation
                # failures itself.
                #
                # ``user_note`` is the PRD-0006 Phase 2 refinement input;
                # only the remediation_planner honours it. Gate it so a
                # planner re-run with a user note doesn't bleed into a
                # subsequent enricher / exposure / evidence / validation
                # call on the same workspace.
                pa_user_note = (
                    user_note if agent_type == "remediation_planner" else None
                )
                parse_result = await self._run_pa_no_tools(
                    agent_type,
                    WorkspaceDeps(
                        workspace_id=workspace_id,
                        workspace_dir=workspace_dir,
                        finding=finding_data,
                        prior_context=prior_ctx,
                        env_vars=env_vars or {},
                        user_note=pa_user_note,
                    ),
                    effective_timeout,
                )

            # 7-9. Post-parse safeguards + persistence + run finalization.
            # Extracted into ``_finalize_run`` so the DeferredToolRequests
            # resume path (PR2.C) reaches the identical logic — one source
            # of truth for "how an agent result is verified, persisted, and
            # turned into an AgentExecutionResult".
            return await self._finalize_run(
                db,
                workspace_id=workspace_id,
                agent_type=agent_type,
                parse_result=parse_result,
                finding_data=finding_data,
                env_vars=env_vars,
                agent_run=agent_run,
                start_time=start_time,
            )

        except AgentTimeoutError:
            self._cleanup_workspace_state(
                workspace_id,
                agent_run.id,
                agent_type=agent_type,
                status="failed",
            )
            duration = time.monotonic() - start_time
            # Use ``effective_timeout`` (the real wall-clock ceiling for
            # this agent — 600s for tool agents, ``timeout`` otherwise),
            # not the input ``timeout`` arg. Reporting "timed out after
            # 150s" when the run actually went the full 600s sent users
            # hunting for a phantom 150s misconfiguration when the real
            # story was "tool agent burned its full 10-minute budget".
            timeout_error = f"Agent timed out after {effective_timeout:.0f}s"
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="failed",
                    summary_markdown="Agent timed out. Partial response may be available.",
                    last_error=timeout_error,
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="failed",
                parse_result=ParseResult(
                    success=False, raw_text="", error="timeout"
                ),
                error=timeout_error,
                duration_seconds=duration,
            )

        # EF-B17 — must precede ``AgentProcessError`` because
        # ``AgentRateLimitError`` is a subclass of it.
        except AgentRateLimitError as exc:
            self._cleanup_workspace_state(
                workspace_id,
                agent_run.id,
                agent_type=agent_type,
                status="rate_limited",
            )
            duration = time.monotonic() - start_time
            next_delay = _rate_limit_backoff_delay(RATE_LIMIT_MAX_ATTEMPTS)
            last_error = (
                f"Provider rate limit reached after "
                f"{RATE_LIMIT_MAX_ATTEMPTS} attempts; retry in "
                f"~{next_delay:.0f}s. Upstream: {exc}"
            )
            logger.warning(
                "Agent %s terminated rate_limited after %d attempts: %s",
                agent_type, RATE_LIMIT_MAX_ATTEMPTS, exc,
            )
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="rate_limited",
                    summary_markdown=_humanize_process_error(str(exc)),
                    last_error=last_error,
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="rate_limited",
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=last_error,
                duration_seconds=duration,
            )

        except AgentProcessError as exc:
            self._cleanup_workspace_state(
                workspace_id,
                agent_run.id,
                agent_type=agent_type,
                status="failed",
            )
            duration = time.monotonic() - start_time
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="failed",
                    summary_markdown=_humanize_process_error(str(exc)),
                    last_error=str(exc),
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="failed",
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=str(exc),
                duration_seconds=duration,
            )

        except Exception as exc:
            self._cleanup_workspace_state(
                workspace_id,
                agent_run.id,
                agent_type=agent_type,
                status="failed",
            )
            duration = time.monotonic() - start_time
            logger.exception("Unexpected error during agent execution")
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="failed",
                    summary_markdown=f"Unexpected error: {exc}",
                    last_error=str(exc),
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="failed",
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=str(exc),
                duration_seconds=duration,
            )

    async def _finalize_run(
        self,
        db: aiosqlite.Connection,
        *,
        workspace_id: str,
        agent_type: str,
        parse_result: ParseResult,
        finding_data: dict[str, Any],
        env_vars: dict[str, str] | None,
        agent_run: AgentRun,
        start_time: float,
    ) -> AgentExecutionResult:
        """Run post-parse safeguards, persist, and build the result.

        Shared by ``execute`` (initial completion) and the
        DeferredToolRequests resume path so both apply the identical
        reference/evidence/PR safeguards, context+sidebar+status
        persistence, and agent_run finalization.
        """
        # 7b-ref. Reference verification (Q01-B08). The finding_enricher
        # emits ``references`` as free-text and weaker models fabricate
        # specific identifiers — GHSA IDs that 404, commit URLs with
        # garbled SHAs — which then ship into the evidence sidebar with
        # the same authority as a real NVD link. Drop the ones we can
        # structurally disprove or that the host 404s. Best-effort: a
        # verifier failure must never fail the run.
        if (
            parse_result.success
            and agent_type == "finding_enricher"
            and parse_result.structured_output
        ):
            try:
                ref_check = await clean_references(
                    parse_result.structured_output.get("references")
                )
                if ref_check.dropped:
                    logger.warning(
                        "finding_enricher references dropped "
                        "(workspace=%s run=%s): %s",
                        workspace_id,
                        agent_run.id,
                        ref_check.dropped,
                    )
                    parse_result.structured_output["references"] = (
                        ref_check.kept
                    )
            except (httpx.HTTPError, ValueError, TypeError):
                # Networking, bad URLs, or upstream shape surprises —
                # log but never fail the run on reference verification.
                logger.warning(
                    "Reference verification raised for workspace %s",
                    workspace_id,
                    exc_info=True,
                )

        # 7b-ev. Evidence guards (Q01-B11, B13). The evidence_collector
        # classifies fix safety and reports the current version as
        # free-text — both drift under model/concurrency variance. For a
        # dependency finding Cliff already knows the authoritative
        # versions from the scanner, so reconcile the agent's output
        # against them (a major-version jump is never a ``safe_bump``;
        # ``current_version`` is backfilled). Best-effort.
        if (
            parse_result.success
            and agent_type == "evidence_collector"
            and parse_result.structured_output
        ):
            try:
                corrections = guard_evidence_output(
                    parse_result.structured_output, finding_data
                )
                if corrections:
                    logger.info(
                        "evidence_collector output corrected "
                        "(workspace=%s run=%s): %s",
                        workspace_id,
                        agent_run.id,
                        corrections,
                    )
            except (ValueError, TypeError, KeyError):
                # Evidence guard is pure data manipulation; the only
                # realistic raise surface is malformed structured
                # output. Log but never fail the run on it.
                logger.warning(
                    "Evidence guard raised for workspace %s",
                    workspace_id,
                    exc_info=True,
                )

        # 7c. PR URL verification (B16). The remediation_executor is the
        # only agent that claims to have opened a PR. If the emitted
        # ``pr_url`` can't be fetched from GitHub we flip the parse
        # result to a failure BEFORE anything is persisted — otherwise
        # we'd advance the finding to ``remediated`` with a hallucinated
        # URL and the user would later click a dead link.
        verification_error: str | None = None
        if (
            parse_result.success
            and agent_type == "remediation_executor"
            and (parse_result.structured_output or {}).get("status")
            == "pr_created"
        ):
            gh_token = (env_vars or {}).get("GH_TOKEN") or (
                env_vars or {}
            ).get("GITHUB_TOKEN")
            claimed = (parse_result.structured_output or {}).get("pr_url")
            verification = await verify_pr_url(claimed, token=gh_token)
            if not verification.ok:
                verification_error = (
                    "PR verification failed: "
                    f"{verification.reason}. Agent claimed "
                    f"pr_url={claimed!r}."
                )
                logger.warning(
                    "remediation_executor emitted unverifiable pr_url "
                    "(workspace=%s run=%s): %s",
                    workspace_id,
                    agent_run.id,
                    verification_error,
                )
                # Strip the false claim so downstream persistence doesn't
                # store a dead link in the sidebar.
                cleaned = dict(parse_result.structured_output or {})
                cleaned["status"] = "failed"
                cleaned["pr_url"] = None
                cleaned["error_details"] = verification_error
                parse_result = ParseResult(
                    success=False,
                    raw_text=parse_result.raw_text,
                    error=verification_error,
                    structured_output=cleaned,
                    summary=parse_result.summary,
                    confidence=parse_result.confidence,
                    suggested_next_action=parse_result.suggested_next_action,
                )

        # 8. Persist results
        sidebar_updated = False
        context_version = None

        if parse_result.success and parse_result.structured_output:
            # 8a. Update context files + re-render templates
            context_version = await self._context_builder.update_context(
                db,
                workspace_id,
                agent_type,
                parse_result.structured_output,
                summary=parse_result.summary,
            )

            # 8b. Update sidebar state (read-merge-write)
            await map_and_upsert(
                db,
                workspace_id,
                agent_type,
                parse_result.structured_output,
            )
            sidebar_updated = True

            # 8c. Auto-advance finding status (forward-only)
            await _advance_finding_status(
                db,
                workspace_id,
                agent_type,
                parse_result.structured_output,
            )

        # 9. Update AgentRun in DB
        duration = time.monotonic() - start_time
        # An agent run is only "completed" when parse succeeded AND
        # the PR (if any) verified. Without parse_result.success the
        # sidebar/context were never written (block 8a-c was skipped),
        # so rendering the row green would mis-signal a silent failure
        # — caught by the architect review of EF-B17 (more rate-limit
        # retries → more parse-failure-after-retry paths).
        parse_failed = not parse_result.success
        run_status: Literal["completed", "failed"] = (
            "failed"
            if verification_error or parse_failed
            else "completed"
        )
        failure_message = (
            verification_error
            or (parse_result.error if parse_failed else None)
        )
        await update_agent_run(
            db,
            agent_run.id,
            AgentRunUpdate(
                status=run_status,
                summary_markdown=(
                    failure_message
                    if failure_message
                    else parse_result.summary
                ),
                confidence=parse_result.confidence,
                structured_output=parse_result.structured_output,
                next_action_hint=parse_result.suggested_next_action,
                last_error=failure_message,
            ),
        )

        self._cleanup_workspace_state(
            workspace_id,
            agent_run.id,
            agent_type=agent_type,
            status=run_status,
        )
        return AgentExecutionResult(
            agent_run_id=agent_run.id,
            agent_type=agent_type,
            status=run_status,
            parse_result=parse_result,
            sidebar_updated=sidebar_updated,
            context_version=context_version,
            duration_seconds=duration,
            error=verification_error,
        )

    async def _run_pa_no_tools(
        self,
        agent_type: str,
        deps: WorkspaceDeps,
        timeout: float,
    ) -> ParseResult:
        """Run one of the six no-tools agents through Pydantic AI.

        Returns a :class:`ParseResult` shaped exactly like the OpenCode
        path so the downstream verifier + persistence blocks stay one
        diff away from their pre-migration behaviour. Translates the PA
        exception taxonomy into Cliff's existing
        ``AgentRateLimitError`` / ``AgentTimeoutError`` /
        ``AgentProcessError`` so the existing ``except`` handlers in
        ``execute()`` cover both substrates uniformly.

        The provider-rate-limit retry budget mirrors the OpenCode loop
        (``RATE_LIMIT_MAX_ATTEMPTS`` exponential-backoff retries). PA
        validation-failure retries are handled internally by Pydantic
        AI via ``output_type`` — we do not also wrap with the
        ``_RETRY_PROMPT`` loop.
        """
        if agent_type not in NO_TOOLS_AGENT_TYPES:
            # Defense-in-depth: caller (``execute``) already gates on
            # ``_TOOL_AGENT_TYPES``. Surface a deterministic error
            # instead of dispatching the wrong agent if that gate ever
            # drifts.
            raise AgentProcessError(
                f"agent_type {agent_type!r} is not registered for the "
                f"Pydantic AI no-tools path."
            )

        model = await self._resolve_active_model()
        structured_output = await self._run_pa_call(
            lambda: run_no_tools_agent(agent_type, deps, model),
            agent_type=agent_type,
            timeout=timeout,
        )
        summary = derive_summary(agent_type, structured_output)
        return ParseResult(
            success=True,
            raw_text="",
            structured_output=structured_output,
            summary=summary,
            confidence=None,
            suggested_next_action=None,
            error=None,
        )

    async def _resolve_active_model(self) -> Model:
        """Resolve the active provider env + model id and build a PA Model.

        Shared by the no-tools and executor PA paths. The resolvers wired
        in ``main.py`` are pure ``app.state`` reads and won't raise in
        practice, but the constructor accepts any awaitable — so a future
        hook that does I/O (DB roundtrip, vault decrypt) could raise here.
        Translate every failure into ``AgentProcessError`` so the outer
        ``except`` handler renders a clean ``status=failed`` row.
        """
        if self._ai_env_resolver is None or self._ai_model_resolver is None:
            raise AgentProcessError(
                "AI integration resolvers not wired into the executor. "
                "This is a configuration error — Cliff cannot run an "
                "agent without an active AI provider."
            )
        env_result, model_result = await asyncio.gather(
            self._ai_env_resolver(),
            self._ai_model_resolver(),
            return_exceptions=True,
        )
        if isinstance(env_result, BaseException):
            raise AgentProcessError(
                f"AI env resolver failed: {env_result}"
            ) from env_result
        if isinstance(model_result, BaseException):
            raise AgentProcessError(
                f"AI model resolver failed: {model_result}"
            ) from model_result
        try:
            return build_model(env_result, model_result)
        except ProviderConfigurationError as exc:
            raise AgentProcessError(str(exc)) from exc

    async def _run_pa_call(
        self,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        agent_type: str,
        timeout: float,
    ) -> Any:
        """Run a Pydantic AI coroutine with the shared rate-limit / timeout
        / exception-translation loop, returning whatever it produces.

        ``coro_factory`` is invoked fresh on each attempt (a re-roll or a
        rate-limit retry needs a new coroutine). Used by both the no-tools
        path (``run_no_tools_agent``) and the executor path
        (``agent.run``). Translates the PA exception taxonomy into Cliff's
        ``AgentTimeoutError`` / ``AgentRateLimitError`` / ``AgentProcessError``
        so the ``execute``/resume ``except`` handlers cover both uniformly.
        """
        last_rate_limit: ModelHTTPError | None = None
        # Parse-retry budget for UnexpectedModelBehavior (weak/old models
        # sometimes emit prose-only with no JSON shape; PA's own
        # output_type retry only fires on schema-shaped-but-invalid
        # responses, not on prose-only ones). One re-roll mirrors the
        # OpenCode-era ``_RETRY_PROMPT`` corrective-retry.
        parse_retries_used = 0
        for attempt in range(1, RATE_LIMIT_MAX_ATTEMPTS + 1):
            try:
                # ``timeout`` is per-attempt: rate-limit backoff sleeps +
                # retries mean total wall-clock can exceed it. Mirrors the
                # OpenCode-era loop semantics.
                return await asyncio.wait_for(coro_factory(), timeout=timeout)
            except TimeoutError as exc:
                raise AgentTimeoutError(
                    f"Pydantic AI agent {agent_type!r} did not complete "
                    f"within {timeout:.0f}s."
                ) from exc
            except ModelHTTPError as exc:
                # Log + raise with ``exc.message`` (not ``str(exc)``) — PA's
                # exception ``__str__`` embeds the raw provider response
                # body, which may echo prompt content (and any credentials
                # the agent was working with). The bounded message field is
                # safe; the body stays on the chained ``__cause__``.
                exc_message = getattr(exc, "message", str(exc))
                if exc.status_code != 429:
                    raise AgentProcessError(
                        f"AI provider error ({exc.status_code}): {exc_message}"
                    ) from exc
                last_rate_limit = exc
                if attempt >= RATE_LIMIT_MAX_ATTEMPTS:
                    raise AgentRateLimitError(
                        f"AI provider rate limit: {exc_message}"
                    ) from exc
                delay = _rate_limit_backoff_delay(attempt)
                logger.warning(
                    "Agent %s rate-limited on attempt %d/%d via PA; "
                    "sleeping %.1fs before retry: %s",
                    agent_type, attempt, RATE_LIMIT_MAX_ATTEMPTS,
                    delay, exc_message,
                )
                await asyncio.sleep(delay)
            except UsageLimitExceeded as exc:
                raise AgentProcessError(
                    f"Pydantic AI usage limit exceeded: {exc}"
                ) from exc
            except UnexpectedModelBehavior as exc:
                # Re-roll once: PA raises this on prose-only / empty /
                # thinking-only responses, where its output_type retry
                # doesn't fire. A re-roll at the same prompt often yields a
                # well-formed response on the next sample. Second
                # occurrence is terminal. Use ``exc.message`` (not
                # ``str(exc)``) — its ``__str__`` appends the raw model
                # body, which can echo prompt content / credentials.
                exc_message = getattr(exc, "message", str(exc))
                if parse_retries_used >= 1:
                    raise AgentProcessError(
                        f"AI model returned an unparseable response: "
                        f"{exc_message}"
                    ) from exc
                parse_retries_used += 1
                logger.warning(
                    "Agent %s returned an unparseable response on attempt "
                    "%d via PA; re-rolling once: %s",
                    agent_type, attempt, exc_message,
                )
                # No sleep — model re-roll, not rate-limit backoff.
            except UserError as exc:
                raise AgentProcessError(
                    f"Pydantic AI configuration error: {exc}"
                ) from exc
        # pragma: no cover — the 429 branch raises on the final attempt, so
        # the loop never exits without returning or raising. Kept as a
        # static-analysis backstop.
        assert last_rate_limit is not None  # noqa: S101
        raise AgentRateLimitError(str(last_rate_limit))

    async def _resolve_mcp_toolsets(
        self, db: aiosqlite.Connection
    ) -> list[Any]:
        """Resolve the workspace's MCP servers into PA toolsets.

        Best-effort — a broken integration must never block a remediation.
        The executor's core loop (clone/fix/commit/push/PR) uses no MCP
        tools; these are the configured integrations (ticketing, scanners).
        """
        resolver = getattr(self._context_builder, "_mcp_resolver", None)
        if resolver is None:
            return []
        try:
            result = await resolver.resolve_workspace(db)
            return build_mcp_toolsets(result.mcp_configs or None)
        except Exception:
            logger.warning(
                "MCP toolset resolution failed; running executor without MCP",
                exc_info=True,
            )
            return []

    async def _run_pa_executor(
        self,
        deps: WorkspaceDeps,
        timeout: float,
        *,
        db: aiosqlite.Connection,
        message_history: list[Any] | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
    ) -> _PaExecutorOutcome:
        """Run the remediation_executor through Pydantic AI.

        On an initial run ``message_history`` is None and the user prompt is
        built from ``deps``. On a resume after approve/deny, the caller
        passes the deserialized ``message_history`` + ``deferred_tool_results``
        and no new user prompt.

        Returns a :class:`_PaExecutorOutcome`: a completed ``ParseResult``
        (shaped like the no-tools path so ``_finalize_run`` handles it
        identically) when the run finishes, or a ``permission_request``
        marker + serialized ``message_history`` when a gated tool paused it.
        """
        model = await self._resolve_active_model()
        mcp_toolsets = await self._resolve_mcp_toolsets(db)
        agent = build_executor_agent(model, mcp_toolsets)
        user_prompt = None if message_history is not None else build_user_prompt(deps)

        result = await self._run_pa_call(
            lambda: agent.run(
                user_prompt,
                deps=deps,
                message_history=message_history,
                deferred_tool_results=deferred_tool_results,
            ),
            agent_type="remediation_executor",
            timeout=timeout,
        )

        output = result.output
        if isinstance(output, DeferredToolRequests):
            # A gated tool (rm -rf, edit outside the workspace, …) raised
            # ApprovalRequired. Persist the marker + the full conversation so
            # POST .../permission can resume via ``deferred_tool_results``.
            return _PaExecutorOutcome(
                parse_result=None,
                permission_request=_build_permission_marker(output),
                message_history_json=result.all_messages_json().decode("utf-8"),
            )

        structured = output.model_dump()
        return _PaExecutorOutcome(
            parse_result=ParseResult(
                success=True,
                raw_text="",
                structured_output=structured,
                summary=_summarize_executor(structured),
                confidence=None,
                suggested_next_action=None,
                error=None,
            ),
            permission_request=None,
            message_history_json=None,
        )

    async def _park_for_permission(
        self,
        db: aiosqlite.Connection,
        workspace_id: str,
        agent_run: AgentRun,
        outcome: _PaExecutorOutcome,
        start_time: float,
    ) -> AgentExecutionResult:
        """Persist a paused executor run and return ``awaiting_permission``.

        The agent_run row stays ``status='running'`` + ``permission_pending``
        so ``issue_derivation`` routes the finding to the "Needs you" bucket;
        the workspace stays busy (active-run state untouched) so no other
        agent starts. ``resume_executor`` (via POST .../permission) continues
        it; ``_finalize_run`` clears the busy state when it completes.
        """
        await update_agent_run(
            db,
            agent_run.id,
            AgentRunUpdate(
                permission_pending=True,
                permission_request=outcome.permission_request,
                pa_message_history=outcome.message_history_json,
            ),
        )
        duration = time.monotonic() - start_time
        return AgentExecutionResult(
            agent_run_id=agent_run.id,
            agent_type=agent_run.agent_type,
            status="awaiting_permission",
            parse_result=ParseResult(success=False, raw_text="", error=None),
            duration_seconds=duration,
        )

    async def resume_executor(
        self,
        db: aiosqlite.Connection,
        workspace_id: str,
        run_id: str,
        *,
        approved: bool,
        workspace_dir: str,
        deny_message: str | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> AgentExecutionResult:
        """Resume a paused remediation_executor run after approve/deny.

        Rebuilds the agent + workspace deps, deserializes the stored message
        history, and re-enters the run with a ``DeferredToolResults`` carrying
        the user's decision for every pending tool call. On completion →
        ``_finalize_run`` (identical persistence to the initial path); if the
        model immediately calls another gated tool → park again.
        """
        agent_run = await get_agent_run(db, run_id)
        if (
            agent_run is None
            or not agent_run.permission_pending
            or not agent_run.permission_request
        ):
            raise AgentProcessError(
                "No pending permission request for this agent run."
            )
        history_json = await get_pa_message_history(db, run_id)
        if not history_json:
            raise AgentProcessError(
                "Paused run has no stored message history; cannot resume."
            )

        start_time = time.monotonic()
        # Clear the marker up front so a duplicate POST can't double-resume
        # and a crash mid-resume reconciles to ``failed`` (not a stale pause).
        await update_agent_run(
            db,
            run_id,
            AgentRunUpdate(
                permission_pending=False,
                permission_request=None,
                pa_message_history=None,
            ),
        )

        try:
            finding_data, prior_ctx = _load_workspace_data(
                workspace_dir, agent_run.agent_type
            )
            deps = WorkspaceDeps(
                workspace_id=workspace_id,
                workspace_dir=workspace_dir,
                finding=finding_data,
                prior_context=prior_ctx,
                env_vars=env_vars or {},
                user_note=None,
            )
            message_history = ModelMessagesTypeAdapter.validate_json(
                history_json
            )
            # ``or []`` (not a ``.get`` default) so an explicit null in the
            # marker JSON can't slip a None into the comprehension below.
            tool_call_ids = (agent_run.permission_request or {}).get(
                "tool_call_ids"
            ) or []
            decision = (
                ToolApproved()
                if approved
                else ToolDenied(
                    message=deny_message
                    or "The user denied this command. Choose another approach."
                )
            )
            results = DeferredToolResults(
                approvals={tcid: decision for tcid in tool_call_ids}
            )

            outcome = await self._run_pa_executor(
                deps,
                max(DEFAULT_TIMEOUT, 600.0),
                db=db,
                message_history=message_history,
                deferred_tool_results=results,
            )
            if outcome.permission_request is not None:
                return await self._park_for_permission(
                    db, workspace_id, agent_run, outcome, start_time
                )
            return await self._finalize_run(
                db,
                workspace_id=workspace_id,
                agent_type=agent_run.agent_type,
                parse_result=outcome.parse_result,
                finding_data=finding_data,
                env_vars=env_vars,
                agent_run=agent_run,
                start_time=start_time,
            )
        except (AgentTimeoutError, AgentRateLimitError, AgentProcessError) as exc:
            status: Literal["failed", "rate_limited"] = (
                "rate_limited"
                if isinstance(exc, AgentRateLimitError)
                else "failed"
            )
            self._cleanup_workspace_state(
                workspace_id, run_id, agent_type=agent_run.agent_type, status=status
            )
            await update_agent_run(
                db,
                run_id,
                AgentRunUpdate(
                    status=status,
                    summary_markdown=_humanize_process_error(str(exc)),
                    last_error=str(exc),
                ),
            )
            return AgentExecutionResult(
                agent_run_id=run_id,
                agent_type=agent_run.agent_type,
                status=status,
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=str(exc),
                duration_seconds=time.monotonic() - start_time,
            )
        except Exception as exc:  # noqa: BLE001
            # Catch-all so a resume can NEVER leave the run wedged at
            # ``running`` + ``permission_pending`` (workspace busy forever).
            # The setup steps inside the try — ModelMessagesTypeAdapter.
            # validate_json on a corrupt/truncated history, or a malformed
            # tool_call_ids — raise ValidationError/TypeError, which the
            # specific handler above doesn't cover. Mark the run failed so
            # the finding routes to the Retry CTA instead of hanging.
            logger.exception(
                "Resume failed unexpectedly for run %s; marking failed", run_id
            )
            self._cleanup_workspace_state(
                workspace_id, run_id, agent_type=agent_run.agent_type, status="failed"
            )
            await update_agent_run(
                db,
                run_id,
                AgentRunUpdate(
                    status="failed",
                    summary_markdown=_humanize_process_error(str(exc)),
                    last_error=f"Resume failed: {exc}",
                ),
            )
            return AgentExecutionResult(
                agent_run_id=run_id,
                agent_type=agent_run.agent_type,
                status="failed",
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=str(exc),
                duration_seconds=time.monotonic() - start_time,
            )

    async def check_not_busy(
        self, db: aiosqlite.Connection, workspace_id: str
    ) -> None:
        """Raise AgentBusyError if another agent is already running."""
        runs = await list_agent_runs(db, workspace_id, limit=10)
        for run in runs:
            if run.status == "running":
                raise AgentBusyError(
                    f"Agent '{run.agent_type}' is already running "
                    f"in workspace {workspace_id}"
                )

