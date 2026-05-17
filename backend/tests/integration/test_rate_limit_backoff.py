"""EF-B17 regression — exponential backoff on upstream LLM rate-limit.

Wave-1 evidence (`docs/qa/evidence/Q01/B14-B20/B17-failed-runs-sample.txt`)
shows agent runs failing at exactly 76 s under workspace-pool concurrency.
The root cause: OpenCode wraps an upstream provider 429 into a
``session.error`` SSE event, which the executor used to surface as a fatal
``AgentProcessError`` with no retry. These tests prove that:

1. A retry-able rate-limit (1-2 throttles followed by success) now finishes
   the run with ``status == 'completed'`` instead of failing on attempt 1.
2. A persistent rate-limit terminates the run with ``status='rate_limited'``
   AND ``last_error`` populated AND ``evidence_json['error']`` populated —
   no silent 76 s timeouts.

The tests mock the workspace pool's OpenCode client so they're pure unit
tests of the retry loop in ``executor.execute``; the in-memory aiosqlite
fixture from ``tests/integration/conftest.py`` is reused.
"""

from __future__ import annotations

import json
import time
from pathlib import Path  # noqa: TC003 — runtime use in fixture annotation
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opensec.agents import executor as executor_module
from opensec.agents.executor import AgentExecutor
from opensec.models import AgentRun

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_SAMPLE_FINDING = {
    "id": "390f95cd-fcbb-416d-b3af-51e86dfc3d29",
    "title": "Apache Tomcat vulnerable version on web-prod-17",
    "source_type": "tenable",
    "source_id": "CVE-2023-46589",
    "description": "Apache Tomcat 9.0.82 is vulnerable to HTTP request smuggling.",
    "raw_severity": "critical",
    "normalized_priority": "P1",
    "asset_id": "web-prod-17",
    "asset_label": "Web Server 17 (Production)",
    "status": "new",
    "likely_owner": "Platform Engineering",
}


def _good_response_text() -> str:
    payload = {
        "summary": "Enriched CVE-2023-46589",
        "result_card_markdown": "## CVE-2023-46589",
        "structured_output": {
            "normalized_title": "Apache Tomcat HTTP request smuggling",
            "cve_ids": ["CVE-2023-46589"],
            "cvss_score": 7.5,
            "known_exploits": False,
        },
        "confidence": 0.91,
        "evidence_sources": ["NVD"],
        "suggested_next_action": "find_owner",
    }
    return f"Analysis complete.\n\n```json\n{json.dumps(payload)}\n```"


def _make_mock_agent_run() -> AgentRun:
    return AgentRun(
        id="run-rl-1",
        workspace_id="ws-rl",
        agent_type="finding_enricher",
        status="running",
    )


@pytest.fixture
def workspace_dir(tmp_path: Path) -> str:
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "finding.json").write_text(json.dumps(_SAMPLE_FINDING))
    return str(tmp_path)


def _make_flaky_client(error_attempts: int, *, always_error: bool = False) -> AsyncMock:
    """Mock OpenCode client whose ``stream_events`` errors on the first N
    attempts (one full call each), then returns a normal response stream.

    If ``always_error`` is True, every call errors (used for the exhaustion
    case).
    """
    client = AsyncMock()
    client.create_session.return_value = MagicMock(id="session-rl")
    client.send_message.return_value = None

    attempt_counter = {"n": 0}

    async def stream_events(session_id: str):  # noqa: ARG001 — session_id unused
        attempt_counter["n"] += 1
        if always_error or attempt_counter["n"] <= error_attempts:
            yield {"type": "error", "message": "Provider returned 429 too many requests"}
            return
        yield {"type": "text", "content": _good_response_text()}
        yield {"type": "done"}

    client.stream_events = stream_events
    client._attempt_counter = attempt_counter  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_retry_then_success(monkeypatch, workspace_dir):
    """1-2 rate-limit responses, then success — run completes after retries."""

    # Zero out backoff delays so the test doesn't actually sleep.
    monkeypatch.setattr(executor_module, "RATE_LIMIT_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "RATE_LIMIT_MAX_DELAY_SECONDS", 0.0)

    pool = AsyncMock()
    builder = AsyncMock()
    builder.update_context.return_value = 1
    db = AsyncMock()

    # First 2 attempts emit the rate-limit error event, 3rd succeeds.
    client = _make_flaky_client(error_attempts=2)
    pool.get_or_start.return_value = client

    executor = AgentExecutor(pool, builder)

    start = time.monotonic()
    with (
        patch(
            "opensec.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("opensec.agents.executor.update_agent_run") as mock_update,
        patch("opensec.agents.executor.list_agent_runs", return_value=[]),
        patch("opensec.agents.executor.map_and_upsert"),
        patch("opensec.agents.executor._advance_finding_status", return_value=None),
    ):
        result = await executor.execute(
            "ws-rl", "finding_enricher", db, workspace_dir=workspace_dir,
        )
    elapsed = time.monotonic() - start

    assert result.status == "completed", (
        f"expected eventual success after retries; got status={result.status!r} "
        f"error={result.error!r}"
    )
    assert result.parse_result.success is True
    # 3 attempts: 2 rate-limit + 1 success
    assert client._attempt_counter["n"] == 3  # noqa: SLF001 — test asserts internal counter
    # Well under the 18 s ceiling (acceptance #1) and far from the 76 s
    # stall window — proves the backoff path replaced the timeout collision.
    # Under 18 s per EF-B17 acceptance criterion #1 / regression #4. With
    # delays zeroed the only remaining cost is the stall-detection poller
    # in ``_collect_response`` (one 2 s tick per attempt), so 3 attempts
    # come in around 6-8 s — proves the backoff path replaced the 76 s
    # stall collision without sitting on the timeout.
    assert elapsed < 18.0, f"backoff retry took too long ({elapsed:.1f}s)"

    # Final DB update must record completion, not a rate-limit terminal.
    final_call = mock_update.call_args_list[-1]
    final_update = final_call[0][2]
    assert final_update.status == "completed"


@pytest.mark.asyncio
async def test_rate_limit_exhausted_terminates_with_status_and_last_error(
    monkeypatch, workspace_dir,
):
    """All attempts rate-limited — run terminates as rate_limited with
    last_error populated; never silently times out at 76 s.
    """

    monkeypatch.setattr(executor_module, "RATE_LIMIT_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "RATE_LIMIT_MAX_DELAY_SECONDS", 0.0)

    pool = AsyncMock()
    builder = AsyncMock()
    builder.update_context.return_value = 1
    db = AsyncMock()

    client = _make_flaky_client(error_attempts=0, always_error=True)
    pool.get_or_start.return_value = client

    executor = AgentExecutor(pool, builder)

    start = time.monotonic()
    with (
        patch(
            "opensec.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("opensec.agents.executor.update_agent_run") as mock_update,
        patch("opensec.agents.executor.list_agent_runs", return_value=[]),
        patch("opensec.agents.executor.map_and_upsert"),
        patch("opensec.agents.executor._advance_finding_status", return_value=None),
    ):
        result = await executor.execute(
            "ws-rl", "finding_enricher", db, workspace_dir=workspace_dir,
        )
    elapsed = time.monotonic() - start

    assert result.status == "rate_limited", (
        f"expected rate_limited terminal status; got {result.status!r}"
    )
    assert result.parse_result.success is False
    assert result.error and "rate limit" in result.error.lower()
    # Burned the full retry budget (acceptance #4 of EF-B17).
    assert client._attempt_counter["n"] == executor_module.RATE_LIMIT_MAX_ATTEMPTS  # noqa: SLF001
    # No 76 s stall — under EF-B17 acceptance #2. Same 2 s-per-attempt
    # stall-poller tail as the success case; still well below 18 s.
    assert elapsed < 18.0, f"exhausted retry took too long ({elapsed:.1f}s)"

    # DB update must carry status, last_error, and evidence_json.error.
    final_call = mock_update.call_args_list[-1]
    final_update = final_call[0][2]
    assert final_update.status == "rate_limited"
    assert final_update.last_error and "rate limit" in final_update.last_error.lower()
    assert final_update.evidence_json is not None
    assert "error" in final_update.evidence_json
    assert final_update.evidence_json.get("type") == "AgentRateLimitError"


@pytest.mark.asyncio
async def test_non_rate_limit_error_still_fails_immediately(monkeypatch, workspace_dir):
    """Non-429 OpenCode errors must NOT trigger the rate-limit retry loop —
    they continue to terminate immediately as ``failed`` (preserves existing
    semantics; hard rule 1).
    """

    monkeypatch.setattr(executor_module, "RATE_LIMIT_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "RATE_LIMIT_MAX_DELAY_SECONDS", 0.0)

    pool = AsyncMock()
    builder = AsyncMock()
    builder.update_context.return_value = 1
    db = AsyncMock()

    client = AsyncMock()
    client.create_session.return_value = MagicMock(id="session-rl")
    client.send_message.return_value = None
    attempts = {"n": 0}

    async def stream_events(session_id: str):  # noqa: ARG001
        attempts["n"] += 1
        yield {"type": "error", "message": "Provider returned 500 internal error"}

    client.stream_events = stream_events
    pool.get_or_start.return_value = client

    executor = AgentExecutor(pool, builder)

    with (
        patch(
            "opensec.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("opensec.agents.executor.update_agent_run") as mock_update,
        patch("opensec.agents.executor.list_agent_runs", return_value=[]),
    ):
        result = await executor.execute(
            "ws-rl", "finding_enricher", db, workspace_dir=workspace_dir,
        )

    assert result.status == "failed"
    assert attempts["n"] == 1, "non-rate-limit errors must not retry"
    final_update = mock_update.call_args_list[-1][0][2]
    assert final_update.status == "failed"
    assert final_update.last_error and "500" in final_update.last_error
