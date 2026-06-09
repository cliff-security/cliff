"""Tests for the sidebar mapper."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from cliff.agents.sidebar_mapper import map_and_upsert, map_to_sidebar_update
from cliff.models import SidebarState, SidebarStateUpdate

# ---------------------------------------------------------------------------
# map_to_sidebar_update (pure function tests)
# ---------------------------------------------------------------------------


class TestMapToSidebarUpdate:
    def test_enricher_maps_summary_and_evidence(self):
        out = {
            "normalized_title": "CVE-2026-1234 RCE",
            "cvss_score": 9.1,
            "cve_ids": ["CVE-2026-1234"],
            "known_exploits": True,
            "exploit_details": "PoC available",
            "references": ["https://nvd.nist.gov/..."],
            "fixed_version": "2.3.1",
            "affected_versions": "< 2.3.1",
        }
        update = map_to_sidebar_update("finding_enricher", out)
        assert update.summary is not None
        assert update.summary["title"] == "CVE-2026-1234 RCE"
        assert update.summary["cvss_score"] == 9.1
        assert update.evidence is not None
        assert update.evidence["known_exploits"] is True
        assert update.evidence["fixed_version"] == "2.3.1"
        # Other sections should be None
        assert update.owner is None
        assert update.plan is None
        assert update.validation is None

    def test_owner_maps_owner_section(self):
        out = {
            "recommended_owner": "Platform Team",
            "candidates": [{"team": "Platform", "confidence": 0.9}],
            "reasoning": "Based on CODEOWNERS",
        }
        update = map_to_sidebar_update("owner_resolver", out)
        assert update.owner is not None
        assert update.owner["recommended_owner"] == "Platform Team"
        assert update.summary is None

    def test_exposure_maps_evidence(self):
        out = {
            "environment": "production",
            "internet_facing": True,
            "reachable": "likely",
            "blast_radius": "Auth flow",
            "recommended_urgency": "immediate",
        }
        update = map_to_sidebar_update("exposure_analyzer", out)
        assert update.evidence is not None
        assert update.evidence["recommended_urgency"] == "immediate"
        assert update.evidence["internet_facing"] is True

    def test_planner_maps_plan_and_dod(self):
        out = {
            "plan_steps": ["Upgrade package", "Test", "Deploy"],
            "definition_of_done": ["Tests pass", "Scanner clear"],
            "interim_mitigation": "WAF rule",
            "estimated_effort": "small",
            "validation_method": "Re-scan",
        }
        update = map_to_sidebar_update("remediation_planner", out)
        assert update.plan is not None
        assert len(update.plan["plan_steps"]) == 3
        assert update.definition_of_done is not None
        assert update.definition_of_done["items"] == ["Tests pass", "Scanner clear"]

    def test_validation_maps_validation(self):
        out = {
            "verdict": "fixed",
            "evidence": "CVE no longer detected",
            "remaining_concerns": [],
            "recommendation": "close",
        }
        update = map_to_sidebar_update("validation_checker", out)
        assert update.validation is not None
        assert update.validation["verdict"] == "fixed"

    def test_executor_maps_pull_request(self):
        out = {
            "status": "pr_created",
            "pr_url": "https://github.com/acme/repo/pull/42",
            "branch_name": "cliff/fix/cve-2026-1234",
            "changes_summary": "Updated log4j-core to 2.17.1 in pom.xml",
            "test_results": "pass",
            "error_details": None,
        }
        update = map_to_sidebar_update("remediation_executor", out)
        assert update.pull_request is not None
        assert update.pull_request["status"] == "pr_created"
        assert update.pull_request["pr_url"] == "https://github.com/acme/repo/pull/42"
        assert update.pull_request["branch_name"] == "cliff/fix/cve-2026-1234"
        assert update.pull_request["changes_summary"] == "Updated log4j-core to 2.17.1 in pom.xml"
        assert update.pull_request["test_results"] == "pass"
        # Other sections should be None
        assert update.summary is None
        assert update.evidence is None
        assert update.plan is None
        assert update.validation is None

    def test_executor_maps_failed_status(self):
        out = {
            "status": "failed",
            "error_details": "Tests failed: 3 of 50",
            "branch_name": "cliff/fix/cve-2026-1234",
        }
        update = map_to_sidebar_update("remediation_executor", out)
        assert update.pull_request is not None
        assert update.pull_request["status"] == "failed"
        assert update.pull_request["error_details"] == "Tests failed: 3 of 50"
        assert update.pull_request["pr_url"] is None

    def test_unknown_agent_returns_empty(self):
        update = map_to_sidebar_update("unknown_agent", {"foo": "bar"})
        assert update.summary is None
        assert update.evidence is None
        assert update.owner is None

    def test_report_triager_maps_triage_section_only(self):
        """ADR-0051 §5 — triage lands in its own section, disjoint from the
        ``evidence`` section the enricher/exposure/evidence agents share."""
        out = {
            "verdict": "unexploitable",
            "confidence": 0.88,
            "recommended_close": "unexploitable",
            "reachability": {"reached": False, "path": [], "summary": "No path found."},
            "checks": [{"eyebrow": "REACHABILITY", "result": "No path", "kind": "pass"}],
        }
        update = map_to_sidebar_update("report_triager", out)
        assert update.triage is not None
        assert update.triage["verdict"] == "unexploitable"
        # Disjoint from every other section.
        assert update.evidence is None
        assert update.summary is None
        assert update.validation is None

    def test_triage_synthesizer_key_also_maps_triage(self):
        """The scanner path persists synthesis output under the
        ``triage_synthesizer`` key (it is not a registered agent run)."""
        out = {"verdict": "real", "confidence": 0.9}
        update = map_to_sidebar_update("triage_synthesizer", out)
        assert update.triage is not None
        assert update.triage["verdict"] == "real"
        assert update.evidence is None


# ---------------------------------------------------------------------------
# map_and_upsert (async with mocked DB)
# ---------------------------------------------------------------------------


class TestMapAndUpsert:
    @pytest.mark.asyncio
    async def test_merge_preserves_existing_fields(self):
        """When enricher sets summary+evidence, then exposure sets evidence,
        the enricher's summary should survive."""
        existing = SidebarState(
            workspace_id="ws-1",
            summary={"title": "Existing title", "cvss_score": 9.0},
            evidence={"known_exploits": True, "fixed_version": "2.3.1"},
            owner=None,
            plan=None,
            definition_of_done=None,
            linked_ticket=None,
            validation=None,
            similar_cases=None,
            updated_at=datetime.now(UTC),
        )

        mock_db = AsyncMock()
        exposure_out = {
            "environment": "production",
            "recommended_urgency": "immediate",
        }

        with (
            patch(
                "cliff.db.repo_sidebar.get_sidebar",
                return_value=existing,
            ),
            patch(
                "cliff.db.repo_sidebar.upsert_sidebar",
            ) as mock_upsert,
        ):
            await map_and_upsert(mock_db, "ws-1", "exposure_analyzer", exposure_out)

            # Verify upsert was called
            mock_upsert.assert_called_once()
            call_args = mock_upsert.call_args
            update: SidebarStateUpdate = call_args[0][2]

            # Summary should be preserved from existing
            assert update.summary == {"title": "Existing title", "cvss_score": 9.0}
            # Evidence should be merged (enricher + exposure)
            assert update.evidence is not None
            assert update.evidence["known_exploits"] is True  # from enricher
            assert update.evidence["recommended_urgency"] == "immediate"  # from exposure

    @pytest.mark.asyncio
    async def test_triage_write_preserves_existing_evidence(self):
        """Writing the triage section must not clobber the evidence the
        enricher/exposure already wrote (ADR-0051 §5: disjoint sections)."""
        existing = SidebarState(
            workspace_id="ws-1",
            summary={"title": "CVE-2026-1234"},
            evidence={"reachable": "likely", "internet_facing": True},
            updated_at=datetime.now(UTC),
        )
        mock_db = AsyncMock()
        triage_out = {"verdict": "real", "confidence": 0.9, "recommended_close": None}

        with (
            patch("cliff.db.repo_sidebar.get_sidebar", return_value=existing),
            patch("cliff.db.repo_sidebar.upsert_sidebar") as mock_upsert,
        ):
            await map_and_upsert(mock_db, "ws-1", "report_triager", triage_out)
            update: SidebarStateUpdate = mock_upsert.call_args[0][2]
            assert update.triage is not None
            assert update.triage["verdict"] == "real"
            # Evidence + summary preserved untouched.
            assert update.evidence == {"reachable": "likely", "internet_facing": True}
            assert update.summary == {"title": "CVE-2026-1234"}

    @pytest.mark.asyncio
    async def test_first_agent_creates_sidebar(self):
        """When no sidebar exists yet, create from scratch."""
        mock_db = AsyncMock()
        enricher_out = {
            "normalized_title": "CVE-2026-1234",
            "cvss_score": 9.1,
            "cve_ids": ["CVE-2026-1234"],
            "known_exploits": False,
        }

        with (
            patch(
                "cliff.db.repo_sidebar.get_sidebar",
                return_value=None,
            ),
            patch(
                "cliff.db.repo_sidebar.upsert_sidebar",
            ) as mock_upsert,
        ):
            await map_and_upsert(mock_db, "ws-1", "finding_enricher", enricher_out)

            call_args = mock_upsert.call_args
            update: SidebarStateUpdate = call_args[0][2]
            assert update.summary is not None
            assert update.summary["title"] == "CVE-2026-1234"
            assert update.evidence is not None

    @pytest.mark.asyncio
    async def test_executor_preserves_existing_sections(self):
        """When executor runs, existing summary/plan should be preserved."""
        existing = SidebarState(
            workspace_id="ws-1",
            summary={"title": "CVE-2026-1234", "cvss_score": 9.1},
            evidence={"known_exploits": True},
            owner=None,
            plan={"plan_steps": ["Upgrade package"]},
            definition_of_done={"items": ["Tests pass"]},
            linked_ticket=None,
            validation=None,
            similar_cases=None,
            pull_request=None,
            updated_at=datetime.now(UTC),
        )

        mock_db = AsyncMock()
        executor_out = {
            "status": "pr_created",
            "pr_url": "https://github.com/acme/repo/pull/42",
            "branch_name": "cliff/fix/cve-2026-1234",
            "changes_summary": "Updated pom.xml",
            "test_results": "pass",
            "error_details": None,
        }

        with (
            patch(
                "cliff.db.repo_sidebar.get_sidebar",
                return_value=existing,
            ),
            patch(
                "cliff.db.repo_sidebar.upsert_sidebar",
            ) as mock_upsert,
        ):
            await map_and_upsert(mock_db, "ws-1", "remediation_executor", executor_out)

            call_args = mock_upsert.call_args
            update: SidebarStateUpdate = call_args[0][2]

            # Existing sections preserved
            assert update.summary == {"title": "CVE-2026-1234", "cvss_score": 9.1}
            assert update.plan == {"plan_steps": ["Upgrade package"]}
            # New pull_request section populated
            assert update.pull_request is not None
            assert update.pull_request["status"] == "pr_created"
            assert update.pull_request["pr_url"] == "https://github.com/acme/repo/pull/42"
