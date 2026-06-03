"""Tests for the AgentExecutor."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cliff.agents.errors import AgentBusyError, AgentTimeoutError
from cliff.agents.executor import (
    TOOL_TIERS,
    AgentExecutor,
    _classify_tool_request,
    _load_workspace_data,
)
from cliff.agents.output_parser import ParseResult
from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.models import AgentRun

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_FINDING = {
    "id": "390f95cd-fcbb-416d-b3af-51e86dfc3d29",
    "title": "Apache Tomcat vulnerable version on web-prod-17",
    "source_type": "tenable",
    "source_id": "CVE-2023-46589",
    "description": (
        "CVE-2023-46589 identified on web-prod-17. "
        "Apache Tomcat 9.0.82 is vulnerable to HTTP request smuggling."
    ),
    "raw_severity": "critical",
    "normalized_priority": "P1",
    "asset_id": "web-prod-17",
    "asset_label": "Web Server 17 (Production)",
    "status": "new",
    "likely_owner": "Platform Engineering",
}

_SAMPLE_ENRICHMENT = {
    "normalized_title": "Apache Tomcat HTTP Request Smuggling",
    "cve_ids": ["CVE-2023-46589"],
    "cvss_score": 7.5,
    "known_exploits": False,
    "fixed_version": "9.0.84",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_agent_response(**overrides):
    """Build a valid agent JSON response."""
    data = {
        "summary": "Found CVE-2026-1234 with CVSS 9.1",
        "result_card_markdown": "## CVE-2026-1234\n\nCritical RCE",
        "structured_output": {
            "normalized_title": "CVE-2026-1234 RCE",
            "cve_ids": ["CVE-2026-1234"],
            "cvss_score": 9.1,
            "known_exploits": True,
        },
        "confidence": 0.92,
        "evidence_sources": ["NVD", "ExploitDB"],
        "suggested_next_action": "find_owner",
    }
    data.update(overrides)
    return f"Analysis complete.\n\n```json\n{json.dumps(data)}\n```"


def _make_mock_agent_run(workspace_id="ws-1", agent_type="remediation_executor", status="running"):
    return AgentRun(
        id="run-123",
        workspace_id=workspace_id,
        agent_type=agent_type,
        status=status,
    )


def _make_stream_events(response_text):
    """Create an async generator that mimics OpenCode's stream_events."""
    async def stream_events(session_id):
        yield {"type": "text", "content": response_text}
        yield {"type": "done"}
    return stream_events


def _make_mock_client(response_text):
    """Create a mock OpenCodeClient that returns a canned response."""
    client = AsyncMock()
    client.create_session.return_value = MagicMock(id="session-1")
    client.send_message.return_value = None
    client.stream_events = _make_stream_events(response_text)
    return client


# ---------------------------------------------------------------------------
# PA executor helpers (ADR-0047 PR #2). The remediation_executor now runs
# in-process through Pydantic AI, so executor tests stub ``_run_pa_executor``
# (the seam to PA) and inject the AI resolvers, exactly as the no-tools tests
# stub ``_run_pa_no_tools``. Coverage of the PA tool layer itself lives in
# ``tests/agents/test_remediation_executor.py`` + ``tests/agents/tools/``.
# ---------------------------------------------------------------------------


def _executor_with_pa(mock_context_builder, outcome_factory):
    """Build an executor whose ``_run_pa_executor`` returns the given outcome.

    ``outcome_factory`` is a zero-arg callable returning a
    ``_PaExecutorOutcome`` (or raising, to exercise the error paths).
    """
    from cliff.agents.executor import AgentExecutor

    ex = AgentExecutor(
        mock_context_builder,
        ai_env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "x"}),
        ai_model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
    )

    async def _fake_pa_executor(
        deps, timeout, *, db, message_history=None, deferred_tool_results=None
    ):
        return outcome_factory()

    ex._run_pa_executor = _fake_pa_executor
    return ex


def _pa_success_outcome(structured_output=None, *, summary="Remediation done"):
    from cliff.agents.executor import _PaExecutorOutcome

    return _PaExecutorOutcome(
        parse_result=ParseResult(
            success=True,
            raw_text="",
            structured_output=structured_output or {"status": "changes_made"},
            summary=summary,
            confidence=None,
            suggested_next_action=None,
            error=None,
        ),
        permission_request=None,
        message_history_json=None,
    )


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    return pool


@pytest.fixture
def mock_context_builder():
    builder = AsyncMock()
    builder.update_context.return_value = 1  # new context_version
    return builder


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def workspace_dir(tmp_path):
    """Create a workspace directory with finding.json on disk."""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "finding.json").write_text(json.dumps(_SAMPLE_FINDING))
    return str(tmp_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentExecutor:
    @pytest.mark.asyncio
    async def test_happy_path(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """Full successful execution: PA executor -> finalize -> persist."""
        executor = _executor_with_pa(
            mock_context_builder, _pa_success_outcome
        )

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert") as mock_sidebar,
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "completed"
        assert result.parse_result.success is True
        assert result.sidebar_updated is True
        assert result.context_version == 1
        assert result.duration_seconds > 0

        # Context builder should have been called
        mock_context_builder.update_context.assert_called_once()
        # Sidebar should have been updated
        mock_sidebar.assert_called_once()

    @pytest.mark.skip(
        reason="SSE progress events (agent_run_started/completed) removed in "
        "PR2.D; the frontend now learns run transitions from the polled "
        "agent-runs query."
    )
    @pytest.mark.asyncio
    async def test_execute_publishes_started_and_completed_events(
        self, mock_context_builder, mock_db, workspace_dir
    ):
        """B36 / IMPL-0020 — every execute() must push an
        ``agent_run_started`` event onto the workspace queue as soon as
        the row is created and an ``agent_run_completed`` event before
        the closing ``done``. The SSE endpoint forwards these so the
        side panel can refresh ``agent-runs`` the instant a pipeline
        step flips, without waiting for the 5s idle poll.

        ``_cleanup_workspace_state`` pops the queue at end-of-run, so we
        intercept ``push_permission_event`` (the single publish funnel)
        rather than draining the queue post-hoc.
        """
        executor = _executor_with_pa(
            mock_context_builder, _pa_success_outcome
        )
        captured: list[dict] = []
        original = executor.push_permission_event

        def _capture(workspace_id: str, event: dict) -> None:
            captured.append(event)
            original(workspace_id, event)

        executor.push_permission_event = _capture  # type: ignore[assignment]

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "completed"

        types = [evt.get("type") for evt in captured]
        assert "agent_run_started" in types
        assert "agent_run_completed" in types
        # Started must precede completed.
        assert types.index("agent_run_started") < types.index(
            "agent_run_completed"
        )

        started = next(e for e in captured if e["type"] == "agent_run_started")
        assert started["agent_type"] == "remediation_executor"
        assert started["status"] == "running"
        assert started["run_id"]  # non-empty

        completed = next(
            e for e in captured if e["type"] == "agent_run_completed"
        )
        assert completed["agent_type"] == "remediation_executor"
        assert completed["status"] == "completed"
        assert completed["run_id"] == started["run_id"]

    @pytest.mark.skip(
        reason="SSE progress events removed in PR2.D; failure transitions "
        "surface via the polled agent-runs query."
    )
    @pytest.mark.asyncio
    async def test_execute_publishes_completed_with_failed_status_on_parse_failure(
        self, mock_context_builder, mock_db, workspace_dir
    ):
        """Failure path still publishes ``agent_run_completed`` so the
        side panel can stop spinning. The status field reflects the run
        outcome (``failed``)."""
        response_text = "no JSON here"
        mock_pool.get_or_start.return_value = _make_mock_client(response_text)

        executor = AgentExecutor(mock_context_builder)
        captured: list[dict] = []
        original = executor.push_permission_event

        def _capture(workspace_id: str, event: dict) -> None:
            captured.append(event)
            original(workspace_id, event)

        executor.push_permission_event = _capture  # type: ignore[assignment]

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        completed = [e for e in captured if e["type"] == "agent_run_completed"]
        assert len(completed) == 1
        assert completed[0]["status"] == "failed"

    @pytest.mark.skip(
        reason="The SSE permission queue (ensure_permission_queue) was removed "
        "in PR2.D/E; there is no per-workspace event queue any more."
    )
    @pytest.mark.asyncio
    async def test_execute_preserves_preexisting_permission_queue(
        self, mock_context_builder, mock_db, workspace_dir
    ):
        """B36 / IMPL-0020 — if the SSE consumer already auto-vivified a
        queue (panel opened BEFORE Start was clicked), ``execute`` must
        publish into THAT queue, not a fresh one. Otherwise the
        ``agent_run_started`` event is delivered to a queue no one is
        awaiting and the side panel never refreshes.
        """
        response_text = _make_agent_response()
        mock_pool.get_or_start.return_value = _make_mock_client(response_text)

        executor = AgentExecutor(mock_context_builder)
        # Simulate the side panel having opened the SSE stream first.
        preexisting = executor.ensure_permission_queue("ws-1")

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        # The pre-existing queue must have received the started event
        # (the consumer's await on this queue is what we're protecting).
        drained: list[dict] = []
        while not preexisting.empty():
            drained.append(preexisting.get_nowait())
        types = [e.get("type") for e in drained]
        assert "agent_run_started" in types
        assert "done" in types  # ``_cleanup_workspace_state`` closes it

    @pytest.mark.asyncio
    async def test_parse_failure_marks_failed(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """When LLM returns text but no valid JSON, the run is FAILED.

        Previously this returned ``completed`` while skipping the sidebar
        + context writes — a silent green-row state. The architect review
        of EF-B17 flagged it (more retries = more parse-after-retry
        misses). Now the executor flips to ``failed`` and populates
        ``last_error`` from ``parse_result.error``.
        """
        response_text = "I analyzed the vulnerability but forgot to return JSON."
        mock_pool.get_or_start.return_value = _make_mock_client(response_text)

        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run") as mock_update,
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert") as mock_sidebar,
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "failed"
        assert result.parse_result.success is False
        assert result.sidebar_updated is False
        # Context builder + sidebar must NOT be touched on parse failure.
        mock_context_builder.update_context.assert_not_called()
        mock_sidebar.assert_not_called()
        # The DB row must carry the parse error in last_error so the UI
        # can surface "we couldn't read the agent's output".
        final_update = mock_update.call_args_list[-1][0][2]
        assert final_update.status == "failed"
        assert final_update.last_error

    @pytest.mark.asyncio
    async def test_busy_workspace_raises(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """Another agent running → AgentBusyError."""
        existing_run = _make_mock_agent_run(status="running")
        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.list_agent_runs",
                return_value=[existing_run],
            ),pytest.raises(AgentBusyError, match="already running")
        ):
            await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

    @pytest.mark.skip(
        reason="OpenCode tool-agent machinery (pool start) removed in PR2.E; "
        "remediation_executor runs in-process via Pydantic AI and no longer "
        "uses the process pool."
    )
    @pytest.mark.asyncio
    async def test_process_start_failure(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """OpenCode process fails to start → status=failed."""
        mock_pool.get_or_start.side_effect = RuntimeError("No free ports")

        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run") as mock_update,
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "failed"
        assert "No free ports" in (result.error or "")
        # Agent run should be marked failed in DB
        mock_update.assert_called_once()
        update_data = mock_update.call_args[0][2]
        assert update_data.status == "failed"

    @pytest.mark.asyncio
    async def test_timeout(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """Agent exceeds timeout → status=failed with timeout error.

        Exercises the Pydantic AI no-tools path because that's where the
        caller-supplied ``timeout`` is the wall-clock ceiling on the
        ``asyncio.wait_for`` around ``agent.run()``. The OpenCode
        tool-agent branch has a 600s floor (max(timeout, 600)) so a
        sub-second ``timeout`` parameter is meaningless there — the
        timeout-label regression that motivates the assertion below
        sits on the PA branch in PR #1.
        """
        executor = AgentExecutor(mock_context_builder)

        async def _timeout_pa(agent_type, deps, timeout):
            # Stand-in for the PA path's own ``asyncio.wait_for`` →
            # ``AgentTimeoutError`` translation. The executor's outer
            # ``except AgentTimeoutError`` handler is what renders the
            # user-facing label this test guards.
            raise AgentTimeoutError(
                f"Pydantic AI agent did not complete within {timeout:.0f}s."
            )

        executor._run_pa_no_tools = _timeout_pa

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(agent_type="finding_enricher"),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        ):
            result = await executor.execute(
                "ws-1", "finding_enricher", mock_db,
                workspace_dir=workspace_dir, timeout=0.1,
            )

        assert result.status == "failed"
        assert "timed out" in (result.error or "").lower()
        # Regression for the misleading-label bug: the error must report
        # the effective wall-clock ceiling (which equals ``timeout`` for
        # non-tool agents like the enricher). Earlier code printed
        # ``f"... after {timeout:.0f}s"`` literally, which for tool agents
        # said "after 150s" while the run actually went 600s — sending
        # users hunting for a phantom 150s ceiling.
        assert "0s" in (result.error or "")

    @pytest.mark.asyncio
    async def test_timeout_label_reports_effective_timeout_for_tool_agent(
        self, mock_context_builder, mock_db, workspace_dir,
    ):
        """For a tool agent (remediation_executor), the wall-clock ceiling
        is bumped from the caller-supplied ``timeout`` to ``max(timeout, 600)``
        — and the timeout error label must reflect that.

        Real failure surfaced in QA: 3 executor runs timed out at the
        actual 600s ceiling, but the label said "timed out after 150s"
        (the default ``timeout`` arg). Users debugged a phantom 150s
        misconfiguration when the real story was "tool agent burned its
        full 10-minute budget". The fix swapped ``timeout`` for
        ``effective_timeout`` in the label.

        This test short-circuits the actual run by stubbing
        ``_run_pa_executor`` to raise ``AgentTimeoutError`` synchronously,
        so the assertion runs in milliseconds rather than waiting the
        real 600s ceiling.
        """
        from cliff.agents.errors import AgentTimeoutError

        def _raise_timeout():
            raise AgentTimeoutError("simulated timeout")

        executor = _executor_with_pa(
            mock_context_builder, _raise_timeout
        )

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        ):
            result = await executor.execute(
                "ws-1",
                "remediation_executor",
                mock_db,
                workspace_dir=workspace_dir,
                # Caller-supplied 150s is the legacy default — the
                # executor bumps it to 600s internally for tool agents.
                timeout=150.0,
            )

        assert result.status == "failed"
        assert "timed out" in (result.error or "").lower()
        # The bug: label said "after 150s". The fix: label must report
        # the effective 600s ceiling.
        assert "600s" in (result.error or ""), (
            f"expected '600s' in error label, got: {result.error!r} "
            f"(regression: label is reporting the input timeout instead "
            f"of effective_timeout)"
        )
        assert "150s" not in (result.error or ""), (
            f"label leaked the caller-supplied 150s instead of the "
            f"effective 600s ceiling: {result.error!r}"
        )

    @pytest.mark.skip(
        reason="OpenCode error-event stream machinery removed in PR2.E; the PA "
        "executor path translates ModelHTTPError directly (covered by "
        "tests/integration/test_rate_limit_backoff.py + test_remediation_executor)."
    )
    @pytest.mark.asyncio
    async def test_opencode_error_event(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """OpenCode returns a non-rate-limit error event → status=failed."""
        # EF-B17 — message intentionally avoids the rate-limit substrings
        # (``rate limit`` / ``429`` / ``too many requests``); those now
        # route through the retry loop and end as ``rate_limited`` rather
        # than ``failed``. Rate-limit semantics are covered separately by
        # ``backend/tests/integration/test_rate_limit_backoff.py``.
        client = AsyncMock()
        client.create_session.return_value = MagicMock(id="session-1")
        client.send_message.return_value = None

        async def error_stream(session_id):
            yield {"type": "error", "message": "Provider returned 500 internal error"}

        client.stream_events = error_stream
        mock_pool.get_or_start.return_value = client

        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "failed"
        assert "500" in (result.error or "")

    @pytest.mark.skip(
        reason="OpenCode token-streaming (on_progress) removed in PR2.E; the "
        "no-SSE PA executor does not stream progress (see ADR-0047 + the "
        "e2e test_enricher_progress_callback lockdown)."
    )
    @pytest.mark.asyncio
    async def test_progress_callback_called(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """on_progress callback receives text chunks."""
        response_text = _make_agent_response()
        mock_pool.get_or_start.return_value = _make_mock_client(response_text)

        progress_calls = []

        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            await executor.execute(
                "ws-1", "remediation_executor", mock_db,
                workspace_dir=workspace_dir,
                on_progress=progress_calls.append,
            )

        assert len(progress_calls) > 0

    @pytest.mark.asyncio
    async def test_completed_run_not_blocking(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """A completed agent run should NOT block new executions."""
        completed_run = _make_mock_agent_run(status="completed")
        executor = _executor_with_pa(
            mock_context_builder, _pa_success_outcome
        )

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch(
                "cliff.agents.executor.list_agent_runs",
                return_value=[completed_run],
            ),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_context_builder_failure(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """If context_builder.update_context fails, result persists in DB."""
        mock_context_builder.update_context.side_effect = OSError("Disk full")
        executor = _executor_with_pa(
            mock_context_builder, _pa_success_outcome
        )

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "failed"
        assert "Disk full" in (result.error or "")

    @pytest.mark.asyncio
    async def test_owner_resolver_agent_type(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """Verify executor works with different agent types (PA path).

        ADR-0047 — owner_resolver runs in-process through Pydantic AI.
        ``_run_pa_no_tools`` is stubbed so the test stays focused on the
        executor's orchestration (run row creation, sidebar update,
        context advance), not the PA library itself — coverage of the
        PA runtime layer lives in ``tests/agents/test_runtime_*.py``.
        """
        executor = AgentExecutor(mock_context_builder)
        fake_output = {
            "recommended_owner": "Platform Team",
            "candidates": [],
            "reasoning": "CODEOWNERS",
        }

        async def _fake_pa(agent_type, deps, timeout):
            # PRD-0006 Phase 2 — ``user_note`` is only honoured for
            # remediation_planner. The PA call site gates it so re-runs
            # with a refinement note don't bleed into owner / enricher /
            # exposure / evidence / validation calls on the same
            # workspace. Lock that in here.
            assert deps.user_note is None, (
                f"owner_resolver received user_note={deps.user_note!r}; "
                "user_note must be planner-only on the PA path."
            )
            return ParseResult(
                success=True,
                raw_text="",
                structured_output=fake_output,
                summary="Owner identified",
                confidence=None,
                suggested_next_action=None,
                error=None,
            )

        executor._run_pa_no_tools = _fake_pa

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(agent_type="owner_resolver"),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "owner_resolver", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "completed"
        assert result.parse_result.summary == "Owner identified"

    @pytest.mark.asyncio
    async def test_planner_receives_user_note_via_pa_path(
        self, mock_context_builder, mock_db, workspace_dir,
    ):
        """PRD-0006 Phase 2 — the planner's PA call DOES receive the user
        refinement note. Pair with ``test_owner_resolver_agent_type``,
        which asserts the gate strips it from every other agent type."""
        executor = AgentExecutor(mock_context_builder)
        captured: dict[str, str | None] = {}

        async def _fake_pa(agent_type, deps, timeout):
            captured["user_note"] = deps.user_note
            return ParseResult(
                success=True,
                raw_text="",
                structured_output={
                    "plan_steps": ["Upgrade lodash to 4.17.21"],
                    "definition_of_done": [],
                },
                summary="Plan ready",
                confidence=None,
                suggested_next_action=None,
                error=None,
            )

        executor._run_pa_no_tools = _fake_pa

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(agent_type="remediation_planner"),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_planner", mock_db,
                workspace_dir=workspace_dir,
                user_note="prefer a code-fix over a bump",
            )

        assert result.status == "completed"
        assert captured["user_note"] == "prefer a code-fix over a bump"

    @pytest.mark.skip(
        reason="OpenCode parse-retry (corrective re-prompt on the same "
        "session) removed in PR2.E; the PA executor's output_type enforces "
        "the schema and PA retries validation internally."
    )
    @pytest.mark.asyncio
    async def test_retry_on_parse_failure(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """When first attempt returns no JSON, retry with corrective prompt."""
        bad_response = "Let me read the context files to analyze this finding..."
        good_response = _make_agent_response()

        # Client that returns bad response first, then good on retry
        call_count = 0
        client = AsyncMock()
        client.create_session.return_value = MagicMock(id="session-1")
        client.send_message.return_value = None

        async def multi_stream(session_id):
            nonlocal call_count
            call_count += 1
            text = bad_response if call_count == 1 else good_response
            yield {"type": "text", "content": text}
            yield {"type": "done"}

        client.stream_events = multi_stream
        mock_pool.get_or_start.return_value = client

        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "completed"
        assert result.parse_result.success is True
        assert result.sidebar_updated is True
        # Two send_message calls: initial prompt + retry
        assert client.send_message.call_count == 2

    @pytest.mark.skip(
        reason="OpenCode double-parse-fail path removed in PR2.E; the PA "
        "executor enforces RemediationExecutorOutput via output_type."
    )
    @pytest.mark.asyncio
    async def test_retry_still_fails(self, mock_pool, mock_context_builder,
        mock_db, workspace_dir):
        """Both attempts produce no JSON → run marked FAILED (not completed).

        Architect review of EF-B17: marking the row ``completed`` while
        the sidebar/context blocks were skipped masks the failure with
        a green row in the UI.
        """
        bad_response = "I'll try to read the files instead of returning JSON."
        mock_pool.get_or_start.return_value = _make_mock_client(bad_response)

        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert") as mock_sidebar,
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db, workspace_dir=workspace_dir
            )

        assert result.status == "failed"
        assert result.parse_result.success is False
        assert result.sidebar_updated is False
        mock_sidebar.assert_not_called()


class TestPaResolverWiring:
    """The executor MUST resolve env+model on every PA call (no caching).

    The two resolver closures wired in ``main.py`` are the single seam
    between Cliff's canonical AI state (``ai_integration`` + vault +
    ``app_setting(model)``) and the Pydantic AI ``Model`` instance the
    no-tools agents run against. If the executor ever cached the
    resolved values at ``__init__`` instead of awaiting them per run,
    a UI provider-switch would not take effect until daemon restart —
    a silent staleness regression. This lockdown prevents that.
    """

    @pytest.mark.asyncio
    async def test_run_pa_no_tools_resolves_env_and_model_per_call(
        self, mock_context_builder, monkeypatch,
    ):
        env_seq = [
            {"OPENAI_API_KEY": "sk-first"},
            {"OPENAI_API_KEY": "sk-second"},
        ]
        model_seq = ["openai/gpt-4o-mini", "openai/gpt-5-mini"]
        env_resolver = AsyncMock(side_effect=env_seq)
        model_resolver = AsyncMock(side_effect=model_seq)

        captured_build_args: list[tuple[dict, str]] = []

        def _capture_build_model(env, model_full_id):
            captured_build_args.append((env, model_full_id))
            return MagicMock(model_name=model_full_id.split("/", 1)[1])

        async def _stub_run(agent_type, deps, model):
            return {"normalized_title": "ok", "cve_ids": []}

        monkeypatch.setattr(
            "cliff.agents.executor.build_model", _capture_build_model,
        )
        monkeypatch.setattr(
            "cliff.agents.executor.run_no_tools_agent", _stub_run,
        )

        executor = AgentExecutor(
            mock_context_builder,
            ai_env_resolver=env_resolver,
            ai_model_resolver=model_resolver,
        )
        deps = WorkspaceDeps(
            workspace_id="ws-1", workspace_dir="/tmp/ws",
            finding={"id": "f-1"},
        )

        await executor._run_pa_no_tools(
            "finding_enricher", deps, timeout=30.0,
        )
        await executor._run_pa_no_tools(
            "finding_enricher", deps, timeout=30.0,
        )

        # Both resolvers awaited per call — no init-time caching.
        assert env_resolver.await_count == 2
        assert model_resolver.await_count == 2
        # build_model received call N's resolved values — not call 1's
        # values on the second invocation (the staleness regression).
        assert captured_build_args == [
            ({"OPENAI_API_KEY": "sk-first"}, "openai/gpt-4o-mini"),
            ({"OPENAI_API_KEY": "sk-second"}, "openai/gpt-5-mini"),
        ]


class TestLoadWorkspaceData:
    def test_reads_finding_from_disk(self, workspace_dir):
        """_load_workspace_data reads finding.json from the workspace."""
        finding, prior = _load_workspace_data(workspace_dir, "finding_enricher")
        assert finding["title"] == "Apache Tomcat vulnerable version on web-prod-17"
        assert prior == {}  # enricher is first, no prior context

    def test_reads_prior_context(self, workspace_dir):
        """Prior context files are loaded for later agents."""
        # Write enrichment data
        ctx = Path(workspace_dir) / "context"
        (ctx / "enrichment.json").write_text(json.dumps(_SAMPLE_ENRICHMENT))

        finding, prior = _load_workspace_data(workspace_dir, "owner_resolver")
        assert "enrichment" in prior
        assert prior["enrichment"]["cve_ids"] == ["CVE-2023-46589"]

    def test_missing_finding_raises(self, tmp_path):
        """Missing finding.json raises AgentProcessError."""
        (tmp_path / "context").mkdir()
        from cliff.agents.errors import AgentProcessError
        with pytest.raises(AgentProcessError, match="finding.json missing"):
            _load_workspace_data(str(tmp_path), "finding_enricher")

    def test_enricher_gets_no_prior_even_if_files_exist(self, workspace_dir):
        """Enricher is first in pipeline — never gets prior context."""
        ctx = Path(workspace_dir) / "context"
        (ctx / "enrichment.json").write_text(json.dumps(_SAMPLE_ENRICHMENT))

        _, prior = _load_workspace_data(workspace_dir, "finding_enricher")
        assert prior == {}  # enricher has no prior sections


# ---------------------------------------------------------------------------
# Permission handling tests
# ---------------------------------------------------------------------------

class TestPermissionTiers:
    def test_read_tools_auto_approve(self):
        """Read and webfetch are auto-approved."""
        assert TOOL_TIERS["read"] == "auto"
        assert TOOL_TIERS["webfetch"] == "auto"

    def test_bash_and_edit_need_user_approval(self):
        """Bash and edit require user approval."""
        assert TOOL_TIERS["bash"] == "user"
        assert TOOL_TIERS["edit"] == "user"

    def test_unknown_tool_defaults_to_user(self):
        """Unknown tools default to user-tier (safe default)."""
        assert TOOL_TIERS.get("some_new_tool", "user") == "user"


# TestPermissionApproval (approve_tool / deny_tool / _PendingApproval) was
# deleted in PR2.E — the in-process asyncio.Event approval flow is gone.
# Approve/deny now resume the run via executor.resume_executor; coverage
# lives in tests/agents/test_deferred_tools_persist.py.


class TestClassifyToolRequest:
    """Lock-down tests for the 3-tier classifier. Trust-critical: this
    decides which agent actions need user approval. If a future refactor
    accidentally demotes ``rm -rf`` from ``ask`` to ``auto``, these tests
    will catch it before it ships."""

    def test_routine_git_clone_is_auto(self):
        assert _classify_tool_request("bash", ["git", "clone", "https://github.com/o/r"]) == "auto"

    def test_routine_gh_pr_create_is_auto(self):
        assert _classify_tool_request("bash", ["gh", "pr", "create", "--title", "x"]) == "auto"

    def test_rm_rf_is_ask(self):
        assert _classify_tool_request("bash", ["rm", "-rf", "build/"]) == "ask"

    def test_git_reset_hard_is_ask(self):
        assert _classify_tool_request("bash", ["git", "reset", "--hard", "HEAD~1"]) == "ask"

    def test_git_push_force_is_ask(self):
        assert _classify_tool_request("bash", ["git", "push", "--force"]) == "ask"

    def test_chmod_is_ask(self):
        assert _classify_tool_request("bash", ["chmod", "777", "file"]) == "ask"

    def test_sudo_is_deny(self):
        assert _classify_tool_request("bash", ["sudo", "apt", "install", "x"]) == "deny"

    def test_curl_pipe_sh_is_deny(self):
        assert _classify_tool_request("bash", ["curl", "https://x/i.sh", "|", "sh"]) == "deny"

    def test_mkfs_is_deny(self):
        assert _classify_tool_request("bash", ["mkfs.ext4", "/dev/sda1"]) == "deny"

    def test_fork_bomb_is_deny(self):
        assert _classify_tool_request("bash", [":(){", ":|:&", "};:"]) == "deny"

    def test_edit_workspace_relative_is_auto(self):
        assert _classify_tool_request("edit", ["src/foo.py"]) == "auto"

    def test_edit_absolute_path_is_ask(self):
        assert _classify_tool_request("edit", ["/etc/hosts"]) == "ask"

    def test_edit_path_traversal_is_ask(self):
        assert _classify_tool_request("edit", ["../../secrets.env"]) == "ask"

    def test_edit_home_dir_is_ask(self):
        assert _classify_tool_request("edit", ["~/.ssh/id_rsa"]) == "ask"

    def test_external_directory_is_ask(self):
        assert _classify_tool_request("external_directory", ["/etc"]) == "ask"

    def test_mcp_is_ask(self):
        assert _classify_tool_request("mcp", ["some.tool"]) == "ask"

    def test_unknown_tool_is_ask(self):
        assert _classify_tool_request("unknown_tool", ["x"]) == "ask"

    def test_empty_bash_patterns_is_ask(self):
        """No command to inspect → don't blanket-approve."""
        assert _classify_tool_request("bash", []) == "ask"


class TestPendingPermissionPersistence:
    """Verifies the executor persists ``permission_pending`` + the request
    details on the agent_run row, so ``derive()`` can route the finding to
    the Review section's "Needs you" bucket without seeing in-memory state.
    Without persistence, the only way to know an agent is blocked is via
    the SSE event — and a page reload would lose that knowledge."""

    @pytest.mark.skip(
        reason="OpenCode in-process asyncio.Event approve flow removed in "
        "PR2.E; the durable DeferredToolRequests marker + resume path is "
        "covered by tests/agents/test_deferred_tools_persist.py."
    )
    @pytest.mark.asyncio
    async def test_pending_persists_then_clears_on_approve(
        self, mock_context_builder, mock_db, workspace_dir
    ):
        from cliff.models import AgentRunUpdate

        client = AsyncMock()
        client.create_session.return_value = MagicMock(id="ses-1")
        client.send_message.return_value = None
        client.grant_permission.return_value = None

        async def stream_with_ask_bash(session_id):
            yield {
                "type": "permission_request",
                "id": "per_rm",
                "tool": "bash",
                "patterns": ["rm", "-rf", "build/"],
            }
            yield {"type": "text", "content": _make_agent_response()}
            yield {"type": "done"}

        client.stream_events = stream_with_ask_bash
        mock_pool.get_or_start.return_value = client

        executor = AgentExecutor(mock_context_builder)

        update_spy = AsyncMock(return_value=None)

        async def auto_approve_after_callback(event_dict):
            await asyncio.sleep(0.01)
            executor.approve_tool(event_dict["run_id"])

        def on_perm(event_dict):
            asyncio.create_task(auto_approve_after_callback(event_dict))

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run", update_spy),
            patch(
                "cliff.agents.executor.list_agent_runs",
                return_value=[],
            ),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db,
                workspace_dir=workspace_dir,
                on_permission=on_perm,
            )

        assert result.status == "completed"

        # Collect every AgentRunUpdate passed to update_agent_run.
        updates: list[AgentRunUpdate] = [
            call.args[2] for call in update_spy.call_args_list
            if len(call.args) >= 3 and isinstance(call.args[2], AgentRunUpdate)
        ]
        # The marker should have been set, then cleared, before the final
        # status update.
        set_calls = [
            u for u in updates
            if u.permission_pending is True
        ]
        clear_calls = [
            u for u in updates
            if u.permission_pending is False
        ]
        assert len(set_calls) == 1, (
            f"expected exactly one set call, got updates: {updates}"
        )
        assert set_calls[0].permission_request == {
            "id": "per_rm",
            "tool": "bash",
            "patterns": ["rm", "-rf", "build/"],
        }
        assert len(clear_calls) >= 1
        assert clear_calls[0].permission_request is None

        # And ordering: set must precede clear.
        set_idx = updates.index(set_calls[0])
        clear_idx = updates.index(clear_calls[0])
        assert set_idx < clear_idx

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason=(
            "ADR-0047 / PR #1 — finding_enricher's old TOOL_TIERS route "
            "is gone. Permission flow on the surviving OpenCode tool "
            "agent uses _classify_tool_request, not TOOL_TIERS. PR #2 "
            "rebuilds permission handling on DeferredToolRequests; this "
            "test gets reborn there as a deferred-tools assertion."
        ),
    )
    async def test_auto_approve_in_stream(
        self, mock_pool, mock_context_builder,
        mock_db, workspace_dir
    ):
        """Auto-tier tools (read) are granted without user interaction."""
        # Client that emits a permission event then completes
        client = AsyncMock()
        client.create_session.return_value = MagicMock(id="ses-1")
        client.send_message.return_value = None
        client.grant_permission.return_value = None

        async def stream_with_permission(session_id):
            yield {
                "type": "permission_request",
                "id": "per_auto",
                "tool": "read",
                "patterns": ["context/finding.json"],
            }
            yield {
                "type": "text",
                "content": _make_agent_response(),
            }
            yield {"type": "done"}

        client.stream_events = stream_with_permission
        mock_pool.get_or_start.return_value = client

        executor = AgentExecutor(mock_context_builder)

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch(
                "cliff.agents.executor.list_agent_runs",
                return_value=[],
            ),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db,
                workspace_dir=workspace_dir,
            )

        assert result.status == "completed"
        # Auto-approved: grant_permission should have been called
        client.grant_permission.assert_called_once_with("per_auto", session_id="ses-1")

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason=(
            "ADR-0047 / PR #1 — TOOL_TIERS-routed user-approval flow is "
            "gone with the no-tools agents. The surviving OpenCode tool "
            "agent classifies bash per-command, so 'ls -la /tmp' auto-"
            "approves and no callback fires. PR #2 rebuilds this on "
            "DeferredToolRequests."
        ),
    )
    async def test_user_tier_surfaces_callback(
        self, mock_pool, mock_context_builder,
        mock_db, workspace_dir
    ):
        """User-tier tools fire on_permission callback."""
        client = AsyncMock()
        client.create_session.return_value = MagicMock(id="ses-1")
        client.send_message.return_value = None
        client.grant_permission.return_value = None

        permission_calls = []

        async def stream_with_bash_permission(session_id):
            yield {
                "type": "permission_request",
                "id": "per_bash",
                "tool": "bash",
                "patterns": ["ls -la /tmp"],
            }
            # After yielding permission, we need to wait
            # for the approval before the stream continues.
            # In real usage, OpenCode blocks here. In test,
            # we simulate by yielding done after a delay.
            yield {
                "type": "text",
                "content": _make_agent_response(),
            }
            yield {"type": "done"}

        client.stream_events = stream_with_bash_permission
        mock_pool.get_or_start.return_value = client

        executor = AgentExecutor(mock_context_builder)

        # Auto-approve from a background task after the
        # callback fires
        async def auto_approve_after_callback(event_dict):
            permission_calls.append(event_dict)
            # Approve in a microtask so the executor can resume
            await asyncio.sleep(0.01)
            executor.approve_tool(event_dict["run_id"])

        def on_perm(event_dict):
            asyncio.create_task(
                auto_approve_after_callback(event_dict)
            )

        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch(
                "cliff.agents.executor.list_agent_runs",
                return_value=[],
            ),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
        ):
            result = await executor.execute(
                "ws-1", "remediation_executor", mock_db,
                workspace_dir=workspace_dir,
                on_permission=on_perm,
            )

        assert result.status == "completed"
        assert len(permission_calls) == 1
        assert permission_calls[0]["tool"] == "bash"
        # Should have called grant after approval
        client.grant_permission.assert_called_once_with("per_bash", session_id="ses-1")


# ---------------------------------------------------------------------------
# B16: PR-URL verification on remediation_executor
# ---------------------------------------------------------------------------


def _pr_created_output(pr_url: str | None, status: str = "pr_created") -> dict:
    """The structured_output a PA remediation_executor run produces when it
    claims to have opened a PR (drives the _finalize_run PR-verify path)."""
    return {
        "status": status,
        "pr_url": pr_url,
        "branch_name": "cliff/fix/cve-test",
        "changes_summary": "bumped widget to 1.2.3",
        "test_results": "pass",
        "error_details": None,
    }


class TestRemediationExecutorPRVerification:
    """B16 guardrail: hallucinated PR URLs must fail the run."""

    @pytest.mark.asyncio
    async def test_valid_pr_url_passes_verification(
        self, mock_context_builder, mock_db, workspace_dir
    ):
        real_url = "https://github.com/acme/widget/pull/42"

        from cliff.services.pr_verifier import PRVerification

        async def fake_verify(url, **_):
            assert url == real_url
            return PRVerification(
                ok=True, reason="verified", pr_state="open", html_url=url
            )

        executor = _executor_with_pa(
            mock_context_builder,
            lambda: _pa_success_outcome(_pr_created_output(real_url)),
        )
        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(
                    agent_type="remediation_executor"
                ),
            ),
            patch("cliff.agents.executor.update_agent_run") as mock_update,
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert") as mock_sidebar,
            patch(
                "cliff.agents.executor._advance_finding_status",
                return_value="remediated",
            ) as mock_advance,
            patch(
                "cliff.agents.executor.verify_pr_url",
                side_effect=fake_verify,
            ),
        ):
            result = await executor.execute(
                "ws-1",
                "remediation_executor",
                mock_db,
                workspace_dir=workspace_dir,
                env_vars={"GH_TOKEN": "ghp_test"},
            )

        assert result.status == "completed"
        assert result.parse_result.success is True
        assert result.sidebar_updated is True
        mock_sidebar.assert_called_once()
        mock_advance.assert_called_once()
        final_call = mock_update.call_args_list[-1]
        assert final_call.args[2].status == "completed"

    @pytest.mark.asyncio
    async def test_hallucinated_pr_url_fails_run_and_blocks_advance(
        self, mock_context_builder, mock_db, workspace_dir
    ):
        """B16 regression: verifier says 404 → no sidebar update, no advance, no completion."""
        fake_url = "https://github.com/acme/widget/pull/9999"

        from cliff.services.pr_verifier import PRVerification

        async def fake_verify(url, **_):
            return PRVerification(
                ok=False,
                reason="not_found: GitHub returned 404 for this pull request",
            )

        executor = _executor_with_pa(
            mock_context_builder,
            lambda: _pa_success_outcome(_pr_created_output(fake_url)),
        )
        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(
                    agent_type="remediation_executor"
                ),
            ),
            patch("cliff.agents.executor.update_agent_run") as mock_update,
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert") as mock_sidebar,
            patch(
                "cliff.agents.executor._advance_finding_status",
                return_value=None,
            ) as mock_advance,
            patch(
                "cliff.agents.executor.verify_pr_url",
                side_effect=fake_verify,
            ),
        ):
            result = await executor.execute(
                "ws-1",
                "remediation_executor",
                mock_db,
                workspace_dir=workspace_dir,
                env_vars={"GH_TOKEN": "ghp_test"},
            )

        assert result.status == "failed"
        assert result.error is not None
        assert "PR verification failed" in result.error
        assert "not_found" in result.error
        mock_sidebar.assert_not_called()
        mock_advance.assert_not_called()
        final_call = mock_update.call_args_list[-1]
        update = final_call.args[2]
        assert update.status == "failed"
        assert "PR verification failed" in (update.summary_markdown or "")

    @pytest.mark.asyncio
    async def test_compare_url_rejected_without_network(
        self, mock_context_builder, mock_db, workspace_dir
    ):
        """A ``/pull/new/<branch>`` URL is rejected by the URL parser alone."""
        fake_url = "https://github.com/acme/widget/pull/new/cliff-fix"

        executor = _executor_with_pa(
            mock_context_builder,
            lambda: _pa_success_outcome(_pr_created_output(fake_url)),
        )
        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(
                    agent_type="remediation_executor"
                ),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert") as mock_sidebar,
            patch(
                "cliff.agents.executor._advance_finding_status",
                return_value=None,
            ),
            patch(
                "httpx.AsyncClient.get",
                side_effect=AssertionError(
                    "verifier should not touch the network for invalid URLs"
                ),
            ),
        ):
            result = await executor.execute(
                "ws-1",
                "remediation_executor",
                mock_db,
                workspace_dir=workspace_dir,
                env_vars={"GH_TOKEN": "ghp_test"},
            )

        assert result.status == "failed"
        assert "not_a_pull_url" in (result.error or "")
        mock_sidebar.assert_not_called()


# ---------------------------------------------------------------------------
# _humanize_process_error — actionable text for provider errors
# ---------------------------------------------------------------------------


class TestHumanizeProcessError:
    def test_missing_authentication_header_maps_to_credential_message(self):
        """The BYOK auth-propagation failure mode reads as a credential error.

        Anthropic/OpenAI return "Missing Authentication header" verbatim when
        the outbound request carries no credential. It must surface the
        actionable "re-connect the provider" text, not the generic fallback.
        """
        from cliff.agents.executor import _humanize_process_error

        msg = _humanize_process_error(
            "OpenCode error: Missing Authentication header"
        )
        assert "rejected the credentials" in msg
        assert "Settings → AI provider" in msg

    def test_unknown_error_falls_back_to_raw(self):
        from cliff.agents.executor import _humanize_process_error

        msg = _humanize_process_error("OpenCode error: disk full")
        assert "disk full" in msg
