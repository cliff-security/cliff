"""EF-B17 regression — exponential backoff on upstream LLM rate-limit.

Wave-1 evidence (`docs/qa/evidence/Q01/B14-B20/B17-failed-runs-sample.txt`)
shows agent runs failing at exactly 76 s under workspace-pool concurrency.
The root cause: OpenCode wraps an upstream provider 429 into a
``session.error`` SSE event, which the executor used to surface as a fatal
``AgentProcessError`` with no retry. These tests prove that:

1. A retry-able rate-limit (1-2 throttles followed by success) now finishes
   the run with ``status == 'completed'`` instead of failing on attempt 1.
2. A persistent rate-limit terminates the run with ``status='rate_limited'``
   AND ``last_error`` populated — no silent 76 s timeouts. (``last_error``
   is the canonical error column since migration 021; the older
   ``evidence_json['error']`` mirror is no longer written.)

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

from cliff.agents import executor as executor_module
from cliff.agents.executor import AgentExecutor
from cliff.models import AgentRun

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
        agent_type="remediation_executor",
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
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.map_and_upsert"),
        patch("cliff.agents.executor._advance_finding_status", return_value=None),
    ):
        result = await executor.execute(
            "ws-rl", "remediation_executor", db, workspace_dir=workspace_dir,
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
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.map_and_upsert"),
        patch("cliff.agents.executor._advance_finding_status", return_value=None),
    ):
        result = await executor.execute(
            "ws-rl", "remediation_executor", db, workspace_dir=workspace_dir,
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

    # DB update must carry status + last_error (canonical column since
    # migration 021).
    final_call = mock_update.call_args_list[-1]
    final_update = final_call[0][2]
    assert final_update.status == "rate_limited"
    assert final_update.last_error and "rate limit" in final_update.last_error.lower()
    # evidence_json is intentionally not written on failure paths anymore
    # (drop confirmed by /architect: nothing consumed the JSON mirror).
    assert final_update.evidence_json is None


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
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
    ):
        result = await executor.execute(
            "ws-rl", "remediation_executor", db, workspace_dir=workspace_dir,
        )

    assert result.status == "failed"
    assert attempts["n"] == 1, "non-rate-limit errors must not retry"
    final_update = mock_update.call_args_list[-1][0][2]
    assert final_update.status == "failed"
    assert final_update.last_error and "500" in final_update.last_error


# ---------------------------------------------------------------------------
# Real-world OpenCode error-message corpus
# ---------------------------------------------------------------------------
#
# Every entry below is taken from a real source — either the running
# OpenCode binary or the Effect AI SDK that OpenCode embeds — NOT a string
# someone made up to test against. These are the wire shapes that show up
# inside ``properties.error.data.message`` in OpenCode's ``session.error``
# SSE event (unwrapped by ``cliff.engine.client.OpenCodeClient.stream_events``
# at engine/client.py:284-287) when an upstream provider 429s.
#
# Sources:
#   * Effect AI SDK: ``effect/dist/unstable/ai/AiError.js``
#     - ``RateLimitError.message``:
#       ``"Rate limit exceeded"`` (optionally
#       ``". Retry after {N} {unit}"``) — isRetryable=true
#     - ``QuotaExhaustedError.message``:
#       ``"Quota exhausted. Check your account billing and usage limits."``
#       — isRetryable=false → must NOT retry (billing action required)
#   * OpenCode binary strings: literal ``"429 Too Many Requests"`` HTTP form
#   * Cliff's own ``_humanize_process_error`` (executor.py:519-560), built
#     from prior production incidents — the substring set matches the
#     historic real wordings.

_REAL_RATE_LIMIT_MESSAGES = [
    # Canonical Effect AI SDK shape with no retry-after metadata.
    "Rate limit exceeded",
    # Effect AI SDK shape with retry-after suffix (the common case once
    # the upstream provider returns ``Retry-After``).
    "OpenAI.completion: Rate limit exceeded. Retry after 1 minute",
    "Anthropic.chat: Rate limit exceeded. Retry after 30 seconds",
    # Raw HTTP wire form that surfaces when Effect AI SDK isn't in the
    # loop (extracted from the OpenCode binary).
    "429 Too Many Requests",
    # Provider-native wording — Anthropic's actual 429 body string.
    "Number of requests has exceeded your rate limit",
    # Capitalization / punctuation drift — our classifier lowercases first.
    "RATE LIMIT exceeded for requests on this org",
]


@pytest.mark.parametrize("message", _REAL_RATE_LIMIT_MESSAGES)
@pytest.mark.asyncio
async def test_real_world_rate_limit_messages_classify_and_retry(
    monkeypatch, workspace_dir, message,
):
    """For every known real OpenCode-wrapped rate-limit message shape, the
    executor classifies it as a rate-limit, retries, and (when retries are
    exhausted) terminates with ``status=rate_limited``.

    If a real production message shape lands here that DOESN'T match the
    substring set in ``_RATE_LIMIT_SUBSTRINGS``, this test will fail
    deterministically — that's the signal to widen the classifier rather
    than discover the regression in a bulk-remediation pass.
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
        yield {"type": "error", "message": message}

    client.stream_events = stream_events
    pool.get_or_start.return_value = client

    executor = AgentExecutor(pool, builder)

    with (
        patch(
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
        patch("cliff.agents.executor.map_and_upsert"),
        patch("cliff.agents.executor._advance_finding_status", return_value=None),
    ):
        result = await executor.execute(
            "ws-rl", "remediation_executor", db, workspace_dir=workspace_dir,
        )

    assert result.status == "rate_limited", (
        f"real-world message {message!r} should classify as rate_limited; "
        f"got {result.status!r}"
    )
    assert attempts["n"] == executor_module.RATE_LIMIT_MAX_ATTEMPTS, (
        f"expected full retry budget for {message!r}; ran {attempts['n']}"
    )
    final_update = mock_update.call_args_list[-1][0][2]
    assert final_update.status == "rate_limited"
    assert final_update.last_error


# Messages that LOOK similar to rate-limits but are explicitly NOT
# retry-able — the classifier must let them fall through to the
# regular failure path. Wrong classification here would silently waste
# 14+ seconds retrying a request that will never succeed and would mask
# the actionable error from the user.
_LOOKALIKE_NON_RATE_LIMIT_MESSAGES = [
    # Effect AI SDK QuotaExhaustedError — billing/quota cap, user must
    # act (add credits, change plan). isRetryable=false in the SDK.
    "Quota exhausted. Check your account billing and usage limits.",
    # OpenRouter / Anthropic credit-balance shape — handled by
    # _humanize_process_error separately, no retry.
    "Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits.",
    # Generic provider 500 — transient but not a rate-limit; the
    # existing process-error path handles it.
    "Provider returned 500 internal error",
    # 404-ish — the historic "OpenCode error: Not Found" shape seen in
    # docs/qa/evidence/Q01/walk-6-findings/F-001-minimist-runs.json.
    "Not Found",
]


@pytest.mark.parametrize("message", _LOOKALIKE_NON_RATE_LIMIT_MESSAGES)
@pytest.mark.asyncio
async def test_lookalike_messages_do_not_trigger_rate_limit_retry(
    monkeypatch, workspace_dir, message,
):
    """Quota-exhausted / credit-balance / 500 / Not-Found messages must NOT
    match the rate-limit classifier. They should fail fast on the first
    attempt with ``status=failed`` — retrying them wastes the user's time
    and masks the actionable error (e.g. "add credits").
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
        yield {"type": "error", "message": message}

    client.stream_events = stream_events
    pool.get_or_start.return_value = client

    executor = AgentExecutor(pool, builder)

    with (
        patch(
            "cliff.agents.executor.create_agent_run",
            return_value=_make_mock_agent_run(),
        ),
        patch("cliff.agents.executor.update_agent_run") as mock_update,
        patch("cliff.agents.executor.list_agent_runs", return_value=[]),
    ):
        result = await executor.execute(
            "ws-rl", "remediation_executor", db, workspace_dir=workspace_dir,
        )

    assert result.status == "failed", (
        f"lookalike message {message!r} must NOT classify as rate-limit; "
        f"got status={result.status!r}"
    )
    assert attempts["n"] == 1, (
        f"lookalike message {message!r} must fail fast on attempt 1; "
        f"ran {attempts['n']} attempts (would waste backoff budget)"
    )
    final_update = mock_update.call_args_list[-1][0][2]
    assert final_update.status == "failed"


# ---------------------------------------------------------------------------
# F1-minimist-style scenario — emulates the Wave-1 bulk-remediation flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f1_minimist_style_scenario_recovers_under_throttling(
    monkeypatch, workspace_dir,
):
    """Emulates the Q01-Wave-1 F1-minimist failure pattern: a sequence of
    agent runs where the provider intermittently 429s (the load that used
    to silently kill 6 of 22 findings). Each individual run takes 1-2
    throttles before succeeding. Proves the executor recovers per-run
    without leaving any "phantom" 76 s failures in the agent_run table.

    This is the closest deterministic test to the actual Wave-1 evidence
    (docs/qa/evidence/Q01/B14-B20/B17-failed-runs-sample.txt) — same
    cadence (multiple consecutive agents), same throttle pattern, just
    with monkeypatched delays + mocked OpenCode.
    """

    monkeypatch.setattr(executor_module, "RATE_LIMIT_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "RATE_LIMIT_MAX_DELAY_SECONDS", 0.0)

    pool = AsyncMock()
    builder = AsyncMock()
    builder.update_context.return_value = 1
    db = AsyncMock()

    executor = AgentExecutor(pool, builder)

    # Mirror the F1-minimist agent sequence from Wave-1 evidence. After
    # ADR-0047 only the remediation_executor exercises the OpenCode
    # SSE/rate-limit surface; the five consecutive runs preserve the
    # original test intent (a sustained rate-limit-pressure scenario
    # recovers row-by-row instead of failing on the first throttle).
    agent_sequence = [
        ("remediation_executor", 0),  # first try succeeds (cold cache)
        ("remediation_executor", 2),  # 2 throttles, then success
        ("remediation_executor", 2),  # 2 throttles, then success
        ("remediation_executor", 1),  # 1 throttle, then success
        ("remediation_executor", 0),  # succeeds
    ]

    final_statuses: list[str] = []

    for agent_type, throttle_count in agent_sequence:
        client = _make_flaky_client(error_attempts=throttle_count)
        pool.get_or_start.return_value = client

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
                "ws-f1", agent_type, db, workspace_dir=workspace_dir,
            )
        final_statuses.append(result.status)
        # Pre-fix behavior: any throttle would produce ``status=failed``
        # at 76 s. New behavior: every agent completes after retries.
        assert result.status == "completed", (
            f"agent {agent_type!r} (throttles={throttle_count}) should "
            f"recover under backoff; got {result.status!r}"
        )

    assert final_statuses == ["completed"] * len(agent_sequence)


# ---------------------------------------------------------------------------
# H3 — Concurrent backoff under pool>=2 (EF-B17 root cause)
# ---------------------------------------------------------------------------


def test_backoff_jitter_desynchronizes_concurrent_retries(monkeypatch):
    """The jitter in ``_rate_limit_backoff_delay`` exists exclusively
    to break coincident wakes when pool>=2 concurrent agents all hit
    the same provider quota and retry on the same exponential
    schedule. Without jitter every executor would sleep for
    ``base * 2**(attempt-1)`` exactly and wake in lockstep — the
    retry-storm shape EF-B17 was meant to prevent.

    Architect test-coverage gap H3: the original 6 backoff tests are
    all serial; this directly exercises the jitter math. The test
    samples 50 delays at the same ``attempt`` and asserts:
      1. They are NOT all equal (jitter is doing something).
      2. The spread covers at least 25% of the base delay (jitter is
         the documented "up to one base-delay" range).
      3. Every delay respects the documented MAX cap.
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


# ---------------------------------------------------------------------------
# Architect test-coverage gap: pipeline halts on rate_limited
# ---------------------------------------------------------------------------
