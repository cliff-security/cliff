"""Escalation → Deep dive glue (ADR-0052 P2.10).

Sits between the Quick read and the agentic Deep dive: decides whether to
escalate, and if so resolves the repo's cached profile + clone and runs the
DeepDiveRunner. Best-effort — returns ``None`` (caller keeps the cheap verdict)
when escalation says no, no AI provider is configured, or the repo has no ready
profile yet.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cliff.agents.triage_deep.escalation import (
    DEFAULT_DEEP_DIVE_BUDGET,
    decide_escalation,
)
from cliff.agents.triage_deep.runner import DeepDiveRunner, build_tier_models
from cliff.repos.dao import get_repo_by_url
from cliff.repos.service import default_repo_dir_manager

if TYPE_CHECKING:
    import aiosqlite

    from cliff.agents.schemas import TriageOutput
    from cliff.repos.repo_dir_manager import RepoDirManager

logger = logging.getLogger(__name__)


async def maybe_deep_dive(
    db: aiosqlite.Connection,
    *,
    finding: dict,
    quick: TriageOutput,
    repo_url: str | None,
    enrichment: dict | None,
    exposure: dict | None,
    ai_env: dict[str, str] | None,
    model_full_id: str | None,
    budget_remaining: int = DEFAULT_DEEP_DIVE_BUDGET,
    source: str = "scanner",
    dir_mgr: RepoDirManager | None = None,
    runner: Any | None = None,
) -> TriageOutput | None:
    """Run the Deep dive when warranted; else ``None`` (keep the Quick read).

    ``runner`` is injectable for testing — the default builds a real
    ``DeepDiveRunner`` from the tier models.
    """
    decision = decide_escalation(
        quick.verdict, finding, budget_remaining=budget_remaining, source=source
    )
    if not decision.escalate:
        logger.debug("deep dive not escalated: %s", decision.reason)
        return None
    if not model_full_id or not ai_env:
        logger.info("deep dive skipped — no AI provider configured")
        return None
    if not repo_url:
        return None

    repo = await get_repo_by_url(db, repo_url)
    if repo is None or repo.profile_status != "ready" or not repo.profile_dir:
        logger.info("deep dive skipped — no ready profile for %s", repo_url)
        return None

    mgr = dir_mgr or default_repo_dir_manager()
    clone_dir = mgr.clone_dir(repo.id)
    if not clone_dir.exists():
        logger.info("deep dive skipped — cached clone missing for %s", repo_url)
        return None

    knowledge = {
        name: mgr.read_artifact(repo.id, name)
        for name in ("profile", "code_map", "threat")
    }
    active_runner = runner or DeepDiveRunner(build_tier_models(ai_env, model_full_id))
    return await active_runner.run(
        finding=finding,
        repo_knowledge=knowledge,
        clone_dir=clone_dir,
        enrichment=enrichment,
        exposure=exposure,
        traced_sha=repo.last_profiled_sha,
    )


__all__ = ["maybe_deep_dive"]
