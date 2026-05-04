"""Phase 2 dashboard metrics (PRD-0006 / IMPL-0007 PR-B / B5).

Aggregates the trend / needs-you / severity-history fields layered onto the
existing ``GET /api/dashboard`` payload. Read-only — no schema changes.

Series convention: oldest-first, today is the last element. Series shorter
than the requested window pad with leading zeros (or ``None`` for
``grade_history``). Delta calculation guards against a zero baseline so the
wire never carries Infinity / NaN.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from opensec.db.repo_agent_run import list_latest_runs_by_workspace_ids
from opensec.db.repo_sidebar import list_sidebars_by_workspace_ids
from opensec.db.repo_workspace import list_workspaces_by_finding_ids
from opensec.models.issue_derivation import derive

if TYPE_CHECKING:
    import aiosqlite

    from opensec.models.finding import Finding


_TERMINAL_STATUSES = ("validated", "closed", "exception", "passed")
_VULN_TYPES = ("dependency", "code", "secret")
_SEVERITIES = ("critical", "high", "medium", "low")

GradeLetter = Literal["A", "B", "C", "D", "F"]


# --------------------------------------------------------------------- helpers


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _day_window(days: int, *, today: date | None = None) -> list[date]:
    """Return ``days`` consecutive dates ending at ``today`` (inclusive)."""
    end = today or _utc_today()
    return [end - timedelta(days=days - 1 - i) for i in range(days)]


def _parse_iso_to_dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _compute_delta_pct(current: float | None, baseline: float | None) -> int:
    """Signed integer percent change vs. baseline. 0 when baseline is 0/None."""
    if current is None or baseline is None or baseline == 0:
        return 0
    return round((current - baseline) / baseline * 100)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


# ----------------------------------------------------------- raw row queries


async def _open_vuln_rows(
    db: aiosqlite.Connection,
) -> list[tuple[str, str, str | None, str, str | None]]:
    """Return ``(id, status, normalized_priority, created_at, updated_at)``
    for every vuln finding.

    "Vuln" = ``type IN ('dependency','code','secret')`` (posture excluded —
    posture rows are scanner-truth, not user-lifecycle issues).
    """
    placeholders = ",".join("?" for _ in _VULN_TYPES)
    cursor = await db.execute(
        "SELECT id, status, normalized_priority, created_at, updated_at "  # noqa: S608
        f"FROM finding WHERE type IN ({placeholders})",
        _VULN_TYPES,
    )
    rows = await cursor.fetchall()
    return [
        (
            r["id"],
            r["status"],
            r["normalized_priority"],
            r["created_at"],
            r["updated_at"],
        )
        for r in rows
    ]


def _is_open_on(
    *,
    created_at: datetime | None,
    updated_at: datetime | None,
    status: str | None,
    day_end: datetime,
) -> bool:
    """A finding is open on ``day_end`` if it existed and was not yet terminal."""
    if created_at is None or created_at > day_end:
        return False
    # Closed before or on this day → not open. ``updated_at`` is the last
    # status flip; if it's <= day_end the closure has happened.
    return not (
        status in _TERMINAL_STATUSES
        and updated_at is not None
        and updated_at <= day_end
    )


# -------------------------------------------------------- series computations


async def open_issues_series(db: aiosqlite.Connection, *, days: int = 30) -> list[int]:
    """Daily count of open vuln findings, oldest -> newest, length == ``days``."""
    rows = await _open_vuln_rows(db)
    parsed = [
        (
            _parse_iso_to_dt(r[3]),  # created_at
            _parse_iso_to_dt(r[4]),  # updated_at
            r[1],  # status
        )
        for r in rows
    ]
    out: list[int] = []
    for d in _day_window(days):
        day_end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)
        out.append(
            sum(
                1
                for created_at, updated_at, status in parsed
                if _is_open_on(
                    created_at=created_at,
                    updated_at=updated_at,
                    status=status,
                    day_end=day_end,
                )
            )
        )
    return out


async def severity_history_series(
    db: aiosqlite.Connection, *, days: int = 60
) -> dict[str, list[int]]:
    """Daily severity-bucketed counts, four parallel arrays of length ``days``."""
    rows = await _open_vuln_rows(db)
    parsed = [
        (
            _parse_iso_to_dt(r[3]),
            _parse_iso_to_dt(r[4]),
            r[1],
            (r[2] or "").lower(),
        )
        for r in rows
    ]
    series: dict[str, list[int]] = {sev: [] for sev in _SEVERITIES}
    for d in _day_window(days):
        day_end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)
        per_day: dict[str, int] = {sev: 0 for sev in _SEVERITIES}
        for created_at, updated_at, status, sev in parsed:
            if sev not in per_day:
                continue
            if _is_open_on(
                created_at=created_at,
                updated_at=updated_at,
                status=status,
                day_end=day_end,
            ):
                per_day[sev] += 1
        for sev in _SEVERITIES:
            series[sev].append(per_day[sev])
    return series


async def time_to_close_p50_series(
    db: aiosqlite.Connection, *, days: int = 30
) -> list[int | None]:
    """Daily p50 time-to-close (seconds) over ``days`` days. None on empty days."""
    placeholders = ",".join("?" for _ in _VULN_TYPES)
    closed_set = ",".join(f"'{s}'" for s in _TERMINAL_STATUSES)
    cursor = await db.execute(
        # noqa: S608
        f"SELECT created_at, updated_at FROM finding "
        f"WHERE type IN ({placeholders}) AND status IN ({closed_set})",
        _VULN_TYPES,
    )
    rows = await cursor.fetchall()

    by_day: dict[date, list[float]] = {}
    for r in rows:
        created = _parse_iso_to_dt(r["created_at"])
        closed = _parse_iso_to_dt(r["updated_at"])
        if created is None or closed is None or closed < created:
            continue
        delta_seconds = (closed - created).total_seconds()
        by_day.setdefault(closed.date(), []).append(delta_seconds)

    out: list[int | None] = []
    for d in _day_window(days):
        med = _median(by_day.get(d, []))
        out.append(int(round(med)) if med is not None else None)
    return out


async def grade_history_series(
    db: aiosqlite.Connection, *, days: int = 90
) -> list[dict[str, str | None]]:
    """Daily grade snapshot. One letter per day = the latest completed
    assessment that day; ``None`` for days with no completed assessment.
    Returns ``[{"date": "YYYY-MM-DD", "grade": "A"|None}, ...]`` oldest-first.
    """
    cursor = await db.execute(
        "SELECT completed_at, grade FROM assessment "
        "WHERE status = 'complete' AND completed_at IS NOT NULL"
    )
    rows = await cursor.fetchall()

    by_day: dict[date, tuple[datetime, str | None]] = {}
    for r in rows:
        completed = _parse_iso_to_dt(r["completed_at"])
        grade = r["grade"]
        if completed is None:
            continue
        existing = by_day.get(completed.date())
        if existing is None or completed > existing[0]:
            by_day[completed.date()] = (completed, grade)

    out: list[dict[str, str | None]] = []
    for d in _day_window(days):
        cell = by_day.get(d)
        out.append({"date": d.isoformat(), "grade": cell[1] if cell else None})
    return out


# ------------------------------------------------------ needs_you snapshot


async def needs_you_counts(
    db: aiosqlite.Connection, *, findings: list[Finding] | None = None
) -> dict[str, int]:
    """Count plans_waiting / prs_ready / critical_todo across current findings.

    If ``findings`` is supplied (already-loaded list), reuse it to avoid a
    second pass; otherwise load all non-posture findings and derive per row.
    """
    if findings is None:
        from opensec.db.repo_finding import list_findings

        findings = await list_findings(
            db, type=list(_VULN_TYPES), limit=10_000
        )

    plans_waiting = 0
    prs_ready = 0
    critical_todo = 0

    for f in findings:
        derived = f.derived
        if derived is None:
            # Compose on-the-fly using the same derivation helpers that
            # ``_populate_derived`` uses; one call per finding.
            ws_map = await list_workspaces_by_finding_ids(db, [f.id])
            ws = ws_map.get(f.id)
            sidebar = None
            runs: dict[str, object] = {}
            if ws is not None:
                sidebars = await list_sidebars_by_workspace_ids(db, [ws.id])
                sidebar = sidebars.get(ws.id)
                runs_map = await list_latest_runs_by_workspace_ids(db, [ws.id])
                runs = runs_map.get(ws.id, {})
            derived = derive(f, workspace=ws, sidebar=sidebar, latest_runs_by_type=runs)  # type: ignore[arg-type]

        section = derived.section
        stage = derived.stage
        if section == "review" and stage == "plan_ready":
            plans_waiting += 1
        elif stage in ("pr_ready", "pr_awaiting_val"):
            prs_ready += 1
        elif (
            section == "todo"
            and (f.normalized_priority or "").lower() == "critical"
        ):
            critical_todo += 1

    return {
        "plans_waiting": plans_waiting,
        "prs_ready": prs_ready,
        "critical_todo": critical_todo,
    }


# ----------------------------------------------------- top-level aggregator


async def assemble_phase2_metrics(db: aiosqlite.Connection) -> dict[str, object]:
    """Compose the full Phase 2 add-on payload in one call.

    Returns a dict shaped to map directly onto the new ``DashboardPayload``
    fields:

        {
            "open_issues":     {current, history, delta_pct_30d},
            "time_to_close":   {current_seconds, history, delta_pct_30d},
            "needs_you":       {plans_waiting, prs_ready, critical_todo},
            "grade_history":   [{date, grade}, ...],   # 90 entries
            "severity_history":{critical:[...], high:[...], medium:[...], low:[...]},
        }
    """
    open_history = await open_issues_series(db, days=30)
    ttc_history = await time_to_close_p50_series(db, days=30)
    grade_history = await grade_history_series(db, days=90)
    severity = await severity_history_series(db, days=60)
    needs_you = await needs_you_counts(db)

    open_current = open_history[-1] if open_history else 0
    open_baseline = open_history[0] if open_history else 0

    ttc_current = ttc_history[-1] if ttc_history else None
    # Baseline for ttc: first non-None entry in the window (or today's value
    # itself when only today has data — yields delta 0, which is the contract).
    ttc_baseline = next(
        (v for v in ttc_history if v is not None), None
    )
    if ttc_baseline == ttc_current:
        ttc_baseline = None

    return {
        "open_issues": {
            "current": open_current,
            "history": open_history,
            "delta_pct_30d": _compute_delta_pct(open_current, open_baseline),
        },
        "time_to_close": {
            "current_seconds": ttc_current,
            "history": ttc_history,
            "delta_pct_30d": _compute_delta_pct(ttc_current, ttc_baseline),
        },
        "needs_you": needs_you,
        "grade_history": grade_history,
        "severity_history": severity,
    }
