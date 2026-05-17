"""DAO for the ``completion`` table (IMPL-0002 Milestone A2 + D5).

A ``completion`` row is created when an assessment reaches complete with all five
criteria met. ``record_share_action`` appends the clicked share action with
insertion-order dedup so repeat clicks from the UI don't skew the metric.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cliff.models import Completion, CompletionCreate, CriteriaSnapshot, ShareAction

if TYPE_CHECKING:
    import aiosqlite


def _row_to_completion(row: aiosqlite.Row) -> Completion:
    actions_raw = row["share_actions_used"]
    actions = json.loads(actions_raw) if actions_raw else []
    return Completion(
        id=row["id"],
        assessment_id=row["assessment_id"],
        repo_url=row["repo_url"],
        completed_at=row["completed_at"],
        criteria_snapshot=CriteriaSnapshot.model_validate(json.loads(row["criteria_snapshot"])),
        share_actions_used=actions,
    )


async def create_completion(
    db: aiosqlite.Connection, data: CompletionCreate
) -> Completion:
    completion_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """
        INSERT INTO completion
            (id, assessment_id, repo_url, completed_at, criteria_snapshot, share_actions_used)
        VALUES (?, ?, ?, ?, ?, '[]')
        """,
        (
            completion_id,
            data.assessment_id,
            data.repo_url,
            now,
            json.dumps(data.criteria_snapshot.model_dump()),
        ),
    )
    await db.commit()
    fetched = await get_completion(db, completion_id)
    assert fetched is not None
    return fetched


async def get_completion(
    db: aiosqlite.Connection, completion_id: str
) -> Completion | None:
    cursor = await db.execute("SELECT * FROM completion WHERE id = ?", (completion_id,))
    row = await cursor.fetchone()
    return _row_to_completion(row) if row else None


async def get_completion_for_assessment(
    db: aiosqlite.Connection, assessment_id: str
) -> Completion | None:
    cursor = await db.execute(
        "SELECT * FROM completion WHERE assessment_id = ? ORDER BY completed_at DESC LIMIT 1",
        (assessment_id,),
    )
    row = await cursor.fetchone()
    return _row_to_completion(row) if row else None


async def record_share_action(
    db: aiosqlite.Connection, completion_id: str, action: ShareAction
) -> Completion | None:
    """Append ``action`` to ``share_actions_used`` with insertion-order dedup."""
    existing = await get_completion(db, completion_id)
    if existing is None:
        return None
    if action in existing.share_actions_used:
        return existing

    new_actions: list[ShareAction] = [*existing.share_actions_used, action]
    await db.execute(
        "UPDATE completion SET share_actions_used = ? WHERE id = ?",
        (json.dumps(new_actions), completion_id),
    )
    await db.commit()
    return await get_completion(db, completion_id)
