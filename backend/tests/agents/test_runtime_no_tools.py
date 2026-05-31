"""TDD-first tests for the Pydantic AI no-tools runtime layer.

Covers the three checkpoints called out in IMPL-0022 §Test plan:

* ``test_runtime_finding_enricher_uses_pa`` — the runtime call yields a
  structured-output dict shaped exactly like the OpenCode-era parser
  produced, so the executor's persistence path keeps working unchanged.
* ``test_runtime_evidence_collector_with_guard`` — ``evidence_guard``
  applies its corrections to a PA-produced output dict (asset_label /
  scanner-version backfill still happens).
* ``test_run_no_tools_agent_unknown_agent_type`` — defense-in-depth
  ValueError for an agent type that isn't registered.

The ``TestModel`` substitute is Pydantic AI's first-class testing
seam — it never talks to a real LLM but produces a validated instance
of whichever ``output_type`` the agent declared.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from cliff.agents.runtime import no_tools
from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.services.evidence_guard import guard_evidence_output


@pytest.fixture
def dep_finding() -> dict:
    """A lodash-style dependency finding for the canonical smoke case."""
    return {
        "id": "f-1",
        "title": "lodash 4.17.5 vulnerable to prototype pollution",
        "source_type": "snyk",
        "source_id": "SNYK-JS-LODASH-450202",
        "asset_label": "lodash@4.17.5",
        "raw_severity": "high",
        "raw_payload": {"version": "4.17.5", "fixed_version": "4.17.21"},
    }


@pytest.fixture
def deps(dep_finding: dict) -> WorkspaceDeps:
    return WorkspaceDeps(
        workspace_id="ws-1",
        workspace_dir="/tmp/cliff-test",
        finding=dep_finding,
        prior_context={},
    )


@pytest.mark.asyncio
async def test_runtime_finding_enricher_uses_pa(
    deps: WorkspaceDeps,
) -> None:
    """The enricher run returns a dict containing the EnrichmentOutput fields."""
    output = await no_tools.run_no_tools_agent(
        "finding_enricher", deps, TestModel()
    )
    # TestModel synthesises a value satisfying the output_type schema —
    # exact values are uninteresting; the shape is what downstream
    # persistence depends on.
    assert isinstance(output, dict)
    for field in (
        "normalized_title",
        "cve_ids",
        "known_exploits",
        "references",
    ):
        assert field in output, f"enricher output missing {field}"


@pytest.mark.asyncio
async def test_runtime_evidence_collector_with_guard(
    deps: WorkspaceDeps,
) -> None:
    """``evidence_guard`` corrects PA output the same way it did for OpenCode."""
    output = await no_tools.run_no_tools_agent(
        "evidence_collector", deps, TestModel()
    )
    # Force the two states the guard catches:
    #   1. missing current_version (B13) — backfill from raw_payload.version
    #   2. "safe_bump" with a major-version jump (B11) — downgrade to
    #      breaking_change. The fixture goes 4.x -> ... well lodash 4.17.5
    #      -> 4.17.21 stays in 4.x so we don't trigger B11 here; we focus
    #      on the B13 backfill which is the one the smoke set always
    #      exercises.
    output["current_version"] = None
    corrections = guard_evidence_output(output, deps.finding)
    assert any("backfilled" in c for c in corrections), corrections
    assert output["current_version"] == "4.17.5"


@pytest.mark.asyncio
async def test_runtime_evidence_collector_major_jump_downgrades_safe_bump(
    deps: WorkspaceDeps,
) -> None:
    """B11 — a major-version jump never stays ``safe_bump``."""
    # Bump the fixture's fixed_version into a different major.
    deps_with_jump = WorkspaceDeps(
        workspace_id=deps.workspace_id,
        workspace_dir=deps.workspace_dir,
        finding={
            **deps.finding,
            "raw_payload": {"version": "4.17.5", "fixed_version": "7.0.0"},
        },
        prior_context={},
    )
    output = await no_tools.run_no_tools_agent(
        "evidence_collector", deps_with_jump, TestModel()
    )
    output["fix_safety"] = "safe_bump"
    corrections = guard_evidence_output(output, deps_with_jump.finding)
    assert output["fix_safety"] == "breaking_change", corrections


@pytest.mark.asyncio
async def test_run_no_tools_agent_unknown_agent_type(
    deps: WorkspaceDeps,
) -> None:
    """Unregistered agent types fail loud — never silently dispatch."""
    with pytest.raises(ValueError, match="Unknown no-tools agent type"):
        await no_tools.run_no_tools_agent(
            "validation_orchestrator", deps, TestModel()
        )


def test_no_tools_agent_types_is_six() -> None:
    """The PA substrate owns the same six no-tools agents IMPL-0022 lists."""
    assert frozenset({
        "finding_enricher",
        "owner_resolver",
        "exposure_analyzer",
        "evidence_collector",
        "remediation_planner",
        "validation_checker",
    }) == no_tools.NO_TOOLS_AGENT_TYPES


def test_derive_summary_per_agent() -> None:
    """``derive_summary`` produces a non-empty, agent-aware one-liner."""
    cases: list[tuple[str, dict, str]] = [
        (
            "finding_enricher",
            {"normalized_title": "Lodash prototype pollution", "cve_ids": []},
            "Lodash prototype pollution",
        ),
        (
            "exposure_analyzer",
            {"recommended_urgency": "immediate"},
            "Recommended urgency: immediate",
        ),
        (
            "evidence_collector",
            {"fix_safety": "safe_bump"},
            "Fix safety: safe_bump",
        ),
        (
            "remediation_planner",
            {"plan_steps": ["a", "b", "c"]},
            "3 steps",
        ),
        (
            "validation_checker",
            {"verdict": "fixed"},
            "Validation verdict: fixed",
        ),
    ]
    for agent_type, structured, expected_fragment in cases:
        line = no_tools.derive_summary(agent_type, structured)
        assert expected_fragment in line, (agent_type, line)
