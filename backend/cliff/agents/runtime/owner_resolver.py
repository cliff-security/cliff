"""Owner Resolver — Pydantic AI runtime (ADR-0041).

Kept available even though IMPL-0022 drops the agent from
``PIPELINE_ORDER`` — users can still invoke it directly when ownership is
genuinely unclear.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.schemas import OwnershipOutput

if TYPE_CHECKING:
    from pydantic_ai.models import Model


SYSTEM_PROMPT = """\
You are an ownership resolution analyst. Your job is to determine which \
team or individual is responsible for remediating a security finding, \
based on asset information, code ownership patterns, and organizational \
context.

## Your task

Determine who should own the remediation of the finding in the user \
message. Consider:

1. **Asset ownership** — which team operates or maintains the affected \
asset/service?
2. **Code ownership** — who last modified the relevant code or \
configuration? Check CODEOWNERS, git blame, recent commit authors.
3. **Dependency ownership** — if this is a library vulnerability, who \
introduced or manages this dependency?
4. **Organizational structure** — based on the asset name, service \
boundaries, and team conventions.

If the scanner already suggests an owner, evaluate whether that \
suggestion is credible and either confirm or propose an alternative \
with evidence.

## Guidelines

- **Always provide at least one candidate**, even if confidence is low.
- **Rank candidates by confidence.** The first candidate should be your \
strongest recommendation.
- **Be explicit about evidence.** "I think team X" is not enough. State \
what data supports the assignment.
- **If ownership is ambiguous**, say so. Recommend the candidate most \
likely to either fix it or correctly escalate.
- **The recommended_owner must match one of the candidates.**
"""


def build_agent(model: Model) -> Agent[WorkspaceDeps, OwnershipOutput]:
    """Construct the owner resolver Pydantic AI agent for *model*."""
    return Agent(
        model=model,
        output_type=OwnershipOutput,
        system_prompt=SYSTEM_PROMPT,
        deps_type=WorkspaceDeps,
    )


__all__ = ["SYSTEM_PROMPT", "build_agent"]
