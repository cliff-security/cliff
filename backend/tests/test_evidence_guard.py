"""Tests for the evidence_collector deterministic guards (Q01-B11, B13)."""

from __future__ import annotations

from cliff.services.evidence_guard import guard_evidence_output


def _finding(version: str | None, fixed_version: str | None) -> dict:
    return {
        "id": "f-1",
        "raw_payload": {
            "package": "tar",
            "version": version,
            "fixed_version": fixed_version,
        },
    }


# ---------------------------------------------------------------------------
# B11 — semver major-delta guard on fix_safety
# ---------------------------------------------------------------------------


def test_major_jump_safe_bump_is_corrected_to_breaking_change() -> None:
    """The B11 case: tar 4.x -> 7.x labelled safe_bump must become
    breaking_change, with the reason recorded."""
    out = {
        "fix_safety": "safe_bump",
        "fix_safety_reasoning": "looks routine",
        "current_version": "4.4.8",  # set so the B13 backfill stays quiet
    }
    corrections = guard_evidence_output(out, _finding("4.4.8", "7.5.11"))

    assert out["fix_safety"] == "breaking_change"
    assert "semver guard" in out["fix_safety_reasoning"].lower()
    assert "looks routine" in out["fix_safety_reasoning"]  # original kept
    assert len(corrections) == 1
    assert "3-major" in corrections[0]


def test_minor_bump_safe_bump_is_left_alone() -> None:
    """A within-major upgrade is a legitimate safe_bump — don't touch it."""
    out = {"fix_safety": "safe_bump", "current_version": "4.16.4"}
    corrections = guard_evidence_output(out, _finding("4.16.4", "4.19.2"))
    assert out["fix_safety"] == "safe_bump"
    assert corrections == []


def test_multi_valued_fixed_version_uses_smallest_major() -> None:
    """Trivy lists several fix versions; the smallest major is the
    least-breaking option — a 4.x fix available means it's still a
    safe_bump even though a 5.0 beta is also listed."""
    out = {"fix_safety": "safe_bump", "current_version": "4.16.4"}
    corrections = guard_evidence_output(
        out, _finding("4.16.4", "4.19.2, 5.0.0-beta.3")
    )
    assert out["fix_safety"] == "safe_bump"
    assert corrections == []


def test_major_jump_only_overrides_safe_bump() -> None:
    """If the agent already classified a major jump conservatively, leave
    its (more cautious) verdict alone — only the falsely-reassuring
    safe_bump is corrected."""
    for verdict in ("breaking_change", "needs_migration", "code_fix"):
        out = {"fix_safety": verdict, "current_version": "4.4.8"}
        corrections = guard_evidence_output(out, _finding("4.4.8", "7.5.11"))
        assert out["fix_safety"] == verdict
        assert corrections == []


# ---------------------------------------------------------------------------
# B13 — current_version backfill
# ---------------------------------------------------------------------------


def test_null_current_version_is_backfilled_from_scanner() -> None:
    out = {"current_version": None, "fix_safety": "safe_bump"}
    corrections = guard_evidence_output(out, _finding("1.2.5", "1.2.6"))
    assert out["current_version"] == "1.2.5"
    assert any("current_version backfilled" in c for c in corrections)


def test_missing_current_version_key_is_backfilled() -> None:
    out = {"fix_safety": "safe_bump"}
    guard_evidence_output(out, _finding("1.2.5", "1.2.6"))
    assert out["current_version"] == "1.2.5"


def test_present_current_version_is_not_overwritten() -> None:
    out = {"current_version": "1.2.5-custom"}
    corrections = guard_evidence_output(out, _finding("1.2.5", "1.2.6"))
    assert out["current_version"] == "1.2.5-custom"
    assert corrections == []


# ---------------------------------------------------------------------------
# Defensive — non-dependency findings & malformed input
# ---------------------------------------------------------------------------


def test_finding_without_version_data_is_noop() -> None:
    """A semgrep/secret finding has no scanner version data — leave the
    agent's output untouched."""
    out = {"fix_safety": "safe_bump", "current_version": None}
    finding = {"id": "f-1", "raw_payload": {"check_id": "xss"}}
    corrections = guard_evidence_output(out, finding)
    assert corrections == []
    assert out["fix_safety"] == "safe_bump"


def test_non_dict_structured_output_returns_empty() -> None:
    assert guard_evidence_output(None, _finding("4.4.8", "7.5.11")) == []
    assert guard_evidence_output("oops", _finding("4.4.8", "7.5.11")) == []


def test_finding_without_raw_payload_is_noop() -> None:
    out = {"fix_safety": "safe_bump"}
    assert guard_evidence_output(out, {"id": "f-1"}) == []
    assert guard_evidence_output(out, None) == []
