"""E2E tests for the agent orchestration pipeline with real OpenCode + LLM.

These tests start a real workspace OpenCode process, execute a real sub-agent
(Finding Enricher), and verify that structured output is parsed, context files
are written, and sidebar state is updated in the DB.

Requires:
  - OpenCode binary installed
  - OPENAI_API_KEY (or another provider key) set in the environment

Auto-skipped if prerequisites are missing (via e2e/conftest.py markers).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from cliff.agents import AgentTemplateEngine
from cliff.agents.executor import AgentExecutor
from cliff.agents.pipeline import suggest_next
from cliff.db.connection import close_db, init_db
from cliff.db.repo_finding import create_finding
from cliff.db.repo_workspace import create_workspace
from cliff.engine.pool import PortAllocator, WorkspaceProcessPool
from cliff.models import Finding, FindingCreate, WorkspaceCreate
from cliff.workspace import WorkspaceDirManager
from cliff.workspace.context_builder import WorkspaceContextBuilder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding() -> Finding:
    """Create a realistic security finding for E2E testing."""
    now = datetime.now(UTC)
    return Finding(
        id="f-e2e-enricher",
        source_type="test",
        source_id="test-f-e2e-enricher",
        title="Log4j RCE (CVE-2021-44228)",
        description=(
            "Apache Log4j2 versions 2.0-beta9 through 2.14.1 contain a "
            "JNDI lookup feature that allows remote code execution. An "
            "attacker who can control log messages can execute arbitrary "
            "code loaded from LDAP servers."
        ),
        raw_severity="critical",
        normalized_priority="P1",
        asset_id="app-server-prod-01",
        asset_label="app-server-prod-01",
        status="new",
        why_this_matters="Known active exploitation in the wild since Dec 2021.",
        created_at=now,
        updated_at=now,
    )


def _create_workspace_dir(
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
    workspace_id: str,
    finding: Finding,
) -> Path:
    """Create a workspace directory with finding context and agent templates."""
    ws = dir_manager.create(workspace_id, finding)
    finding_dict = finding.model_dump(mode="json")
    template_engine.write_agents(ws.agents_dir, finding=finding_dict)
    return ws.root


async def _seed_db_and_create_workspace(
    db,
    finding: Finding,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Insert DB rows and create workspace directory. Returns (workspace, ws_dir)."""
    # Insert finding row
    db_finding = await create_finding(
        db,
        FindingCreate(
            source_type=finding.source_type,
            source_id=finding.source_id,
            title=finding.title,
            description=finding.description,
            raw_severity=finding.raw_severity,
            normalized_priority=finding.normalized_priority,
            asset_id=finding.asset_id,
            asset_label=finding.asset_label,
            status=finding.status,
        ),
    )

    # Insert workspace row
    workspace = await create_workspace(
        db,
        WorkspaceCreate(finding_id=db_finding.id),
    )

    # Create directory using the DB-generated workspace ID
    ws_dir = _create_workspace_dir(
        dir_manager, template_engine, workspace.id, finding
    )

    return workspace, ws_dir


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dir_manager(tmp_path: Path) -> WorkspaceDirManager:
    return WorkspaceDirManager(base_dir=tmp_path / "workspaces")


@pytest.fixture
def template_engine() -> AgentTemplateEngine:
    return AgentTemplateEngine()


# Shared resolvers: the pool needs them so OpenCode subprocesses get a
# usable env; the executor needs the same callables so the PA no-tools
# path can construct a Model. Module-level so a future fixture (or test)
# doesn't accidentally diverge from the pair the pool uses.
async def _e2e_env_resolver() -> dict[str, str]:
    import os
    key = os.environ.get("OPENAI_API_KEY", "")
    return {"OPENAI_API_KEY": key} if key else {}


async def _e2e_model_resolver() -> str | None:
    # Pin to a cheap available OpenAI model. Without a canonical model
    # the per-workspace opencode.json carries no ``model`` field and
    # OpenCode falls back to a built-in default (typically Anthropic)
    # that needs a key we haven't injected; the PA path likewise needs
    # a model id with a provider prefix it can route.
    return "openai/gpt-4.1-nano"


@pytest.fixture
async def pool(db):
    """Process pool using ports 4230-4240 to avoid conflicts with other E2E tests.

    Wires an ``env_resolver`` that drains ``OPENAI_API_KEY`` from the host
    env into the spawned workspace OpenCode subprocess. Without it the
    pool's provider-env-var scrubber (commit 2321931 — workspace isolation
    from host AI env) strips the host key and OpenCode 401s with "Missing
    Authentication header" — which is what we test, not what we want to
    test against.
    """
    p = WorkspaceProcessPool(
        port_allocator=PortAllocator(start=4230, end=4240),
        env_resolver=_e2e_env_resolver,
        model_resolver=_e2e_model_resolver,
    )
    yield p
    await p.stop_all()


@pytest.fixture
async def db():
    """In-memory SQLite database with schema initialized."""
    connection = await init_db(":memory:")
    yield connection
    await close_db()


@pytest.fixture
def context_builder(
    dir_manager: WorkspaceDirManager, template_engine: AgentTemplateEngine
) -> WorkspaceContextBuilder:
    return WorkspaceContextBuilder(dir_manager, template_engine)


@pytest.fixture
def executor(
    pool: WorkspaceProcessPool, context_builder: WorkspaceContextBuilder
) -> AgentExecutor:
    # The PA no-tools path requires both resolvers — same callables the
    # pool consumes so the executor and OpenCode subprocesses agree on
    # which provider+key+model is active for this run (ADR-0047).
    return AgentExecutor(
        pool,
        context_builder,
        ai_env_resolver=_e2e_env_resolver,
        ai_model_resolver=_e2e_model_resolver,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_execute_enricher_e2e(
    executor: AgentExecutor,
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
    db,
):
    """Execute the Finding Enricher on a real finding with a real LLM.

    This is the core E2E test — it proves the full pipeline works:
    prompt → OpenCode → LLM → response → parse → persist.
    """
    finding = _make_finding()
    workspace, ws_dir = await _seed_db_and_create_workspace(
        db, finding, dir_manager, template_engine
    )

    # Execute the enricher agent
    result = await executor.execute(
        workspace.id,
        "finding_enricher",
        db,
        workspace_dir=str(ws_dir),
        timeout=120.0,
    )

    # The agent should complete (not timeout or crash)
    assert result.status == "completed", (
        f"Agent failed: {result.error or result.parse_result.error}"
    )

    # ADR-0047 — the PA no-tools path returns the validated dict directly,
    # so ``raw_text`` is empty by design (OpenCode-era prose was the input
    # to a separate parse step that this PR replaces). The shape contract
    # is now ``structured_output``.
    assert result.parse_result.success, (
        f"Enricher PA call did not produce parseable output: "
        f"{result.parse_result.error}"
    )
    assert result.parse_result.structured_output, (
        "PA path returned an empty structured_output dict"
    )

    # If structured output was parsed successfully, verify persistence
    if result.parse_result.success and result.parse_result.structured_output:
        # Context file should exist on disk
        enrichment_file = ws_dir / "context" / "enrichment.json"
        assert enrichment_file.exists(), "enrichment.json not written to disk"

        enrichment_data = json.loads(enrichment_file.read_text())
        assert isinstance(enrichment_data, dict)

        # CONTEXT.md should have been regenerated
        context_md = ws_dir / "CONTEXT.md"
        assert context_md.exists()
        context_text = context_md.read_text()
        assert "enrichment" in context_text.lower() or "CVE" in context_text

        # Sidebar should have been updated
        assert result.sidebar_updated is True
        assert result.context_version is not None
        assert result.context_version > 0
    else:
        # Even if parse failed, we should still have completed successfully
        # (the LLM responded, just not in the expected format)
        pytest.skip(
            f"LLM responded but output wasn't structured JSON: "
            f"{result.parse_result.error}"
        )


async def test_suggest_next_advances_after_enrichment(
    executor: AgentExecutor,
    context_builder: WorkspaceContextBuilder,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
    db,
):
    """After enricher completes, suggest_next should return exposure_analyzer.

    Per IMPL-0022 PR #1 (ADR-0047), ``owner_resolver`` was dropped from
    the forward pipeline; the next step after enrichment is now
    ``exposure_analyzer``. The agent stays callable directly.
    """
    finding = _make_finding()
    workspace, ws_dir = await _seed_db_and_create_workspace(
        db, finding, dir_manager, template_engine
    )

    # Before enrichment: should suggest enricher
    snapshot_before = await context_builder.get_context_snapshot(workspace.id)
    history_before = snapshot_before.pop("agent_run_history", [])
    suggestion_before = suggest_next(snapshot_before, history_before)
    assert suggestion_before is not None
    assert suggestion_before.agent_type == "finding_enricher"

    # Run enricher
    result = await executor.execute(
        workspace.id,
        "finding_enricher",
        db,
        workspace_dir=str(ws_dir),
        timeout=120.0,
    )

    if not (result.parse_result.success and result.parse_result.structured_output):
        pytest.skip("Enricher didn't produce structured output — can't test pipeline advance")

    # After enrichment: should suggest exposure_analyzer (next in
    # PIPELINE_ORDER after owner_resolver was dropped).
    snapshot_after = await context_builder.get_context_snapshot(workspace.id)
    history_after = snapshot_after.pop("agent_run_history", [])
    suggestion_after = suggest_next(snapshot_after, history_after)
    assert suggestion_after is not None
    assert suggestion_after.agent_type == "exposure_analyzer", (
        f"Expected exposure_analyzer but got {suggestion_after.agent_type}"
    )


async def test_suggest_next_on_fresh_workspace(
    context_builder: WorkspaceContextBuilder,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """suggest_next on a fresh workspace returns finding_enricher."""
    finding = _make_finding()
    _create_workspace_dir(
        dir_manager, template_engine, "ws-e2e-fresh", finding
    )

    snapshot = await context_builder.get_context_snapshot("ws-e2e-fresh")
    history = snapshot.pop("agent_run_history", [])
    suggestion = suggest_next(snapshot, history)

    assert suggestion is not None
    assert suggestion.agent_type == "finding_enricher"
    assert suggestion.priority == "recommended"


async def test_workspace_process_starts_and_responds(
    pool: WorkspaceProcessPool,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
):
    """Verify workspace process starts and can create a session."""
    finding = _make_finding()
    ws_dir = _create_workspace_dir(
        dir_manager, template_engine, "ws-e2e-process", finding
    )

    client = await pool.start("ws-e2e-process", ws_dir)
    assert client is not None

    healthy = await client.health_check()
    assert healthy is True

    session = await client.create_session()
    assert session.id


async def test_enricher_progress_callback(
    executor: AgentExecutor,
    dir_manager: WorkspaceDirManager,
    template_engine: AgentTemplateEngine,
    db,
):
    """The no-tools PA path completes without invoking on_progress.

    ADR-0047 — streaming text deltas was an OpenCode SSE-plumbing feature
    that mattered when the no-tools agents emitted prose mid-flight. The
    PA no-tools path is a single ``agent.run()`` that returns the
    validated output dict in one call; there's nothing to stream. The
    callback contract is preserved (``on_progress`` is still accepted)
    so tool agents like remediation_executor — which DO stream — keep
    their existing UX. PR #2 covers tool-agent streaming under PA.
    """
    finding = _make_finding()
    workspace, ws_dir = await _seed_db_and_create_workspace(
        db, finding, dir_manager, template_engine
    )

    progress_texts: list[str] = []

    result = await executor.execute(
        workspace.id,
        "finding_enricher",
        db,
        workspace_dir=str(ws_dir),
        timeout=120.0,
        on_progress=progress_texts.append,
    )

    assert result.status == "completed"
    # Locking down the behavior change: PA no-tools agents do NOT emit
    # progress callbacks. If a future PR adds streaming for no-tools
    # agents (or accidentally re-wires the OpenCode path here), this
    # assertion fires and the change is conscious, not silent.
    assert progress_texts == [], (
        f"PA no-tools path emitted progress callbacks unexpectedly: "
        f"{progress_texts!r}"
    )
