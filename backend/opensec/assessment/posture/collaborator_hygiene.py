"""Collaborator-hygiene posture checks (PRD-0003 v0.2).

These three checks rely on GitHub REST endpoints that most personal access
tokens cannot reach (``GET /repos/{owner}/{repo}/collaborators`` requires push
or admin scope). The orchestrator calls ``getattr`` for each method so the
checks degrade to ``status='unknown'`` when the underlying client can't
satisfy them — the dashboard projects ``unknown`` to the API ``advisory``
state with the reason from ``detail``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from opensec.assessment.posture import PostureCheckResult
from opensec.assessment.posture.github_client import UnableToVerify

if TYPE_CHECKING:
    from opensec.assessment.posture import GithubAPI, RepoCoords

# 90-day cutoff for stale collaborators per PRD-0003 v0.2 (fixed, not configurable).
STALE_DAYS = 90


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _try_call(client: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    fn = getattr(client, method, None)
    if fn is None:
        return UnableToVerify(reason="client_unsupported")
    return await fn(*args, **kwargs)


async def check_stale_collaborators(
    gh_client: GithubAPI, coords: RepoCoords
) -> PostureCheckResult:
    """Flag collaborators with write/admin access who haven't acted in 90+ days."""
    collabs = await _try_call(
        gh_client, "list_collaborators", coords.owner, coords.repo
    )
    if isinstance(collabs, UnableToVerify):
        return PostureCheckResult(
            check_name="stale_collaborators",
            status="unknown",
            detail={"reason": collabs.reason},
        )
    if not isinstance(collabs, list):
        return PostureCheckResult(
            check_name="stale_collaborators",
            status="unknown",
            detail={"reason": "unexpected_body"},
        )
    # GitHub's GET /repos/{owner}/{repo}/collaborators does NOT return a
    # ``last_active`` / ``last_activity_at`` field on the User object — those
    # keys are not part of the REST API. Without per-user activity data we
    # cannot make a real stale-vs-active determination. Earlier versions of
    # this check treated the missing field as evidence of staleness and
    # marked every collaborator as stale, producing a false fail on every
    # repo. Degrade to ``unknown`` instead so the dashboard renders the
    # tri-state ``?`` and the user sees an honest "we couldn't check" rather
    # than a phantom failure.
    cutoff = _now()
    eligible = [
        entry
        for entry in collabs
        if isinstance(entry, dict)
        and (
            (entry.get("permissions") or {}).get("push")
            or (entry.get("permissions") or {}).get("admin")
        )
    ]
    # No push/admin collaborators → nothing to be stale; treat as pass so
    # repos with read-only outside contributors don't grade-down on this.
    if not eligible:
        return PostureCheckResult(
            check_name="stale_collaborators",
            status="pass",
            detail={"checked": len(collabs), "threshold_days": STALE_DAYS},
        )
    has_last_active = any(
        entry.get("last_active") or entry.get("last_activity_at") for entry in eligible
    )
    if not has_last_active:
        return PostureCheckResult(
            check_name="stale_collaborators",
            status="unknown",
            detail={
                "reason": "no_last_active_field",
                "checked": len(collabs),
                "threshold_days": STALE_DAYS,
                "note": (
                    "GitHub's collaborators endpoint doesn't return last-active "
                    "data; per-user activity must be derived from a separate "
                    "endpoint we don't query here. Treat as unverified."
                ),
            },
        )
    stale: list[dict[str, Any]] = []
    for entry in eligible:
        last_active_str = entry.get("last_active") or entry.get("last_activity_at") or ""
        last_active = _parse_iso(last_active_str) if last_active_str else None
        if last_active is None:
            # Keep the collaborator out of the stale list when we lack data
            # for them specifically — this avoids the all-or-nothing trap of
            # the previous implementation while still surfacing collaborators
            # whose last-active timestamp is genuinely past the cutoff.
            continue
        days = (cutoff - last_active).days
        if days >= STALE_DAYS:
            stale.append(
                {
                    "login": entry.get("login"),
                    "last_active": last_active_str,
                    "days_since": days,
                }
            )
    if not stale:
        return PostureCheckResult(
            check_name="stale_collaborators",
            status="pass",
            detail={"checked": len(collabs), "threshold_days": STALE_DAYS},
        )
    return PostureCheckResult(
        check_name="stale_collaborators",
        status="fail",
        detail={
            "stale_count": len(stale),
            "threshold_days": STALE_DAYS,
            "stale": stale[:20],
        },
    )


async def check_broad_team_permissions(
    gh_client: GithubAPI, coords: RepoCoords
) -> PostureCheckResult:
    """Advisory: teams with write access and >20 members are an exposure risk."""
    teams = await _try_call(gh_client, "list_repo_teams", coords.owner, coords.repo)
    if isinstance(teams, UnableToVerify):
        return PostureCheckResult(
            check_name="broad_team_permissions",
            status="unknown",
            detail={"reason": teams.reason},
        )
    if not isinstance(teams, list):
        return PostureCheckResult(
            check_name="broad_team_permissions",
            status="unknown",
            detail={"reason": "unexpected_body"},
        )
    flagged = [
        {
            "slug": t.get("slug"),
            "permission": t.get("permission"),
            "members_count": t.get("members_count"),
        }
        for t in teams
        if isinstance(t, dict)
        and t.get("permission") in {"push", "admin", "maintain"}
        and isinstance(t.get("members_count"), int)
        and t["members_count"] > 20
    ]
    return PostureCheckResult(
        check_name="broad_team_permissions",
        status="advisory",
        detail={"flagged_count": len(flagged), "flagged": flagged[:10]},
    )


async def check_default_branch_permissions(
    gh_client: GithubAPI, coords: RepoCoords
) -> PostureCheckResult:
    """Combine repo settings + branch protection to verify default-branch hygiene.

    Considered passing when (a) we can read the default branch, and (b) it has a
    protection rule (the existing ``branch_protection`` check enforces detail).
    """
    info = await _try_call(gh_client, "get_repo_info", coords.owner, coords.repo)
    if isinstance(info, UnableToVerify):
        return PostureCheckResult(
            check_name="default_branch_permissions",
            status="unknown",
            detail={"reason": info.reason},
        )
    if not isinstance(info, dict):
        return PostureCheckResult(
            check_name="default_branch_permissions",
            status="unknown",
            detail={"reason": "unexpected_body"},
        )
    default_branch = info.get("default_branch") or coords.branch
    protection = await _try_call(
        gh_client, "get_branch_protection", coords.owner, coords.repo, default_branch
    )
    if isinstance(protection, UnableToVerify):
        return PostureCheckResult(
            check_name="default_branch_permissions",
            status="unknown",
            detail={"reason": protection.reason, "branch": default_branch},
        )
    if protection is None:
        return PostureCheckResult(
            check_name="default_branch_permissions",
            status="fail",
            detail={"branch": default_branch, "reason": "no_protection_rule"},
        )
    return PostureCheckResult(
        check_name="default_branch_permissions",
        status="pass",
        detail={"branch": default_branch},
    )
