"""EF-B17 regression — exponential backoff on upstream LLM rate-limit.

Wave-1 evidence (`docs/qa/evidence/Q01/B14-B20/B17-failed-runs-sample.txt`)
showed agent runs failing under workspace-pool concurrency when the
upstream provider 429'd. The retry-with-backoff loop now lives in
``AgentExecutor._run_pa_call`` (ADR-0047 PR #2) and is shared by every
Pydantic AI agent run. These tests prove that:

1. A retry-able rate-limit (1-2 throttles followed by success) finishes
   the run with ``status == 'completed'`` instead of failing on attempt 1.
2. A persistent rate-limit terminates the run with ``status='rate_limited'``
   AND ``last_error`` populated — no silent stalls.
3. A non-429 provider error fails immediately (no wasted retries).

Post-migration, rate-limit detection is STRUCTURAL: ``_run_pa_call`` keys
off ``ModelHTTPError.status_code == 429`` rather than string-matching an
OpenCode error message. The old string-classification corpus tests
(``test_real_world_rate_limit_messages_*`` / ``test_lookalike_messages_*``)
are therefore retired — PA hands us the status code directly, so there is
no message text to classify. These tests drive a no-tools agent (the
``finding_enricher``) because ``_run_pa_call`` is the same loop for every
agent; a flaky ``run_no_tools_agent`` raises ``ModelHTTPError`` to model
the provider throttle.
"""

from __future__ import annotations

import json
import time
from pathlib import Path  # noqa: TC003 — runtime use in fixture annotation
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from cliff.agents import executor as executor_module
from cliff.agents.executor import AgentExecutor
from cliff.models import AgentRun

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures + helpers
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


def _make_executor() -> AgentExecutor:
    builder = AsyncMock()
    builder.update_context.return_value = 1
    return AgentExecutor(
        builder,
        ai_env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "x"}),
        ai_model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
    )


def _make_flaky_run(
    error_attempts: int, *, status_code: int = 429, always_error: bool = False
):
    """A flaky ``run_no_tools_agent`` replacement: raises ``ModelHTTPError``
    on the first ``error_attempts`` calls (or every call if ``always_error``),
    then returns a valid structured-output dict.

    Returns ``(run_fn, counter)`` so the test can assert the attempt count.
    """
    counter = {"n": 0}

    async def _run(agent_type, deps, model):  # noqa: ARG001
        counter["n"] += 1
        if always_error or counter["n"] <= error_attempts:
            raise ModelHTTPError(
                status_code=status_code, model_name="test-model", body="throttled"
            )
        return {"normalized_title": "Apache Tomcat smuggling", "cve_ids": []}

    return _run, counter


def _zero_backoff(monkeypatch):
    monkeypatch.setattr(executor_module, "RATE_LIMIT_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "RATE_LIMIT_MAX_DELAY_SECONDS", 0.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_retry_then_success(monkeypatch, workspace_dir):
    """1-2 rate-limit (429) responses, then success — run completes."""
    _zero_backoff(monkeypatch)
    flaky, counter = _make_flaky_run(error_attempts=2)
    executor = _make_executor()

    start = time.monotonic()
    with (
        patch(
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.map_and_upsert"),
        patch("cliff.agents.executor._advance_finding_status", return_value=None),
        patch("cliff.agents.executor.build_model", return_value=MagicMock()),
        patch("cliff.agents.executor.run_no_tools_agent", flaky),
    ):
        result = await executor.execute(
            "ws-rl", "finding_enricher", AsyncMock(), workspace_dir=workspace_dir,
        )
    elapsed = time.monotonic() - start

    assert result.status == "completed", (
        f"expected eventual success after retries; got {result.status!r} "
        f"error={result.error!r}"
    )
    assert result.parse_result.success is True
    assert counter["n"] == 3  # 2 throttles + 1 success
    assert elapsed < 18.0, f"backoff retry took too long ({elapsed:.1f}s)"

    final_update = mock_update.call_args_list[-1][0][2]
    assert final_update.status == "completed"


@pytest.mark.asyncio
async def test_rate_limit_exhausted_terminates_with_status_and_last_error(
    monkeypatch, workspace_dir,
):
    """Every attempt 429s — run terminates ``rate_limited`` with last_error."""
    _zero_backoff(monkeypatch)
    flaky, counter = _make_flaky_run(error_attempts=0, always_error=True)
    executor = _make_executor()

    with (
        patch(
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.map_and_upsert"),
        patch("cliff.agents.executor._advance_finding_status", return_value=None),
        patch("cliff.agents.executor.build_model", return_value=MagicMock()),
        patch("cliff.agents.executor.run_no_tools_agent", flaky),
    ):
        result = await executor.execute(
            "ws-rl", "finding_enricher", AsyncMock(), workspace_dir=workspace_dir,
        )

    assert result.status == "rate_limited", (
        f"expected rate_limited terminal status; got {result.status!r}"
    )
    assert result.parse_result.success is False
    assert result.error and "rate limit" in result.error.lower()
    # Burned the full retry budget (EF-B17 acceptance #4).
    assert counter["n"] == executor_module.RATE_LIMIT_MAX_ATTEMPTS

    final_update = mock_update.call_args_list[-1][0][2]
    assert final_update.status == "rate_limited"
    assert final_update.last_error
    # evidence_json is intentionally not written on failure paths (migration 021).
    assert final_update.evidence_json is None


@pytest.mark.asyncio
async def test_non_rate_limit_error_still_fails_immediately(monkeypatch, workspace_dir):
    """A non-429 provider error (500) must NOT enter the retry loop — it
    fails fast on the first attempt (preserves hard-rule-1 semantics)."""
    _zero_backoff(monkeypatch)
    flaky, counter = _make_flaky_run(
        error_attempts=0, always_error=True, status_code=500
    )
    executor = _make_executor()

    with (
        patch(
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.build_model", return_value=MagicMock()),
        patch("cliff.agents.executor.run_no_tools_agent", flaky),
    ):
        result = await executor.execute(
            "ws-rl", "finding_enricher", AsyncMock(), workspace_dir=workspace_dir,
        )

    assert result.status == "failed"
    assert counter["n"] == 1, "non-rate-limit errors must not retry"
    final_update = mock_update.call_args_list[-1][0][2]
    assert final_update.status == "failed"
    assert final_update.last_error and "500" in final_update.last_error


@pytest.mark.asyncio
async def test_sustained_throttling_recovers_run_by_run(monkeypatch, workspace_dir):
    """Q01-Wave-1 F1-minimist pattern: a sequence of runs where the provider
    intermittently 429s (the load that silently killed 6 of 22 findings).
    Each run takes 1-2 throttles before succeeding; every one recovers
    instead of leaving a phantom failure."""
    _zero_backoff(monkeypatch)
    executor = _make_executor()

    throttle_sequence = [0, 2, 2, 1, 0]
    final_statuses: list[str] = []

    for throttles in throttle_sequence:
        flaky, _counter = _make_flaky_run(error_attempts=throttles)
        with (
            patch(
                "cliff.agents.executor.create_agent_run",
                return_value=_make_mock_agent_run(),
            ),
            patch("cliff.agents.executor.update_agent_run"),
            patch("cliff.agents.executor.list_agent_runs", return_value=[]),
            patch("cliff.agents.executor.map_and_upsert"),
            patch("cliff.agents.executor._advance_finding_status", return_value=None),
            patch("cliff.agents.executor.build_model", return_value=MagicMock()),
            patch("cliff.agents.executor.run_no_tools_agent", flaky),
        ):
            result = await executor.execute(
                "ws-f1", "finding_enricher", AsyncMock(), workspace_dir=workspace_dir,
            )
        final_statuses.append(result.status)
        assert result.status == "completed", (
            f"run with {throttles} throttles should recover; got {result.status!r}"
        )

    assert final_statuses == ["completed"] * len(throttle_sequence)


# ---------------------------------------------------------------------------
# H3 — Concurrent backoff jitter (EF-B17 root cause)
# ---------------------------------------------------------------------------


def test_backoff_jitter_desynchronizes_concurrent_retries(monkeypatch):
    """The jitter in ``_rate_limit_backoff_delay`` exists exclusively to
    break coincident wakes when pool>=2 concurrent agents all hit the same
    provider quota and retry on the same exponential schedule. Without
    jitter every executor would sleep ``base * 2**(attempt-1)`` exactly and
    wake in lockstep — the retry-storm shape EF-B17 prevents.

    Samples 50 delays at the same ``attempt`` and asserts: (1) they are not
    all equal, (2) the spread covers at least 25% of the base delay, (3)
    every delay respects the MAX cap.
    """
    monkeypatch.setattr(executor_module, "RATE_LIMIT_BASE_DELAY_SECONDS", 1.0)
    monkeypatch.setattr(executor_module, "RATE_LIMIT_MAX_DELAY_SECONDS", 16.0)

    delays = [
        executor_module._rate_limit_backoff_delay(attempt=2)
        for _ in range(50)
    ]
    assert len(set(delays)) > 1, (
        "jitter is gone — every retry would wake at the same instant"
    )
    spread = max(delays) - min(delays)
    assert spread >= 0.25, (
        f"jitter spread {spread:.3f}s is too narrow; concurrent retries "
        "would still bunch up under load"
    )
    assert all(d <= 16.0 for d in delays), (
        f"jitter pushed a retry above MAX_DELAY: {max(delays)}"
    )
