"""Tests for the assessment background runner (migration 015 — failure surfacing).

Covers the new exception classifier, the outer ``asyncio.timeout`` safety
net, the failure-detail persistence, and the cancellation handler.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from cliff.api._background import (
    classify_assessment_failure,
    run_and_persist_assessment,
)
from cliff.assessment.clone import CloneError, CloneTimeoutError
from cliff.assessment.scanners.runner import ScannerTimeoutError
from cliff.db.dao.assessment import create_assessment, get_assessment
from cliff.models import AssessmentCreate, AssessmentTool, AssessmentToolResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import aiosqlite


# --------------------------------------------------------------------- classifier


class TestClassifyAssessmentFailure:
    def test_clone_error_maps_to_clone_failed(self):
        kind, message, step = classify_assessment_failure(
            CloneError("git clone failed for https://github.com/x/y (exit 128)"),
            live_step="detect",
        )
        assert kind == "clone_failed"
        assert "clone" in message.lower()
        # CloneError always maps to step='clone' regardless of the live step,
        # because the engine emits 'detect' before the clone returns.
        assert step == "clone"

    def test_clone_timeout_also_maps_to_clone_failed(self):
        kind, _msg, step = classify_assessment_failure(
            CloneTimeoutError("git clone timed out after 60.0s"),
            live_step="detect",
        )
        assert kind == "clone_failed"
        assert step == "clone"

    def test_outer_timeout_maps_to_timeout_with_live_step(self):
        kind, message, step = classify_assessment_failure(
            TimeoutError(),
            live_step="posture",
        )
        assert kind == "timeout"
        assert "too long" in message.lower()
        assert step == "posture"

    def test_scanner_timeout_maps_to_timeout(self):
        kind, _msg, step = classify_assessment_failure(
            ScannerTimeoutError("trivy timed out"),
            live_step="trivy_vuln",
        )
        assert kind == "timeout"
        assert step == "trivy_vuln"

    def test_value_error_maps_to_internal_error(self):
        kind, message, _step = classify_assessment_failure(
            ValueError("bad URL"),
            live_step="detect",
        )
        assert kind == "internal_error"
        assert "url" in message.lower() or "invalid" in message.lower()

    def test_generic_exception_maps_to_internal_error(self):
        kind, _message, step = classify_assessment_failure(
            RuntimeError("kaboom"),
            live_step="semgrep",
        )
        assert kind == "internal_error"
        assert step == "semgrep"

    def test_unknown_live_step_coerces_to_unknown_label(self):
        _kind, _msg, step = classify_assessment_failure(
            RuntimeError("kaboom"),
            live_step="something_made_up",
        )
        assert step == "unknown"

    def test_file_not_found_with_filename_names_the_missing_binary(self):
        """Missing scanner binary surfaces ``trivy`` (or whichever) at the
        headline level so the user can run ``scripts/install-scanners.sh``
        without expanding the technical-details disclosure."""
        exc = FileNotFoundError(2, "No such file or directory", "trivy")
        kind, message, step = classify_assessment_failure(
            exc, live_step="trivy_vuln"
        )
        assert kind == "internal_error"
        assert "trivy" in message
        assert "install-scanners.sh" in message
        assert step == "trivy_vuln"

    def test_file_not_found_without_filename_falls_back_to_message_parse(self):
        """Some glibc/uvloop combos raise FileNotFoundError without setting
        ``filename``. The classifier must still produce a useful headline."""
        exc = FileNotFoundError("[Errno 2] No such file or directory: 'semgrep'")
        _kind, message, _step = classify_assessment_failure(
            exc, live_step="semgrep"
        )
        assert "semgrep" in message
        assert "install-scanners.sh" in message

    def test_file_not_found_with_no_signal_uses_generic_headline(self):
        """If neither ``filename`` nor a parseable message is present we fall
        back to a generic 'binary missing' headline rather than letting it
        slip through to 'Something went wrong'."""
        exc = FileNotFoundError("opaque")
        _kind, message, _step = classify_assessment_failure(
            exc, live_step="trivy_vuln"
        )
        assert "scanner binary" in message.lower()
        assert "install-scanners.sh" in message

    def test_missing_live_step_is_unknown(self):
        _kind, _msg, step = classify_assessment_failure(
            RuntimeError("kaboom"),
            live_step=None,
        )
        assert step == "unknown"


# --------------------------------------------------------------------- runner


class _StubEngine:
    """Minimal AssessmentEngineProtocol-compatible double for runner tests."""

    def __init__(
        self,
        *,
        raise_on_run: BaseException | None = None,
        sleep_for: float | None = None,
        live_step: str | None = None,
    ) -> None:
        self._raise = raise_on_run
        self._sleep_for = sleep_for
        self._live_step = live_step

    async def run_assessment(
        self,
        repo_url: str,
        *,
        assessment_id: str,
        db: object | None = None,
        on_step: Callable[[str], Awaitable[None]] | None = None,
        on_tool: Callable[[AssessmentTool], Awaitable[None]] | None = None,
    ):
        if on_step is not None and self._live_step is not None:
            await on_step(self._live_step)
        if on_tool is not None:
            await on_tool(
                AssessmentTool(
                    id="trivy",
                    label="Trivy",
                    icon="bug_report",
                    state="active",
                    result=AssessmentToolResult(
                        kind="findings_count", value=0, text="0 findings"
                    ),
                )
            )
        if self._sleep_for is not None:
            await asyncio.sleep(self._sleep_for)
        if self._raise is not None:
            raise self._raise
        raise AssertionError("stub never reaches happy path")


@pytest.fixture
async def created_assessment(db: aiosqlite.Connection):
    return await create_assessment(
        db, AssessmentCreate(repo_url="https://github.com/x/y")
    )


async def test_runner_persists_clone_failure_detail(db, created_assessment):
    engine = _StubEngine(
        raise_on_run=CloneError(
            "git clone failed for https://github.com/x/y (exit 128): repo not found"
        ),
        live_step="detect",
    )

    await run_and_persist_assessment(
        db, engine, created_assessment.id, "https://github.com/x/y"
    )

    a = await get_assessment(db, created_assessment.id)
    assert a is not None
    assert a.status == "failed"
    assert a.error_kind == "clone_failed"
    assert a.failed_step == "clone"
    assert a.error_message and "clone" in a.error_message.lower()
    assert a.error_details and "repo not found" in a.error_details


async def test_runner_persists_internal_error_with_live_step(
    db, created_assessment
):
    engine = _StubEngine(
        raise_on_run=RuntimeError("posture exploded"),
        live_step="posture",
    )

    await run_and_persist_assessment(
        db, engine, created_assessment.id, "https://github.com/x/y"
    )

    a = await get_assessment(db, created_assessment.id)
    assert a is not None
    assert a.status == "failed"
    assert a.error_kind == "internal_error"
    assert a.failed_step == "posture"
    assert a.error_details and "posture exploded" in a.error_details


async def test_runner_outer_timeout_marks_failed_as_timeout(
    db, created_assessment
):
    # Stub engine sleeps longer than the timeout; the asyncio.timeout in
    # run_and_persist_assessment must fire and persist a 'timeout' kind.
    engine = _StubEngine(sleep_for=0.5, live_step="posture")

    await run_and_persist_assessment(
        db,
        engine,
        created_assessment.id,
        "https://github.com/x/y",
        timeout_s=0.05,
    )

    a = await get_assessment(db, created_assessment.id)
    assert a is not None
    assert a.status == "failed"
    assert a.error_kind == "timeout"
    assert a.failed_step == "posture"
    assert a.error_message and "too long" in a.error_message.lower()


async def test_runner_truncates_huge_error_details(db, created_assessment):
    huge = "ERROR " * 10_000  # well over the 4_000 char cap
    engine = _StubEngine(
        raise_on_run=RuntimeError(huge),
        live_step="trivy_vuln",
    )

    await run_and_persist_assessment(
        db, engine, created_assessment.id, "https://github.com/x/y"
    )

    a = await get_assessment(db, created_assessment.id)
    assert a is not None
    assert a.error_details is not None
    assert len(a.error_details) < len(huge)
    assert "truncated" in a.error_details.lower()


async def test_cancellation_persists_interrupted_then_reraises(
    db, created_assessment
):
    class _CancelEngine:
        async def run_assessment(self, *_a, **_k):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_and_persist_assessment(
            db, _CancelEngine(), created_assessment.id, "https://github.com/x/y"
        )

    a = await get_assessment(db, created_assessment.id)
    assert a is not None
    assert a.status == "failed"
    assert a.error_kind == "interrupted"
    assert a.error_message and "interrupted" in a.error_message.lower()
