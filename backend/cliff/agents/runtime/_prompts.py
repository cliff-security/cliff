"""Shared user-prompt construction for runtime agents.

Pre-migration the executor inlined the structured-output contract in
every prompt because OpenCode coerced a prose-emitting engine into
emitting JSON. With Pydantic AI's ``output_type`` Pydantic handles the
contract; the user prompt now just carries the finding row and any
prior-agent knowledge, reusing the same renderer ``CONTEXT.md`` uses
(``ContextDocument.finding_section`` / ``.knowledge_section``) so the
two surfaces never drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.workspace.context_document import ContextDocument

if TYPE_CHECKING:
    from cliff.agents.runtime.deps import WorkspaceDeps


def build_user_prompt(deps: WorkspaceDeps) -> str:
    """Return the per-run user prompt for any of the six no-tools agents."""
    sections: list[str] = [ContextDocument.finding_section(deps.finding)]

    knowledge = ContextDocument.knowledge_section(
        deps.prior_context.get("enrichment"),
        deps.prior_context.get("ownership"),
        deps.prior_context.get("exposure"),
    )
    if knowledge:
        sections.append(knowledge)

    evidence = deps.prior_context.get("evidence")
    if evidence:
        sections.append(_evidence_section(evidence))

    plan = deps.prior_context.get("plan")
    if plan:
        sections.append(_plan_section(plan))

    if deps.user_note:
        sections.append(
            "## User refinement\n\n"
            "The user reviewed an earlier plan and asked you to revise it "
            "with the following note. Treat this as authoritative — adjust "
            "the plan steps, dependencies, and validation method to honor "
            "this guidance without losing safety.\n\n"
            f"> {deps.user_note}"
        )

    return "\n\n".join(sections)


def _evidence_section(evidence: dict) -> str:
    lines: list[str] = ["## Evidence from repository analysis"]
    files = evidence.get("affected_files") or []
    if files:
        lines.append("### Affected files")
        for f in files:
            path = f.get("path", "?")
            line_no = f.get("line")
            ctx = f.get("context", "")
            suffix = f":{line_no}" if line_no else ""
            lines.append(f"- `{path}{suffix}` — {ctx}")
    chain = evidence.get("dependency_chain") or []
    if chain:
        lines.append(f"- **Dependency chain:** {' → '.join(chain)}")
    for key, label in (
        ("dependency_type", "Dependency type"),
        ("current_version", "Current version"),
        ("fix_safety", "Fix safety"),
        ("fix_safety_reasoning", "Reasoning"),
        ("recommended_approach", "Recommended approach"),
        ("impact_assessment", "Impact"),
    ):
        value = evidence.get(key)
        if value:
            lines.append(f"- **{label}:** {value}")
    return "\n".join(lines)


def _plan_section(plan: dict) -> str:
    lines: list[str] = ["## Remediation plan that was executed"]
    steps = plan.get("plan_steps") or []
    for idx, step in enumerate(steps, start=1):
        lines.append(f"{idx}. {step}")
    dod = plan.get("definition_of_done") or []
    if dod:
        lines.append("\n### Definition of done")
        for item in dod:
            lines.append(f"- {item}")
    validation = plan.get("validation_method")
    if validation:
        lines.append("\n### Expected validation method")
        lines.append(validation)
    return "\n".join(lines)


__all__ = ["build_user_prompt"]
