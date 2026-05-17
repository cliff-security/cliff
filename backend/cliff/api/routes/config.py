"""Read-only config endpoints.

Exposes two bootstrap signals the SPA needs on load: whether the user has
already completed onboarding, and whether any assessment has ever been run.
The first-run redirect + already-onboarded short-circuit use these to decide
where to send the user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cliff.db.connection import get_db
from cliff.db.dao.assessment import get_latest_assessment
from cliff.db.repo_setting import get_setting

router = APIRouter(prefix="/config", tags=["config"])


class BootstrapState(BaseModel):
    """Read-only state the SPA fetches before rendering the first page."""

    onboarding_completed: bool
    has_any_assessment: bool


@router.get("/bootstrap", response_model=BootstrapState)
async def get_bootstrap(db=Depends(get_db)) -> BootstrapState:
    """Bootstrap hints for SPA redirect decisions."""
    setting = await get_setting(db, "onboarding.completed")
    onboarding_completed = False
    if setting is not None and isinstance(setting.value, dict):
        onboarding_completed = bool(setting.value.get("completed"))

    latest = await get_latest_assessment(db)

    return BootstrapState(
        onboarding_completed=onboarding_completed,
        has_any_assessment=latest is not None,
    )
