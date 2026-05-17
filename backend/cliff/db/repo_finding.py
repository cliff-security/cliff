"""Repository functions for the unified ``finding`` entity (ADR-0027).

Phase 2 of IMPL-0003-p2 collapses the legacy ``posture_check`` table into the
single ``finding`` table with a typed ``type`` column. Persistence happens via
an UPSERT keyed on ``(source_type, source_id)`` so re-running an assessment
refreshes scanner truth without losing user lifecycle state.

Type-conditional preservation rule (CEO direction, 2026-04-26):

* For ``type='posture'``: ``status`` is REFRESHED on conflict — the scanner
  is the source of truth for whether a posture check is currently passing,
  and there's no user lifecycle on a passing check. Other preserved columns
  (``id``, ``created_at``, ``likely_owner``, ``plain_description``,
  ``why_this_matters``, ``pr_url``) still survive the UPSERT.
* For all other types: ``status`` is PRESERVED — re-running Trivy must not
  reset a finding the user marked ``triaged`` or ``in_progress``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.models import Finding, FindingCreate, FindingUpdate
from cliff.models.issue_derivation import derive

if TYPE_CHECKING:
    from collections.abc import Iterable

    import aiosqlite

logger = logging.getLogger(__name__)

# Wire-shape "user lifecycle" preserved statuses for non-posture findings.
_USER_LIFECYCLE_STATUSES = (
    "triaged",
    "in_progress",
    "remediated",
    "validated",
    "closed",
    "exception",
)


def _row_to_finding(row: aiosqlite.Row) -> Finding:
    return Finding(
        id=row["id"],
        source_type=row["source_type"],
        source_id=row["source_id"],
        title=row["title"],
        description=row["description"],
        plain_description=row["plain_description"],
        raw_severity=row["raw_severity"],
        normalized_priority=row["normalized_priority"],
        asset_id=row["asset_id"],
        asset_label=row["asset_label"],
        status=row["status"],
        likely_owner=row["likely_owner"],
        why_this_matters=row["why_this_matters"],
        raw_payload=json.loads(row["raw_payload"]) if row["raw_payload"] else None,
        type=row["type"],
        grade_impact=row["grade_impact"],
        category=row["category"],
        assessment_id=row["assessment_id"],
        pr_url=row["pr_url"],
        exception_reason=row["exception_reason"],
        exception_note=row["exception_note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_finding(db: aiosqlite.Connection, data: FindingCreate) -> Finding:
    """UPSERT on ``(source_type, source_id)`` with type-conditional preservation.

    See module docstring + IMPL-0003-p2 §"UPSERT preservation table".
    """
    finding_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    if data.type == "posture":
        status_clause = "status = excluded.status"
    else:
        # Preserve any user-lifecycle status; only let the scanner overwrite
        # the default 'new' state.
        status_clause = (
            "status = CASE "
            "WHEN finding.status IN ("
            + ",".join(f"'{s}'" for s in _USER_LIFECYCLE_STATUSES)
            + ") THEN finding.status "
            "ELSE excluded.status END"
        )

    sql = f"""
        INSERT INTO finding (
            id, source_type, source_id, type, grade_impact, category,
            assessment_id, title, description, plain_description,
            raw_severity, normalized_priority, status, likely_owner,
            why_this_matters, asset_id, asset_label, raw_payload, pr_url,
            exception_reason, exception_note,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_type, source_id) DO UPDATE SET
            title               = excluded.title,
            description         = excluded.description,
            raw_severity        = excluded.raw_severity,
            normalized_priority = excluded.normalized_priority,
            raw_payload         = excluded.raw_payload,
            type                = excluded.type,
            grade_impact        = excluded.grade_impact,
            category            = excluded.category,
            assessment_id       = excluded.assessment_id,
            asset_id            = excluded.asset_id,
            asset_label         = excluded.asset_label,
            updated_at          = excluded.updated_at,
            {status_clause}
    """  # noqa: S608

    await db.execute(
        sql,
        (
            finding_id,
            data.source_type,
            data.source_id,
            data.type,
            data.grade_impact,
            data.category,
            data.assessment_id,
            data.title,
            data.description,
            data.plain_description,
            data.raw_severity,
            data.normalized_priority,
            data.status,
            data.likely_owner,
            data.why_this_matters,
            data.asset_id,
            data.asset_label,
            json.dumps(data.raw_payload) if data.raw_payload is not None else None,
            data.pr_url,
            data.exception_reason,
            data.exception_note,
            now,
            now,
        ),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT * FROM finding WHERE source_type = ? AND source_id = ?",
        (data.source_type, data.source_id),
    )
    row = await cursor.fetchone()
    assert row is not None
    return _row_to_finding(row)


async def _populate_derived(
    db: aiosqlite.Connection, findings: list[Finding]
) -> list[Finding]:
    """Compose ``Finding.derived`` for every row in one batched join.

    Issues at most 3 extra SELECTs (workspaces, agent_runs, sidebars) regardless
    of ``len(findings)``. The N+1 guard test in
    ``tests/db/test_repo_finding_derived.py`` enforces this.
    """
    if not findings:
        return findings

    from cliff.db.repo_agent_run import list_latest_runs_by_workspace_ids
    from cliff.db.repo_sidebar import list_sidebars_by_workspace_ids
    from cliff.db.repo_workspace import list_workspaces_by_finding_ids

    workspaces_by_finding = await list_workspaces_by_finding_ids(
        db, [f.id for f in findings]
    )
    workspace_ids = [ws.id for ws in workspaces_by_finding.values()]
    runs_by_ws = await list_latest_runs_by_workspace_ids(db, workspace_ids)
    sidebars_by_ws = await list_sidebars_by_workspace_ids(db, workspace_ids)

    enriched: list[Finding] = []
    for f in findings:
        ws = workspaces_by_finding.get(f.id)
        sidebar = sidebars_by_ws.get(ws.id) if ws else None
        runs = runs_by_ws.get(ws.id, {}) if ws else {}
        enriched.append(
            f.model_copy(
                update={
                    "derived": derive(
                        f, workspace=ws, sidebar=sidebar, latest_runs_by_type=runs
                    )
                }
            )
        )
    return enriched


async def get_finding(db: aiosqlite.Connection, finding_id: str) -> Finding | None:
    cursor = await db.execute("SELECT * FROM finding WHERE id = ?", (finding_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    finding = _row_to_finding(row)
    enriched = await _populate_derived(db, [finding])
    return enriched[0]


async def list_findings(
    db: aiosqlite.Connection,
    *,
    status: str | None = None,
    has_workspace: bool | None = None,
    source_type: str | None = None,
    type: str | list[str] | None = None,
    grade_impact: str | None = None,
    assessment_id: str | None = None,
    created_since_iso: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Finding]:
    """List findings, with v0.2 ``type`` / ``grade_impact`` / ``assessment_id`` filters."""
    conditions: list[str] = []
    params: list[str | int] = []

    if status:
        conditions.append("f.status = ?")
        params.append(status)

    if source_type is not None:
        conditions.append("f.source_type = ?")
        params.append(source_type)

    if type is not None:
        if isinstance(type, str):
            conditions.append("f.type = ?")
            params.append(type)
        else:
            placeholders = ",".join("?" for _ in type)
            conditions.append(f"f.type IN ({placeholders})")
            params.extend(type)

    if grade_impact is not None:
        conditions.append("f.grade_impact = ?")
        params.append(grade_impact)

    if assessment_id is not None:
        conditions.append("f.assessment_id = ?")
        params.append(assessment_id)

    if created_since_iso is not None:
        conditions.append("f.created_at >= ?")
        params.append(created_since_iso)

    if has_workspace is True:
        conditions.append(
            "EXISTS (SELECT 1 FROM workspace w WHERE w.finding_id = f.id)"
        )
    elif has_workspace is False:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM workspace w WHERE w.finding_id = f.id)"
        )

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])
    cursor = await db.execute(
        f"SELECT f.* FROM finding f {where}"  # noqa: S608
        " ORDER BY f.updated_at DESC LIMIT ? OFFSET ?",
        params,
    )
    findings = [_row_to_finding(row) for row in await cursor.fetchall()]
    return await _populate_derived(db, findings)


async def list_posture_findings(
    db: aiosqlite.Connection, assessment_id: str
) -> list[Finding]:
    """All posture rows for one assessment (pass + fail + advisory)."""
    cursor = await db.execute(
        """
        SELECT f.* FROM finding f
        WHERE f.type = 'posture' AND f.assessment_id = ?
        ORDER BY f.created_at ASC, f.id ASC
        """,
        (assessment_id,),
    )
    return [_row_to_finding(row) for row in await cursor.fetchall()]


async def mark_started_on_workspace_create(
    db: aiosqlite.Connection, finding_id: str
) -> bool:
    """Flip ``Finding.status`` from ``new`` / ``triaged`` → ``in_progress``.

    Called by ``context_builder.create_workspace`` so the user's click on
    "Start" immediately moves the row out of Todo (PRD-0006 Story 2). Other
    statuses (``in_progress`` / ``remediated`` / ``validated`` / ``closed`` /
    ``exception`` / ``passed``) are left untouched — re-creating a workspace
    on a closed finding must not silently re-open it.

    Returns ``True`` if a row was updated, ``False`` otherwise.
    """
    now_iso = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        "UPDATE finding SET status = 'in_progress', updated_at = ?"
        " WHERE id = ? AND status IN ('new', 'triaged')",
        (now_iso, finding_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def mark_resolved_on_workspace_close(
    db: aiosqlite.Connection,
    finding_id: str,
    *,
    workspace_id: str | None = None,
) -> bool:
    """Flip ``Finding.status`` to ``validated`` when the user resolves a workspace.

    Called when a workspace transitions to ``state='closed'`` so the linked
    finding visibly moves into the Done section of the Issues page (PRD-0006
    Story 5; Phase 1 stand-in for the validator until webhook-driven
    auto-validation lands).

    When ``workspace_id`` is provided, additionally reconcile ``Finding.pr_url``
    from the most recent successful ``remediation_executor`` run for that
    workspace (EF-B14). The executor's pr_url already survives in
    ``AgentRun.structured_output`` and ``SidebarState.pull_request`` but was
    never persisted onto the Finding row itself — so the dashboard would
    silently close a finding while leaving the actual PR orphaned.

    Idempotent — only flips findings that are mid-flight
    (``new`` / ``triaged`` / ``in_progress`` / ``remediated``). Already-
    terminal statuses (``validated`` / ``closed`` / ``exception`` / ``passed``)
    are left untouched, so re-resolving a workspace can't silently overwrite a
    user's prior False-positive / Won't-fix decision. ``pr_url`` reconciliation
    only overwrites when the existing value is null, so an explicit
    ``PATCH /findings/{id}`` with a user-supplied ``pr_url`` is never clobbered.

    Returns ``True`` if a row was updated, ``False`` otherwise.
    """
    reconciled_pr_url: str | None = None
    if workspace_id is not None:
        reconciled_pr_url = await _reconcile_pr_url_from_runs(
            db, finding_id=finding_id, workspace_id=workspace_id
        )

    now_iso = datetime.now(UTC).isoformat()
    if reconciled_pr_url is not None:
        cursor = await db.execute(
            "UPDATE finding SET status = 'validated', pr_url = ?, updated_at = ?"
            " WHERE id = ? AND status IN ('new', 'triaged', 'in_progress', 'remediated')",
            (reconciled_pr_url, now_iso, finding_id),
        )
    else:
        cursor = await db.execute(
            "UPDATE finding SET status = 'validated', updated_at = ?"
            " WHERE id = ? AND status IN ('new', 'triaged', 'in_progress', 'remediated')",
            (now_iso, finding_id),
        )
    await db.commit()
    return cursor.rowcount > 0


async def _reconcile_pr_url_from_runs(
    db: aiosqlite.Connection, *, finding_id: str, workspace_id: str
) -> str | None:
    """Pull pr_url off the latest successful ``remediation_executor`` run.

    Returns the URL to write onto the Finding, or ``None`` if (a) the Finding
    already has a pr_url (we don't overwrite user-supplied values) or (b) no
    executor run carrying a usable pr_url exists. In the second case, if any
    executor run exists at all, logs a WARNING so reviewers can spot the
    fsevents-style "PR opened on GitHub but lost to a timeout" residual.
    """
    existing = await get_finding(db, finding_id)
    if existing is None or existing.pr_url:
        return None

    # Lazy import to avoid widening repo_finding's module-level deps.
    from cliff.db.repo_agent_run import list_agent_runs

    runs = await list_agent_runs(db, workspace_id, limit=50)
    executor_runs = [r for r in runs if r.agent_type == "remediation_executor"]
    if not executor_runs:
        return None

    # list_agent_runs returns newest-first.
    for run in executor_runs:
        structured = run.structured_output or {}
        candidate = structured.get("pr_url") if isinstance(structured, dict) else None
        if candidate:
            return candidate

    logger.warning(
        "EF-B14: finding=%s workspace=%s — executor ran %d time(s) but "
        "pr_url could not be reconciled from any AgentRun.structured_output. "
        "An orphaned PR may exist on GitHub; please verify before closing.",
        finding_id,
        workspace_id,
        len(executor_runs),
    )
    return None


async def update_finding(
    db: aiosqlite.Connection, finding_id: str, data: FindingUpdate
) -> Finding | None:
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        return await get_finding(db, finding_id)

    if "raw_payload" in fields and fields["raw_payload"] is not None:
        fields["raw_payload"] = json.dumps(fields["raw_payload"])

    fields["updated_at"] = datetime.now(UTC).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), finding_id]

    await db.execute(f"UPDATE finding SET {set_clause} WHERE id = ?", values)  # noqa: S608
    await db.commit()
    return await get_finding(db, finding_id)


async def delete_finding(db: aiosqlite.Connection, finding_id: str) -> bool:
    cursor = await db.execute("DELETE FROM finding WHERE id = ?", (finding_id,))
    await db.commit()
    return cursor.rowcount > 0


async def count_findings_by_priority(
    db: aiosqlite.Connection,
    *,
    source_type: str | None = None,
    type: str | None = None,
    assessment_id: str | None = None,
    created_since_iso: str | None = None,
) -> dict[str, int]:
    """Return ``{priority: count}`` for findings with a non-null priority."""
    conditions: list[str] = ["normalized_priority IS NOT NULL"]
    params: list[str] = []
    if source_type is not None:
        conditions.append("source_type = ?")
        params.append(source_type)
    if type is not None:
        conditions.append("type = ?")
        params.append(type)
    if assessment_id is not None:
        conditions.append("assessment_id = ?")
        params.append(assessment_id)
    if created_since_iso is not None:
        conditions.append("created_at >= ?")
        params.append(created_since_iso)
    where = " AND ".join(conditions)
    cursor = await db.execute(
        f"""
        SELECT normalized_priority, COUNT(*) AS n
          FROM finding
         WHERE {where}
         GROUP BY normalized_priority
        """,  # noqa: S608
        params,
    )
    return {row["normalized_priority"]: row["n"] for row in await cursor.fetchall()}


# --------------------------------------------------------------------- close pass


async def close_disappeared_findings(
    db: aiosqlite.Connection,
    *,
    source_type: str,
    kept_source_ids: Iterable[str],
    assessment_id: str,
    repo_url: str,
) -> int:
    """Mark prior open rows for ``source_type`` as closed if not seen this run.

    Implements the stale-close pass from ADR-0027 §7 / IMPL-0003-p2:

    1. Scope strictly by ``source_type``: a Trivy rescan never closes a Snyk
       finding even though both have ``type='dependency'``.
    2. First-run guard: if no prior assessment exists for ``repo_url`` (other
       than the current one), the close pass is a no-op.
    3. ``status NOT IN ('closed','remediated','validated','passed')`` — we
       don't reset terminal states, and posture pass rows are managed by the
       type-conditional UPSERT, not by this pass.
    4. Appends an audit note to ``raw_payload.system_notes``.

    Returns the number of rows transitioned.
    """
    cursor = await db.execute(
        """
        SELECT COUNT(*) AS n FROM assessment
         WHERE repo_url = ? AND id != ?
        """,
        (repo_url, assessment_id),
    )
    prior = await cursor.fetchone()
    if prior is None or prior["n"] == 0:
        return 0  # first-run guard

    kept = list(kept_source_ids)
    now_iso = datetime.now(UTC).isoformat()

    if kept:
        placeholders = ",".join("?" for _ in kept)
        select_sql = (
            "SELECT id, raw_payload FROM finding "
            "WHERE source_type = ? "
            "AND source_id NOT IN (" + placeholders + ") "
            "AND status NOT IN ('closed','remediated','validated','passed')"
        )
        select_params: list[str] = [source_type, *kept]
    else:
        select_sql = (
            "SELECT id, raw_payload FROM finding "
            "WHERE source_type = ? "
            "AND status NOT IN ('closed','remediated','validated','passed')"
        )
        select_params = [source_type]

    cursor = await db.execute(select_sql, select_params)
    rows = list(await cursor.fetchall())
    closed = 0
    for row in rows:
        existing = json.loads(row["raw_payload"]) if row["raw_payload"] else {}
        if not isinstance(existing, dict):
            existing = {"_legacy": existing}
        notes = existing.setdefault("system_notes", [])
        notes.append(
            {
                "event": "auto_closed",
                "reason": "not seen in scan",
                "assessment_id": assessment_id,
                "ts": now_iso,
            }
        )
        await db.execute(
            "UPDATE finding SET status = 'closed', raw_payload = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), now_iso, row["id"]),
        )
        closed += 1
    await db.commit()
    return closed
