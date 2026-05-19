"""Pipeline orchestrator — determines agent sequence and runs pipelines.

Advisory, not enforcing. Users can run agents in any order, skip agents,
or re-run agents. ``suggest_next()`` is a recommendation based on current
workspace context state.

Forward pipeline (5-agent): enricher → exposure → evidence → planner →
executor. Owner resolution dropped from the forward walk per IMPL-0022
PR #1 — the agent stays available for direct invocation when ownership
is genuinely unclear, but most findings either carry a scanner-supplied
owner or land on the workspace creator. The validation checker stays
on-demand — it verifies a fix that does not exist until the executor
runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from cliff.workspace.workspace_dir import AGENT_TYPE_TO_SECTION

if TYPE_CHECKING:
    import aiosqlite

    from cliff.agents.executor import AgentExecutionResult, AgentExecutor

logger = logging.getLogger(__name__)

# Pipeline order — the forward suggested sequence. ``validation_checker``
# is deliberately absent (runs on-demand after remediation, not in the
# forward walk); ``owner_resolver`` is also absent per IMPL-0022 PR #1
# but stays callable directly. See the module docstring.
PIPELINE_ORDER: list[str] = [
    "finding_enricher",
    "exposure_analyzer",
    "evidence_collector",
    "remediation_planner",
    "remediation_executor",
]

# All valid agent types (including on-demand agents).
# Used by the execute endpoint to validate agent_type.
VALID_AGENT_TYPES: set[str] = set(AGENT_TYPE_TO_SECTION.keys())

# Maximum retry iterations for the plan-validate loop.
MAX_RETRY_ITERATIONS = 3

# Maps pipeline agents to the context section they check.
_PIPELINE_CHECKS: list[tuple[str, str]] = [
    ("enrichment", "finding_enricher"),
    ("exposure", "exposure_analyzer"),
    ("evidence", "evidence_collector"),
    ("plan", "remediation_planner"),
    ("remediation", "remediation_executor"),
]


@dataclass
class SuggestedAction:
    """A recommended next agent to run."""

    agent_type: str | None
    reason: str
    priority: Literal["recommended", "optional", "required"]
    prerequisites_met: bool = True
    action_type: Literal["run_agent", "review_pr", "await_approval"] = "run_agent"


def suggest_next(
    context_snapshot: dict[str, Any],
    agent_run_history: list[dict[str, Any]] | None = None,
) -> SuggestedAction | None:
    """Determine the recommended next agent based on current context state.

    Args:
        context_snapshot: Dict with keys: finding, enrichment, ownership,
            exposure, plan, remediation, validation (values are dicts or None).
        agent_run_history: Optional list of past agent run dicts (from
            agent-runs.jsonl) to detect retry loops.

    Returns:
        SuggestedAction with the recommended agent, or None if pipeline
        is complete.
    """
    # If on-demand validation ran and found issues, re-plan first.
    validation = context_snapshot.get("validation")
    if validation:
        verdict = (validation.get("verdict") or "").lower()
        if verdict in ("not_fixed", "partially_fixed"):
            retry_count = _count_plan_retries(agent_run_history or [])
            if retry_count < MAX_RETRY_ITERATIONS:
                return SuggestedAction(
                    agent_type="remediation_planner",
                    reason=(
                        f"Validation found issues "
                        f"(attempt {retry_count + 1}/{MAX_RETRY_ITERATIONS}). "
                        f"Re-planning."
                    ),
                    priority="required",
                )
            # Retry limit reached — fall through to normal flow.

    # Standard pipeline order — suggest first missing section, with one
    # explicit gate: pause for user approval before the executor runs.
    # PRD-0006 Story 3 — parity with the PR review gate. Once the plan is
    # marked ``approved=true`` (POST /workspaces/:id/plan/approve), the
    # run-all loop resumes and the executor is suggested as normal.
    for section, agent_type in _PIPELINE_CHECKS:
        if context_snapshot.get(section) is None:
            if agent_type == "remediation_executor":
                plan = context_snapshot.get("plan") or {}
                if not plan.get("approved"):
                    return SuggestedAction(
                        agent_type=None,
                        reason=(
                            "Plan ready — review the steps and approve before "
                            "the executor opens a pull request."
                        ),
                        priority="required",
                        action_type="await_approval",
                    )
            return SuggestedAction(
                agent_type=agent_type,
                reason=_REASONS[section],
                priority="recommended",
            )

    # All 4 pipeline sections present — check remediation status.
    remediation = context_snapshot.get("remediation", {})
    status = (remediation.get("status") or "").lower() if remediation else ""

    if status == "pr_created":
        return SuggestedAction(
            agent_type=None,
            reason="Pull request created — ready for review",
            priority="recommended",
            action_type="review_pr",
        )

    # Pipeline complete (or remediation in a non-terminal state).
    return None


_REASONS: dict[str, str] = {
    "enrichment": "CVE details and exploit info not yet collected",
    "exposure": "Reachability and blast radius not yet assessed",
    "evidence": "Affected files and fix impact not yet analyzed",
    "plan": "No remediation plan created yet",
    "remediation": "Remediation not yet executed",
}


def _count_plan_retries(agent_run_history: list[dict[str, Any]]) -> int:
    """Count how many remediation_planner runs have completed."""
    return sum(
        1
        for run in agent_run_history
        if run.get("agent_type") == "remediation_planner"
        and run.get("status") == "completed"
    )


async def run_pipeline(
    executor: AgentExecutor,
    workspace_id: str,
    db: aiosqlite.Connection,
    *,
    workspace_dir: str,
    context_builder: Any,
    on_agent_complete: Any | None = None,
) -> list[AgentExecutionResult]:
    """Run all remaining agents in pipeline order.

    Stops on first failure. Returns list of results for agents that ran.
    """

    results: list[AgentExecutionResult] = []

    for _iteration in range(len(PIPELINE_ORDER) + MAX_RETRY_ITERATIONS):
        # Get current context to determine next step
        snapshot = await context_builder.get_context_snapshot(workspace_id)
        run_history = snapshot.get("agent_run_history", [])

        suggestion = suggest_next(snapshot, run_history)
        if suggestion is None or suggestion.action_type != "run_agent":
            break  # Pipeline complete or terminal action

        result = await executor.execute(
            workspace_id,
            suggestion.agent_type,
            db,
            workspace_dir=workspace_dir,
        )
        results.append(result)

        if on_agent_complete:
            on_agent_complete(result)

        # EF-B17 — ``rate_limited`` is a terminal non-success state, same
        # pipeline-stop semantics as ``failed``.
        if result.status in ("failed", "rate_limited"):
            logger.warning(
                "Pipeline stopped: %s ended %s in workspace %s",
                suggestion.agent_type,
                result.status,
                workspace_id,
            )
            break

    return results
