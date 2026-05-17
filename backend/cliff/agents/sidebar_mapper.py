"""Sidebar mapper — maps agent structured output to SidebarState fields.

Uses read-merge-write pattern: reads existing sidebar state, overlays new
fields from the agent output, then upserts the merged result. This prevents
data loss when two agents write to the same section (e.g., enricher and
exposure both update ``evidence``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cliff.models import SidebarStateUpdate

if TYPE_CHECKING:
    import aiosqlite


def map_to_sidebar_update(
    agent_type: str,
    structured_output: dict[str, Any],
) -> SidebarStateUpdate:
    """Map agent structured output to a partial SidebarStateUpdate.

    Returns a SidebarStateUpdate with only the fields that this agent
    type is responsible for. All other fields remain None (unset).
    """
    mapper = _AGENT_SIDEBAR_MAP.get(agent_type)
    if mapper is None:
        return SidebarStateUpdate()
    return mapper(structured_output)


async def map_and_upsert(
    db: aiosqlite.Connection,
    workspace_id: str,
    agent_type: str,
    structured_output: dict[str, Any],
) -> None:
    """Map agent output to sidebar fields and upsert with merge.

    Reads current sidebar state, merges new fields (non-None only),
    then upserts the merged result. This prevents clobbering fields
    set by prior agents.
    """
    from cliff.db.repo_sidebar import get_sidebar, upsert_sidebar

    # 1. Get the partial update from this agent
    partial = map_to_sidebar_update(agent_type, structured_output)

    # 2. Read existing sidebar state
    existing = await get_sidebar(db, workspace_id)

    # 3. Merge: start with existing values, overlay non-None fields from partial
    merged_data: dict[str, Any] = {}
    for field_name in SidebarStateUpdate.model_fields:
        new_val = getattr(partial, field_name)
        if new_val is not None:
            # For dict fields, deep-merge existing and new
            existing_val = getattr(existing, field_name, None) if existing else None
            if isinstance(existing_val, dict) and isinstance(new_val, dict):
                merged = {**existing_val, **new_val}
                merged_data[field_name] = merged
            else:
                merged_data[field_name] = new_val
        elif existing is not None:
            merged_data[field_name] = getattr(existing, field_name, None)

    await upsert_sidebar(db, workspace_id, SidebarStateUpdate(**merged_data))


# ---------------------------------------------------------------------------
# Mapping functions per agent type
# ---------------------------------------------------------------------------


def _map_enricher(out: dict[str, Any]) -> SidebarStateUpdate:
    return SidebarStateUpdate(
        summary={
            "title": out.get("normalized_title"),
            "cvss_score": out.get("cvss_score"),
            "cve_ids": out.get("cve_ids"),
            "description": out.get("description"),
        },
        evidence={
            "known_exploits": out.get("known_exploits"),
            "exploit_details": out.get("exploit_details"),
            "references": out.get("references"),
            "fixed_version": out.get("fixed_version"),
            "affected_versions": out.get("affected_versions"),
        },
    )


def _map_owner(out: dict[str, Any]) -> SidebarStateUpdate:
    return SidebarStateUpdate(
        owner={
            "recommended_owner": out.get("recommended_owner"),
            "candidates": out.get("candidates"),
            "reasoning": out.get("reasoning"),
        },
    )


def _map_exposure(out: dict[str, Any]) -> SidebarStateUpdate:
    return SidebarStateUpdate(
        evidence={
            "environment": out.get("environment"),
            "internet_facing": out.get("internet_facing"),
            "reachable": out.get("reachable"),
            "reachability_evidence": out.get("reachability_evidence"),
            "blast_radius": out.get("blast_radius"),
            "recommended_urgency": out.get("recommended_urgency"),
        },
    )


def _map_planner(out: dict[str, Any]) -> SidebarStateUpdate:
    return SidebarStateUpdate(
        plan={
            "plan_steps": out.get("plan_steps"),
            "interim_mitigation": out.get("interim_mitigation"),
            "dependencies": out.get("dependencies"),
            "estimated_effort": out.get("estimated_effort"),
            "suggested_due_date": out.get("suggested_due_date"),
            "validation_method": out.get("validation_method"),
        },
        definition_of_done={
            "items": out.get("definition_of_done"),
            "validation_method": out.get("validation_method"),
        },
    )


def _map_validation(out: dict[str, Any]) -> SidebarStateUpdate:
    return SidebarStateUpdate(
        validation={
            "verdict": out.get("verdict"),
            "evidence": out.get("evidence"),
            "remaining_concerns": out.get("remaining_concerns"),
            "recommendation": out.get("recommendation"),
        },
    )


def _map_executor(out: dict[str, Any]) -> SidebarStateUpdate:
    return SidebarStateUpdate(
        pull_request={
            "status": out.get("status"),
            "pr_url": out.get("pr_url"),
            "branch_name": out.get("branch_name"),
            "changes_summary": out.get("changes_summary"),
            "test_results": out.get("test_results"),
            "error_details": out.get("error_details"),
        },
    )


def _map_evidence_collector(out: dict[str, Any]) -> SidebarStateUpdate:
    return SidebarStateUpdate(
        evidence={
            "affected_files": out.get("affected_files"),
            "dependency_chain": out.get("dependency_chain"),
            "dependency_type": out.get("dependency_type"),
            "current_version": out.get("current_version"),
            "fix_safety": out.get("fix_safety"),
            "fix_safety_reasoning": out.get("fix_safety_reasoning"),
            "test_coverage": out.get("test_coverage"),
            "recommended_approach": out.get("recommended_approach"),
            "impact_assessment": out.get("impact_assessment"),
        },
    )


_AGENT_SIDEBAR_MAP: dict[str, Any] = {
    "finding_enricher": _map_enricher,
    "owner_resolver": _map_owner,
    "exposure_analyzer": _map_exposure,
    "evidence_collector": _map_evidence_collector,
    "remediation_planner": _map_planner,
    "remediation_executor": _map_executor,
    "validation_checker": _map_validation,
}
