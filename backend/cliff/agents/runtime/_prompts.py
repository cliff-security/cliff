"""Shared user-prompt construction for runtime agents.

Reuses the same ``ContextDocument`` section renderers that
``CONTEXT.md`` generation uses (finding / knowledge / evidence / plan
sections) so the agent's view of prior context never drifts from what
the user sees in CONTEXT.md.

Pre-migration the executor inlined a structured-output contract in
every prompt to coerce OpenCode's prose engine into emitting JSON.
With Pydantic AI's ``output_type`` Pydantic handles the contract; the
user prompt now just carries the finding row and any prior-agent
knowledge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.workspace.context_document import ContextDocument

if TYPE_CHECKING:
    from cliff.agents.runtime.deps import WorkspaceDeps


_USER_REFINEMENT_HEADER = (
    "## User refinement\n\n"
    "The user reviewed an earlier plan and asked you to revise it "
    "with the following note. Treat this as authoritative — adjust "
    "the plan steps, dependencies, and validation method to honor "
    "this guidance without losing safety.\n\n"
)


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

    evidence = ContextDocument._evidence_section(deps.prior_context.get("evidence"))
    if evidence:
        sections.append(evidence)

    plan = ContextDocument._plan_section(deps.prior_context.get("plan"))
    if plan:
        sections.append(plan)

    if deps.user_note:
        sections.append(f"{_USER_REFINEMENT_HEADER}> {deps.user_note}")

    return "\n\n".join(sections)


__all__ = ["build_user_prompt"]
