"""Completion domain model (IMPL-0002 Milestone A + D5).

Completion is the audit row written when a user crosses every criterion in an
Assessment. `share_actions_used` tracks which of the three user-controlled share
actions the user invoked in the ceremony panel; drives the v1.1 share-action
rate metric.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TCH003 — Pydantic needs this at runtime
from typing import Literal

from pydantic import BaseModel

from cliff.models.assessment import CriteriaSnapshot

ShareAction = Literal["download", "copy_text", "copy_markdown"]


class CompletionCreate(BaseModel):
    assessment_id: str
    repo_url: str
    criteria_snapshot: CriteriaSnapshot


class Completion(BaseModel):
    id: str
    assessment_id: str
    repo_url: str
    completed_at: datetime
    criteria_snapshot: CriteriaSnapshot
    share_actions_used: list[ShareAction] = []
