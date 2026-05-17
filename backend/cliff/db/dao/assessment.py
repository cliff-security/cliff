"""DAO for the ``assessment`` table (IMPL-0002 Milestone A2).

The assessment row is the event record for one scan run. ``criteria_snapshot`` is
stored as a JSON TEXT column and deserialized via the ``CriteriaSnapshot`` model.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.models import (
    Assessment,
    AssessmentCreate,
    AssessmentTool,
    AssessmentUpdate,
    CriteriaSnapshot,
    Grade,
)

if TYPE_CHECKING:
    import aiosqlite


def _row_to_assessment(row: aiosqlite.Row) -> Assessment:
    criteria_json = row["criteria_snapshot"]
    criteria = (
        CriteriaSnapshot.model_validate(json.loads(criteria_json)) if criteria_json else None
    )
    # tools_json + summary_seen_at land in migration 010 (ADR-0032). Older
    # databases that haven't run that migration yet just return None for both.
    tools_json = _safe_get(row, "tools_json")
    tools: list[AssessmentTool] | None = None
    if tools_json:
        tools = [AssessmentTool.model_validate(t) for t in json.loads(tools_json)]
    return Assessment(
        id=row["id"],
        repo_url=row["repo_url"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        status=row["status"],
        grade=row["grade"],
        criteria_snapshot=criteria,
        tools=tools,
        summary_seen_at=_safe_get(row, "summary_seen_at"),
        # IMPL-0009 (migration 014). Older databases that haven't run that
        # migration still validate because ``_safe_get`` returns ``None``.
        commit_sha=_safe_get(row, "commit_sha"),
        branch=_safe_get(row, "branch"),
        scanned_files=_safe_get(row, "scanned_files"),
        scanned_deps=_safe_get(row, "scanned_deps"),
        # Migration 015 — failure detail (only set when status == 'failed').
        error_kind=_safe_get(row, "error_kind"),
        error_message=_safe_get(row, "error_message"),
        error_details=_safe_get(row, "error_details"),
        failed_step=_safe_get(row, "failed_step"),
    )


def _safe_get(row: aiosqlite.Row, key: str) -> object | None:
    """Tolerant column access: returns None when the column doesn't exist."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


async def create_assessment(db: aiosqlite.Connection, data: AssessmentCreate) -> Assessment:
    assessment_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO assessment
            (id, repo_url, started_at, completed_at, status, grade, criteria_snapshot)
        VALUES (?, ?, ?, NULL, 'pending', NULL, NULL)
        """,
        (assessment_id, data.repo_url, now),
    )
    await db.commit()
    fetched = await get_assessment(db, assessment_id)
    assert fetched is not None  # just inserted
    return fetched


async def get_assessment(db: aiosqlite.Connection, assessment_id: str) -> Assessment | None:
    cursor = await db.execute("SELECT * FROM assessment WHERE id = ?", (assessment_id,))
    row = await cursor.fetchone()
    return _row_to_assessment(row) if row else None


async def get_latest_assessment(db: aiosqlite.Connection) -> Assessment | None:
    cursor = await db.execute(
        "SELECT * FROM assessment ORDER BY started_at DESC, id DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    return _row_to_assessment(row) if row else None


async def update_assessment(
    db: aiosqlite.Connection, assessment_id: str, data: AssessmentUpdate
) -> Assessment | None:
    fields: dict[str, object] = data.model_dump(exclude_unset=True)
    if not fields:
        return await get_assessment(db, assessment_id)

    if "criteria_snapshot" in fields and fields["criteria_snapshot"] is not None:
        # model_dump already converted it to a dict; re-serialize to JSON text.
        fields["criteria_snapshot"] = json.dumps(fields["criteria_snapshot"])
    if "tools" in fields:
        # AssessmentUpdate carries a list[AssessmentTool]; persist via the
        # tools_json column (ADR-0032).
        tools_value = fields.pop("tools")
        fields["tools_json"] = (
            json.dumps([t for t in tools_value]) if tools_value is not None else None
        )
    if "completed_at" in fields and fields["completed_at"] is not None:
        completed_at = fields["completed_at"]
        if isinstance(completed_at, datetime):
            fields["completed_at"] = completed_at.isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), assessment_id]
    cursor = await db.execute(
        f"UPDATE assessment SET {set_clause} WHERE id = ?",  # noqa: S608
        values,
    )
    await db.commit()
    if cursor.rowcount == 0:
        return None
    return await get_assessment(db, assessment_id)


async def reconcile_orphaned_assessments(db: aiosqlite.Connection) -> int:
    """Mark any ``pending``/``running`` rows as ``failed`` at startup.

    The asyncio task that owns a ``pending``/``running`` row lives in
    ``app.state.assessment_tasks`` (see ``api/_background.py``) and dies with
    the process. Any such row at boot is therefore provably orphaned — no
    live worker can drive it to a terminal state. Idempotent. Returns the
    number of rows reconciled (for logging).

    Migration 015 — also stamps the failure-detail block so the dashboard
    renders an explanation ("Assessment was interrupted (the server
    restarted)") instead of a silent ``failed`` row. Only stamps rows that
    don't already have an ``error_kind`` so a row that failed cleanly
    pre-restart keeps its original reason.
    """
    now_iso = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        """
        UPDATE assessment
           SET status = 'failed',
               completed_at = COALESCE(completed_at, ?),
               error_kind = COALESCE(error_kind, 'interrupted'),
               error_message = COALESCE(
                   error_message,
                   'Assessment was interrupted (the server restarted)'
               )
         WHERE status IN ('pending', 'running')
        """,
        (now_iso,),
    )
    await db.commit()
    return cursor.rowcount


async def reap_stale_assessments(
    db: aiosqlite.Connection, *, older_than_seconds: float
) -> int:
    """Watchdog companion to :func:`reconcile_orphaned_assessments`.

    Reconcile runs once at startup and catches process-restart orphans. This
    runs on a periodic loop while the daemon is up, catching the second
    failure mode — a row that was inserted but whose ``asyncio.create_task``
    worker never executed (event-loop death, race between INSERT and
    schedule, etc.). Any ``pending``/``running`` row whose ``started_at`` is
    older than ``older_than_seconds`` is provably wedged: the per-step
    timeouts in :mod:`cliff.assessment.engine` cap each phase well below
    that threshold, and the outer
    :data:`cliff.api._background.ASSESSMENT_RUN_TIMEOUT_S` caps the run
    itself, so a healthy task would have transitioned by now.

    Idempotent. Returns the number of rows reaped (for logging).
    """
    now = datetime.now(UTC)
    cutoff = (now - _timedelta_seconds(older_than_seconds)).isoformat()
    cursor = await db.execute(
        """
        UPDATE assessment
           SET status = 'failed',
               completed_at = COALESCE(completed_at, ?),
               error_kind = COALESCE(error_kind, 'interrupted'),
               error_message = COALESCE(
                   error_message,
                   'Assessment did not finish in time and was halted'
               )
         WHERE status IN ('pending', 'running')
           AND started_at < ?
        """,
        (now.isoformat(), cutoff),
    )
    await db.commit()
    return cursor.rowcount


def _timedelta_seconds(seconds: float):  # noqa: ANN202 — local convenience
    from datetime import timedelta

    return timedelta(seconds=seconds)


async def mark_summary_seen(
    db: aiosqlite.Connection, assessment_id: str
) -> Assessment | None:
    """Idempotently flip ``summary_seen_at`` from NULL to ``now()``.

    The interstitial gate (ADR-0032 §summary_seen_at) is one-way: the very
    first call writes the timestamp; subsequent calls read it back unchanged
    so the dashboard's gating logic is stable across reloads.
    """
    now_iso = datetime.now(UTC).isoformat()
    await db.execute(
        """
        UPDATE assessment
           SET summary_seen_at = ?
         WHERE id = ?
           AND summary_seen_at IS NULL
        """,
        (now_iso, assessment_id),
    )
    await db.commit()
    return await get_assessment(db, assessment_id)


async def set_assessment_result(
    db: aiosqlite.Connection,
    assessment_id: str,
    *,
    grade: Grade,
    criteria_snapshot: CriteriaSnapshot,
) -> Assessment:
    """Mark an assessment complete with its final grade + criteria snapshot."""
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        UPDATE assessment
           SET status = 'complete',
               grade = ?,
               criteria_snapshot = ?,
               completed_at = ?
         WHERE id = ?
        """,
        (grade, json.dumps(criteria_snapshot.model_dump()), now, assessment_id),
    )
    await db.commit()
    result = await get_assessment(db, assessment_id)
    assert result is not None
    return result
