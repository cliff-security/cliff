"""Q01R B24 — lock the posture auto-fix registry to what the backend ships.

The dashboard surfaces an "Auto-fix" CTA per posture check listed in
``_AUTO_FIXABLE_CHECKS``. The backend's ``POST /api/posture/fix/{check_name}``
only accepts ``security_md`` and ``dependabot_config`` today. Until the agent
templates + ``WorkspaceKind`` values for the other checks land (tracked in the
follow-up BACKLOG items called out in IMPL-0013), the dashboard registry must
not advertise a button the API will 422 on.

These tests pin the registry shape so the contract drift never reopens
silently. When a new auto-fixable check ships, update both this test and the
``PostureFixCheckName`` Literal in lockstep.
"""

from __future__ import annotations

from cliff.api.routes._level_up import (
    _AUTO_FIXABLE_CHECKS,
    derive_level_up,
)
from cliff.models.assessment import CriteriaSnapshot
from cliff.models.finding import Finding, IssueDerived


def test_auto_fixable_checks_only_what_backend_supports() -> None:
    """B24 — the dashboard registry must mirror the route's accepted enum."""
    assert _AUTO_FIXABLE_CHECKS == ("security_md", "dependabot_config")


def _all_passing_criteria() -> CriteriaSnapshot:
    return CriteriaSnapshot(
        no_critical_vulns=True,
        no_high_vulns=True,
        security_md_present=True,
        dependabot_present=True,
        branch_protection_enabled=True,
        no_secrets_detected=True,
        actions_pinned_to_sha=True,
        no_stale_collaborators=True,
        code_owners_exists=True,
        secret_scanning_enabled=True,
        posture_checks_passing=15,
        posture_checks_total=15,
    )


def _posture_finding(name: str) -> Finding:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return Finding(
        id=f"posture-{name}",
        source_type="cliff-posture",
        source_id=name,
        title=name,
        type="posture",
        status="new",
        grade_impact="counts",
        raw_payload={"check_name": name},
        created_at=now,
        updated_at=now,
        derived=IssueDerived(section="todo", stage="todo"),
    )


def test_dashboard_payload_drops_unsupported_checks_from_auto_fixable() -> None:
    """B24 — when both supported and unsupported checks are unmet, only the
    supported ones appear in ``auto_fixable_check_names`` so the UI never
    fans out a fix POST that the backend will 422.
    """
    snap = _all_passing_criteria().model_copy(
        update={
            "security_md_present": False,        # supported
            "dependabot_present": False,         # supported
            "code_owners_exists": False,         # NOT supported by route enum
            "actions_pinned_to_sha": False,      # NOT supported by route enum
            "posture_checks_passing": 11,
        }
    )
    posture = [
        _posture_finding("security_md"),
        _posture_finding("dependabot_config"),
        _posture_finding("code_owners_exists"),
        _posture_finding("actions_pinned_to_sha"),
    ]
    out = derive_level_up(
        grade="B",
        criteria_snapshot=snap,
        open_findings=[],
        posture_findings=posture,
    )
    assert out is not None
    posture_gate = next(g for g in out.gates if g.id == "posture_remaining")
    assert posture_gate.status == "auto_fixable"
    # Only the two checks the backend will accept may appear here.
    assert sorted(posture_gate.auto_fixable_check_names) == [
        "dependabot_config",
        "security_md",
    ]
