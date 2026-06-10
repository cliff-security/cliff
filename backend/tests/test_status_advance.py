"""Tests for auto-advancing finding status after agent completions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from cliff.agents.executor import _advance_finding_status
from cliff.models import Finding, Workspace


def _make_finding(status: str = "new") -> Finding:
    now = datetime.now(UTC)
    return Finding(
        id="f-1",
        source_type="tenable",
        source_id="CVE-2026-0001",
        title="Test vuln",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_workspace(finding_id: str = "f-1") -> Workspace:
    now = datetime.now(UTC)
    return Workspace(
        id="ws-1",
        finding_id=finding_id,
        state="open",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdvanceFindingStatus:
    @pytest.mark.asyncio
    async def test_enricher_does_not_auto_advance_new_to_triaged(self):
        """ADR-0051 §6 amends ADR-0040 §9 / BACKLOG WP6: the enricher no longer
        auto-advances `new → triaged`. ``triaged`` now means "triage confirmed
        the finding is real," set only on human confirmation of a `real`
        verdict — enrichment is an input to triage, not a verdict."""
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("new")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "finding_enricher", {}
            )
            assert result is None
            mock_upd.assert_not_called()

    @pytest.mark.asyncio
    async def test_enricher_does_not_regress_in_progress(self):
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("in_progress")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "finding_enricher", {}
            )
            assert result is None
            mock_upd.assert_not_called()

    @pytest.mark.asyncio
    async def test_planner_advances_triaged_to_in_progress(self):
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("triaged")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "remediation_planner", {}
            )
            assert result == "in_progress"
            mock_upd.assert_called_once()

    @pytest.mark.asyncio
    async def test_executor_pr_created_advances_to_remediated(self):
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("in_progress")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "remediation_executor", {"status": "pr_created"}
            )
            assert result == "remediated"
            mock_upd.assert_called_once()

    @pytest.mark.asyncio
    async def test_executor_without_pr_does_not_advance(self):
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("in_progress")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "remediation_executor", {"status": "changes_made"}
            )
            assert result is None
            mock_upd.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_fixed_advances_to_validated(self):
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("remediated")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "validation_checker", {"verdict": "fixed"}
            )
            assert result == "validated"
            mock_upd.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_not_fixed_does_not_advance(self):
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("remediated")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "validation_checker", {"verdict": "not_fixed"}
            )
            assert result is None
            mock_upd.assert_not_called()

    @pytest.mark.asyncio
    async def test_exposure_analyzer_does_not_advance(self):
        db = AsyncMock()
        with (
            patch("cliff.agents.executor.get_workspace", return_value=_make_workspace()),
            patch("cliff.agents.executor.get_finding", return_value=_make_finding("triaged")),
            patch("cliff.agents.executor.update_finding") as mock_upd,
        ):
            result = await _advance_finding_status(
                db, "ws-1", "exposure_analyzer", {}
            )
            assert result is None
            mock_upd.assert_not_called()
