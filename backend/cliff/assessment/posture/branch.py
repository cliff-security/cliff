"""Pure builders for the three GitHub-backed posture checks.

Each builder takes already-fetched data (protection payload or commits list)
so the orchestrator can fetch once and share the result across multiple
checks. See `run_all_posture_checks` for the fetch-once wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cliff.assessment.posture import PostureCheckResult
from cliff.assessment.posture.github_client import UnableToVerify

if TYPE_CHECKING:
    from cliff.assessment.posture import RepoCoords

ProtectionPayload = dict[str, Any] | UnableToVerify | None
CommitsPayload = list[dict[str, Any]] | UnableToVerify


def build_branch_protection_result(
    protection: ProtectionPayload, coords: RepoCoords
) -> PostureCheckResult:
    if isinstance(protection, UnableToVerify):
        return PostureCheckResult(
            check_name="branch_protection",
            status="unknown",
            detail={"branch": coords.branch, "reason": protection.reason},
        )
    if protection is None:
        return PostureCheckResult(
            check_name="branch_protection",
            status="fail",
            detail={"branch": coords.branch, "reason": "no_protection_rule"},
        )
    return PostureCheckResult(
        check_name="branch_protection",
        status="pass",
        detail={"branch": coords.branch},
    )


def build_no_force_pushes_result(protection: ProtectionPayload) -> PostureCheckResult:
    if isinstance(protection, UnableToVerify):
        return PostureCheckResult(
            check_name="no_force_pushes",
            status="unknown",
            detail={"reason": protection.reason},
        )
    if protection is None:
        return PostureCheckResult(
            check_name="no_force_pushes",
            status="fail",
            detail={"reason": "no_protection_rule"},
        )
    force_setting = protection.get("allow_force_pushes")
    enabled = False
    if isinstance(force_setting, dict):
        enabled = bool(force_setting.get("enabled"))
    elif isinstance(force_setting, bool):
        enabled = force_setting
    return PostureCheckResult(
        check_name="no_force_pushes",
        status="fail" if enabled else "pass",
        detail={"allow_force_pushes": enabled},
    )


def build_signed_commits_result(commits: CommitsPayload) -> PostureCheckResult:
    if isinstance(commits, UnableToVerify):
        return PostureCheckResult(
            check_name="signed_commits",
            status="unknown",
            detail={"reason": commits.reason},
        )
    if not commits:
        return PostureCheckResult(
            check_name="signed_commits",
            status="advisory",
            detail={"reason": "no_commits_inspected"},
        )
    total = len(commits)
    signed = sum(1 for c in commits if _is_signed(c))
    # Mixed signing is advisory per IMPL-0002 (never a hard fail).
    status = "pass" if signed == total else "advisory"
    return PostureCheckResult(
        check_name="signed_commits",
        status=status,
        detail={"signed": signed, "total": total},
    )


def _is_signed(commit: dict[str, Any]) -> bool:
    commit_obj = commit.get("commit") or {}
    verification = commit_obj.get("verification") or {}
    return bool(verification.get("verified"))
