"""App-level finding-normalizer agent (ADR-0022 / ADR-0047, IMPL-0022 PR #3b).

The normalizer is a single LLM call — raw scanner JSON in, a list of
normalized findings out. Unlike the six pipeline agents it is *app-level*:
it runs outside any workspace, so it has no ``WorkspaceDeps`` and no tools.

Pydantic AI's structured ``output_type`` + its internal validation/retry
loop replace the hand-rolled ``_call_llm_with_retry`` / ``_extract_json_array``
machinery the OpenCode-era normalizer carried.

The output schema (:class:`NormalizedFinding`) is deliberately **lenient** —
every field is optional. The model is coaxed toward the right shape by the
system prompt, but the load-bearing validation stays in
``normalize_findings``, which maps each item onto ``FindingCreate`` and
collects per-item errors. Keeping the PA schema lenient preserves the
normalizer's partial-success contract: one malformed item lands in
``errors`` while the rest succeed, rather than failing the whole batch.

The domain prompt lives with the caller in
``cliff.integrations.normalizer`` (it is finding-ingest domain content, and
importing it here would be circular) and is passed in via ``system_prompt``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from pydantic_ai import Agent

if TYPE_CHECKING:
    from pydantic_ai.models import Model


class NormalizedFinding(BaseModel):
    """One finding as extracted by the normalizer LLM.

    Lenient by design — see the module docstring. Mirrors the JSON object
    the system prompt describes; the strict contract is ``FindingCreate``,
    enforced downstream in ``normalize_findings``.
    """

    source_type: str | None = None
    source_id: str | None = None
    title: str | None = None
    description: str | None = None
    raw_severity: str | None = None
    normalized_priority: str | None = None
    asset_id: str | None = None
    asset_label: str | None = None
    status: str | None = None
    likely_owner: str | None = None
    why_this_matters: str | None = None
    plain_description: str | None = None
    # Arbitrary passthrough — the model occasionally wraps the original object
    # in a single-element list, which ``normalize_findings`` coerces back to a
    # dict before the strict ``FindingCreate`` validation. Typed ``Any`` so PA
    # doesn't reject the list shape outright.
    raw_payload: Any = None


def build_normalizer_agent(
    model: Model, *, system_prompt: str
) -> Agent[None, list[NormalizedFinding]]:
    """Build the app-level normalizer agent.

    No ``deps_type`` and no tools — a pure structured-extraction call. The
    union-free ``output_type=list[NormalizedFinding]`` makes Pydantic AI
    drive the model to return a JSON array of objects and validate it.
    """
    return Agent(
        model,
        output_type=list[NormalizedFinding],
        system_prompt=system_prompt,
    )


__all__ = ["NormalizedFinding", "build_normalizer_agent"]
