"""``derive_level_up`` — pure-function driver for the dashboard's Level-up panel.

The Dashboard's Level-up panel surfaces a real, actionable path to the next
grade. This module turns the current grade + criteria snapshot + open findings
+ posture results into a small set of gates the user can click through.

It is intentionally a pure function: no DB, no network, no Pydantic validation
of inputs (callers pass already-validated models). The shape is locked by
``LevelUp`` / ``LevelUpGate`` and the OpenAPI snapshot.

Status priority (first match wins per gate):

1. ``ready_to_review`` — at least one matching finding is in
   ``derived.section='review'`` with ``stage='plan_ready'``.
2. ``pr_ready`` — at least one matching finding is in ``review`` with
   ``stage in {pr_ready, pr_awaiting_val}``.
3. ``in_progress`` — at least one matching finding is in
   ``derived.section='in_progress'``.
4. ``todo`` — none of the above; the gate is unstarted work.

The posture aggregate gate is special: it bundles every unmet posture
criterion. ``status='auto_fixable'`` if at least one unmet check is in
the auto-fixable set; else ``todo``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

# Pydantic resolves model annotations at validation time, so ``Grade`` must
# be importable at runtime — the literal alias is cheap and side-effect free.
from cliff.models.assessment import Grade

if TYPE_CHECKING:
    from cliff.models.assessment import CriteriaSnapshot
    from cliff.models.finding import Finding


# ─── public types ───────────────────────────────────────────────────────────

LevelUpGateStatus = Literal[
    "ready_to_review",
    "pr_ready",
    "in_progress",
    "auto_fixable",
    "todo",
]


class LevelUpGate(BaseModel):
    id: str
    label: str
    detail: str
    current: int
    target: int
    unit: str
    status: LevelUpGateStatus
    action_label: str
    action_href: str
    # Only populated when ``status='auto_fixable'`` so the frontend can fan
    # out parallel ``POST /api/posture/fix/{check_name}`` calls.
    auto_fixable_check_names: list[str] = Field(default_factory=list)
    # B27 — when a non-posture gate has at least one matching finding,
    # we surface its id so the dashboard's "Start" card can deep-link the
    # Issues side panel via ``?open=<id>``. Always ``None`` for the
    # posture aggregate gate (which is category-level by design).
    first_finding_id: str | None = None


class LevelUp(BaseModel):
    current: Grade
    next: Grade | None = None
    summary: str
    gates: list[LevelUpGate] = Field(default_factory=list)


# ─── derivation ─────────────────────────────────────────────────────────────


_NEXT_GRADE: dict[str, str | None] = {
    "F": "D",
    "D": "C",
    "C": "B",
    "B": "A",
    "A": None,
}

# Posture criteria fields on CriteriaSnapshot that map to known check names
# the auto-fix surface can address. Order is the sort order for tie-breaking.
#
# Q01R B24 — this tuple MUST stay a subset of ``PostureFixCheckName`` in
# ``cliff.api.routes.posture``. Advertising a check here that the route
# rejects with 422 produces a dead button on the dashboard's most prominent
# CTA — exactly the bug Q01R-B24 caught. ``code_owners_exists`` and
# ``actions_pinned_to_sha`` were removed in IMPL-0013 because no agent
# template / ``WorkspaceKind`` ships for them yet; they live in BACKLOG as
# follow-up items and may be re-added once the backend handlers land
# (template + ``WorkspaceKind`` + ``_CHECK_TO_WORKSPACE_KIND`` entry +
# ``PostureFixCheckName`` Literal extension, all in one PR).
_AUTO_FIXABLE_CHECKS: tuple[str, ...] = (
    "security_md",
    "dependabot_config",
)

# Map criteria-snapshot field → (canonical check name, display name).
_POSTURE_CRITERIA: tuple[tuple[str, str, str], ...] = (
    ("security_md_present", "security_md", "SECURITY.md"),
    ("dependabot_present", "dependabot_config", "Dependabot config"),
    ("branch_protection_enabled", "branch_protection", "branch protection"),
    ("actions_pinned_to_sha", "actions_pinned_to_sha", "actions pinned to SHA"),
    ("no_stale_collaborators", "stale_collaborators", "no stale collaborators"),
    ("code_owners_exists", "code_owners_exists", "CODEOWNERS"),
    ("secret_scanning_enabled", "secret_scanning_enabled", "secret scanning"),
)


_HIGH_TARGET = 3

# Ordering used for capping at 4 (cheapest first → most expensive last).
_STATUS_RANK: dict[LevelUpGateStatus, int] = {
    "auto_fixable": 0,
    "pr_ready": 1,
    "ready_to_review": 2,
    "in_progress": 3,
    "todo": 4,
}


def derive_level_up(
    grade: Grade | None,
    criteria_snapshot: CriteriaSnapshot | None,
    open_findings: list[Finding],
    posture_findings: list[Finding],
) -> LevelUp | None:
    """Build the LevelUp payload for the dashboard's Level-up panel.

    Returns ``None`` when no grade exists yet (first scan still pending).
    """
    if grade is None:
        return None

    next_grade = _NEXT_GRADE.get(grade)
    if next_grade is None:
        # Already at A — nothing to level up to.
        return LevelUp(
            current=grade,
            next=None,
            summary="You're an A. Hold the line.",
            gates=[],
        )

    snap = criteria_snapshot
    gates: list[LevelUpGate] = []

    # ── finding-based gates ──────────────────────────────────────────────
    if snap is None or snap.no_critical_vulns is not True:
        criticals = _findings_by_severity(open_findings, "critical")
        gate = _critical_gate(criticals)
        if gate is not None:
            gates.append(gate)

    if snap is None or snap.no_high_vulns is not True:
        highs = _findings_by_severity(open_findings, "high")
        if len(highs) > _HIGH_TARGET:
            gates.append(_high_gate(highs))

    if snap is None or snap.no_secrets_detected is not True:
        secrets = [
            f for f in open_findings if f.type == "secret"
        ]
        if secrets:
            gates.append(_secret_gate(secrets))

    # ── posture aggregate gate ───────────────────────────────────────────
    if snap is not None:
        unmet_checks = _unmet_posture_check_names(snap)
        if unmet_checks:
            gates.append(_posture_gate(snap, unmet_checks, posture_findings))

    # ── cap at 4, cheapest first ─────────────────────────────────────────
    gates.sort(key=lambda g: _STATUS_RANK.get(g.status, 99))
    gates = gates[:4]

    return LevelUp(
        current=grade,
        next=next_grade,  # type: ignore[arg-type]
        summary=_compose_summary(gates, next_grade=next_grade),
        gates=gates,
    )


# ─── helpers ────────────────────────────────────────────────────────────────


def _findings_by_severity(items: list[Finding], severity: str) -> list[Finding]:
    return [f for f in items if (f.normalized_priority or "").lower() == severity]


def _resolve_status_for_findings(
    items: list[Finding],
) -> tuple[LevelUpGateStatus, str, str | None]:
    """Return ``(status, action_href, first_finding_id)`` for a finding-based gate.

    Picks the most-progressed matching finding (review > in_progress > todo).
    The third tuple element is the id of the picked finding so the gate
    builder can both propagate it as ``first_finding_id`` AND ensure the
    href deep-links the side panel via ``?open=<id>`` (B27 — previously the
    in_progress / todo branches navigated to the page without opening the
    panel).
    """
    # ready_to_review has highest priority because the user is being asked to
    # do something concrete on a specific finding.
    for f in items:
        if (
            f.derived
            and f.derived.section == "review"
            and f.derived.stage == "plan_ready"
        ):
            return "ready_to_review", f"/issues?open={f.id}", f.id
    for f in items:
        if (
            f.derived
            and f.derived.section == "review"
            and f.derived.stage in {"pr_ready", "pr_awaiting_val"}
        ):
            return "pr_ready", f"/issues?open={f.id}", f.id
    for f in items:
        if f.derived and f.derived.section == "in_progress":
            return "in_progress", f"/issues?section=review&open={f.id}", f.id
    if items:
        head = items[0]
        return "todo", _append_open_param(_todo_href_for(head), head.id), head.id
    return "todo", "/issues", None


def _append_open_param(href: str, finding_id: str) -> str:
    """Append ``open=<id>`` to *href* using the right separator."""
    sep = "&" if "?" in href else "?"
    return f"{href}{sep}open={finding_id}"


def _todo_href_for(finding: Finding) -> str:
    sev = (finding.normalized_priority or "").lower()
    return f"/issues?section=todo&severity={sev}" if sev else "/issues?section=todo"


def _action_label(status: LevelUpGateStatus, *, fixable: int = 0, total: int = 0) -> str:
    if status == "ready_to_review":
        return "Review plan"
    if status == "pr_ready":
        return "Open PR"
    if status == "in_progress":
        return "Open Review"
    if status == "auto_fixable":
        # "Auto-fix N of M" reads as partial ("we'll fix N of the M you
        # need"). It actually means "N are auto-fixable; the other M-N
        # require manual work." Phrase variants reflect that.
        if fixable == 0:
            return "Auto-fix"
        if fixable == total:
            return "Auto-fix all" if fixable > 1 else "Auto-fix it"
        if fixable == 1:
            return f"Auto-fix 1 (of {total} open)"
        return f"Auto-fix {fixable} (of {total} open)"
    return "Start"


def _critical_gate(criticals: list[Finding]) -> LevelUpGate | None:
    if not criticals:
        return None
    n = len(criticals)
    label = (
        "Close the open Critical"
        if n == 1
        else f"Close the {n} open Criticals"
    )
    status, href, first_id = _resolve_status_for_findings(criticals)
    detail = _detail_for_findings(criticals, fallback="open critical")
    return LevelUpGate(
        id="criticals_open",
        label=label,
        detail=detail,
        current=n,
        target=0,
        unit="critical",
        status=status,
        action_label=_action_label(status),
        action_href=href,
        first_finding_id=first_id,
    )


def _high_gate(highs: list[Finding]) -> LevelUpGate:
    n = len(highs)
    status, href, first_id = _resolve_status_for_findings(highs)
    detail = _detail_for_findings(highs, fallback=f"{n} open · {n - _HIGH_TARGET} over target")
    return LevelUpGate(
        id="highs_over_target",
        label="Bring High findings to ≤ 3",
        detail=detail,
        current=n,
        target=_HIGH_TARGET,
        unit="high findings",
        status=status,
        action_label=_action_label(status),
        action_href=href,
        first_finding_id=first_id,
    )


def _secret_gate(secrets: list[Finding]) -> LevelUpGate:
    n = len(secrets)
    label = (
        "Resolve the committed secret"
        if n == 1
        else f"Resolve {n} committed secrets"
    )
    status, href, first_id = _resolve_status_for_findings(secrets)
    detail = _detail_for_findings(secrets, fallback="committed secret")
    return LevelUpGate(
        id="secrets_open",
        label=label,
        detail=detail,
        current=n,
        target=0,
        unit="secret" if n == 1 else "secrets",
        status=status,
        action_label=_action_label(status),
        action_href=href,
        first_finding_id=first_id,
    )


def _posture_gate(
    snap: CriteriaSnapshot,
    unmet_checks: list[str],
    posture_findings: list[Finding],
) -> LevelUpGate:
    fixable = [c for c in unmet_checks if c in _AUTO_FIXABLE_CHECKS]
    status: LevelUpGateStatus = "auto_fixable" if fixable else "todo"
    total_unmet = len(unmet_checks)
    action = _action_label(status, fixable=len(fixable), total=total_unmet)
    detail = ", ".join(unmet_checks[:3]) if unmet_checks else "remaining posture checks"
    return LevelUpGate(
        id="posture_remaining",
        label="Pass remaining posture checks",
        detail=detail,
        current=snap.posture_checks_passing,
        target=snap.posture_checks_total,
        unit="posture checks",
        status=status,
        action_label=action,
        action_href="/issues?type=posture",
        auto_fixable_check_names=fixable,
    )


def _unmet_posture_check_names(snap: CriteriaSnapshot) -> list[str]:
    """Return the canonical posture-check names whose criteria are unmet."""
    snap_dump = snap.model_dump()
    out: list[str] = []
    for field, check_name, _display in _POSTURE_CRITERIA:
        if snap_dump.get(field) is not True:
            out.append(check_name)
    return out


def _detail_for_findings(items: list[Finding], *, fallback: str) -> str:
    """Pick the detail line — first finding's title with stage hint when useful."""
    if not items:
        return fallback
    head = items[0]
    title = head.title or fallback
    if head.derived and head.derived.section == "review":
        if head.derived.stage == "plan_ready":
            return f"{title} · plan ready for your review"
        if head.derived.stage in {"pr_ready", "pr_awaiting_val"}:
            return f"{title} · PR ready"
    if head.derived and head.derived.section == "in_progress":
        return f"{title} · agents working"
    return title


def _grade_article(grade: str) -> str:
    """Indefinite article for a grade letter.

    Only A, E, F start with a vowel sound. Defaults to "a" for unknown
    letters so future grade tokens don't regress.
    """
    return "an" if grade in {"A", "E", "F"} else "a"


def _compose_summary(gates: list[LevelUpGate], *, next_grade: str) -> str:
    if not gates:
        return f"You're already meeting the bar for {next_grade}. Hold the line."
    n = len(gates)
    things = "thing" if n == 1 else "things"
    article = _grade_article(next_grade)
    base = f"{_humanize_count(n)} {things} between you and {article} {next_grade}."
    one_click = sum(
        1 for g in gates if g.status in {"auto_fixable", "pr_ready"}
    )
    if one_click >= 1:
        word = _humanize_count(one_click)
        verb = "is" if one_click == 1 else "are"
        return f"{base} {word} {verb} one-click."
    return base


_NUM_WORDS = {
    1: "One",
    2: "Two",
    3: "Three",
    4: "Four",
}


def _humanize_count(n: int) -> str:
    return _NUM_WORDS.get(n, str(n))


__all__ = [
    "LevelUp",
    "LevelUpGate",
    "LevelUpGateStatus",
    "derive_level_up",
]
