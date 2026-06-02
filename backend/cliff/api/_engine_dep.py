"""DI seam for the assessment engine.

Session B landed the protocol + a stub provider; PR-B (PRD-0003 v0.2) wires
the v0.2 engine here — Trivy + Semgrep via :class:`SubprocessScannerRunner`,
posture via the 15-check orchestrator, cloning via :class:`RepoCloner`. The
protocol gains an ``on_tool`` callback so the route layer can stream the
ADR-0032 ``tools[]`` payload to the in-flight UI.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

# Request stays in runtime imports on purpose. FastAPI resolves the
# get_repo_workspace_spawner(request: Request) annotation via
# typing.get_type_hints at OpenAPI schema build time; pydantic's
# TypeAdapter raises class-not-fully-defined if Request only lives in a
# TYPE_CHECKING block. Do not move.
from fastapi import Request  # noqa: TCH002

from cliff.config import settings

if TYPE_CHECKING:
    import aiosqlite

    from cliff.models import AssessmentResult, AssessmentTool
    from cliff.workspace.workspace_dir_manager import WorkspaceKind

logger = logging.getLogger(__name__)


StepCallback = Callable[[str], Awaitable[None]]
ToolCallback = Callable[["AssessmentTool"], Awaitable[None]]
EnvResolver = Callable[[], Awaitable[dict[str, str]]]
ModelResolver = Callable[[], Awaitable[str | None]]


class AssessmentEngineProtocol(Protocol):
    """Contract for the assessment engine.

    ``on_step`` receives one of the six v0.2 stage keys (``detect``,
    ``trivy_vuln``, ``trivy_secret``, ``semgrep``, ``posture``,
    ``descriptions``) so the API layer can surface progress to the status
    endpoint. ``on_tool`` receives the per-pill state of the ``tools[]``
    payload (ADR-0032). Implementations may ignore either.
    """

    async def run_assessment(
        self,
        repo_url: str,
        *,
        assessment_id: str,
        db: aiosqlite.Connection | None = None,
        on_step: StepCallback | None = None,
        on_tool: ToolCallback | None = None,
    ) -> AssessmentResult: ...


async def _github_token_from_integration() -> str | None:
    """Resolve the GitHub PAT from the ``github`` Integrations row + vault."""
    from cliff.db.connection import _db
    from cliff.db.repo_integration import list_integrations
    from cliff.main import app

    if _db is None:
        return None
    integrations = await list_integrations(_db)
    # Match by provider_name case-insensitively so the lookup works
    # whether the row was created by the PAT onboarding ("GitHub") or
    # the GitHub App + Device Flow path ("GitHub" too, post-alignment;
    # a lowercase legacy row from an earlier dev DB also resolves).
    github = next(
        (
            i
            for i in integrations
            if i.provider_name.lower() == "github" and i.enabled
        ),
        None,
    )
    if github is None:
        return None

    vault = getattr(app.state, "vault", None)
    if vault is None:
        return None

    try:
        return await vault.retrieve(github.id, "github_personal_access_token")
    except Exception:
        return None


class _RealAssessmentEngine:
    """Production engine wired for use by the FastAPI lifespan.

    Constructs a :class:`SubprocessScannerRunner` per call (cheap — no state
    beyond the bin dir), a :class:`RepoCloner` with the same token provider
    every other agent path uses, and a fresh ``httpx.AsyncClient`` per run for
    the GitHub posture-check probes.
    """

    def __init__(
        self,
        *,
        token_provider: Callable[[], Awaitable[str | None]],
    ) -> None:
        self._token_provider = token_provider

    async def run_assessment(
        self,
        repo_url: str,
        *,
        assessment_id: str,
        db: aiosqlite.Connection | None = None,
        on_step: StepCallback | None = None,
        on_tool: ToolCallback | None = None,
    ) -> AssessmentResult:
        # Late imports — these pull in httpx + the scanner runner which we
        # don't want at module load on test paths that never touch the engine.
        import httpx

        from cliff.assessment.engine import RepoCloner, run_assessment
        from cliff.assessment.posture.github_client import GithubClient
        from cliff.assessment.scanners.runner import SubprocessScannerRunner

        bin_dir = settings.resolve_scanner_bin_dir()
        runner = SubprocessScannerRunner(bin_dir=bin_dir)
        cloner = RepoCloner(
            token_provider=self._token_provider,
            tmp_root=settings.resolve_data_dir() / "clones",
        )

        token = await self._token_provider()
        async with httpx.AsyncClient(timeout=30.0) as http:
            gh = GithubClient(http, token=token)
            return await run_assessment(
                repo_url,
                gh_client=gh,
                runner=runner,
                cloner=cloner,
                assessment_id=assessment_id,
                db=db,
                on_step=on_step,
                on_tool=on_tool,
            )


def get_assessment_engine() -> AssessmentEngineProtocol:
    """Return the production engine.

    Tests override via ``app.dependency_overrides[get_assessment_engine] = lambda: fake``.
    """
    return _RealAssessmentEngine(token_provider=_github_token_from_integration)


# --- Workspace dir manager seam (Milestone D3) ----------------------------------


class RepoWorkspaceSpawnerProtocol(Protocol):
    """Minimal contract for spawning a posture-fix repo workspace (Session C)."""

    async def spawn_repo_workspace(
        self,
        *,
        kind: WorkspaceKind,
        repo_url: str,
        params: dict[str, Any] | None = None,
    ) -> str: ...  # returns workspace_id


_CHECK_NAME_FOR_KIND: dict[str, str] = {
    "repo_action_security_md": "security_md",
    "repo_action_dependabot": "dependabot_config",
}


class _DefaultRepoWorkspaceSpawner:
    """Production spawner backed by ``WorkspaceDirManager.create_repo_workspace``."""

    def __init__(
        self,
        *,
        env_resolver: EnvResolver,
        model_resolver: ModelResolver,
    ) -> None:
        # The repo-action generator runs in-process via Pydantic AI now
        # (IMPL-0022 PR #3c); these resolve the app-level AI provider env +
        # active model for ``RepoAgentRunner``.
        self._env_resolver = env_resolver
        self._model_resolver = model_resolver

    async def spawn_repo_workspace(
        self,
        *,
        kind: WorkspaceKind,
        repo_url: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        import shutil

        from cliff.db.connection import _db
        from cliff.db.repo_workspace import create_repo_action_workspace
        from cliff.workspace.repo_workspace_runner import RepoAgentRunner
        from cliff.workspace.workspace_dir_manager import WorkspaceDirManager

        token = await _github_token_from_integration()
        data_dir = settings.resolve_data_dir()
        base_dir = data_dir / "workspaces"
        manager = WorkspaceDirManager(base_dir=base_dir)
        model = settings.opencode_model or None
        workspace_id = manager.create_repo_workspace(
            kind,
            repo_url=repo_url,
            params=params,
            gh_token=token,
            model=model,
        )
        workspace_root = base_dir / workspace_id

        if _db is not None:
            check_name = _CHECK_NAME_FOR_KIND.get(kind.value)
            if check_name is not None:
                try:
                    await create_repo_action_workspace(
                        _db,
                        workspace_id=workspace_id,
                        kind=kind.value,
                        source_check_name=check_name,
                        workspace_dir=str(workspace_root),
                    )
                except Exception:
                    shutil.rmtree(workspace_root, ignore_errors=True)
                    raise

        runner = RepoAgentRunner(
            env_resolver=self._env_resolver,
            model_resolver=self._model_resolver,
        )

        async def _run() -> None:
            try:
                await runner.run(
                    workspace_id=workspace_id,
                    workspace_root=workspace_root,
                    kind=kind,
                    repo_url=repo_url,
                    gh_token=token,
                    params=params,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "RepoAgentRunner raised unexpectedly for %s", workspace_id
                )

        asyncio.create_task(_run(), name=f"repo-agent:{workspace_id}")
        return workspace_id


def get_repo_workspace_spawner(request: Request) -> RepoWorkspaceSpawnerProtocol:
    """Default provider — wires the spawner to the app-level AI resolvers.

    Reads the canonical AI env + model from ``app.state`` at run time (the
    lifespan refresh keeps these current), so a background repo-agent run
    picks up a provider/model change without a restart.
    """
    app = request.app

    async def _env_resolver() -> dict[str, str]:
        return dict(getattr(app.state, "ai_env_cache", {}) or {})

    async def _model_resolver() -> str | None:
        return getattr(app.state, "ai_model_cache", None)

    return _DefaultRepoWorkspaceSpawner(
        env_resolver=_env_resolver,
        model_resolver=_model_resolver,
    )
