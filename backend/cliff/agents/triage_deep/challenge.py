"""Challenge — the adversarial disprove panel (ADR-0052 §2).

The single check standing between us and shipping a confidently-wrong verdict.
A small fixed panel of reviewers, each on a distinct lens, each tasked to BREAK
the verdict, on the judge tier (a stronger model than the generator, ADR-0050).
Resolution is DETERMINISTIC (review finding #4): a majority of ``refuted``
reviewers downgrades the verdict; a tie holds but caps confidence.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from cliff.agents.runtime.deps import ReadBudget, WorkspaceDeps
from cliff.agents.runtime.tools.grep import grep
from cliff.agents.runtime.tools.read import read
from cliff.agents.schemas import Challenge, ChallengeReviewer
from cliff.agents.triage_deep.agents import (
    DEEP_DIVE_READ_BUDGET,
    DEEP_DIVE_REQUEST_LIMIT,
    render_context,
)

if TYPE_CHECKING:
    from pydantic_ai.models import Model

#: One reviewer per lens — diversity catches failure modes redundancy can't.
CHALLENGE_LENSES: dict[str, str] = {
    "reachability": (
        "Attack the reachability path. Is there a guard the tracer missed "
        "(walk-the-parallel-guard)? Is a hop actually unreachable in the real build?"
    ),
    "exploit": (
        "Attack the exploit plan. Would the trigger actually fire? Is the input "
        "genuinely attacker-controlled, or normalized/validated upstream?"
    ),
    "impact": (
        "Attack the impact. Is it demonstrated by the evidence or merely assumed? "
        "Is the severity inflated beyond what the path supports?"
    ),
}

_SYSTEM = """\
You are an adversarial reviewer. Your job is to try to PROVE the triage verdict \
WRONG through one specific lens — not to confirm it. {lens_instruction} Read the \
cited code with `read`/`grep` to check claims yourself rather than trusting the \
summary. Apply the test: "would a tired triager reading 30 reports a day believe \
this at the cited severity?" Default to `refuted` when the evidence is weak or \
you cannot verify a load-bearing claim. Return holds or refuted with a concrete \
refutation."""


def build_reviewer_agent(model: Model, lens: str) -> Agent[WorkspaceDeps, ChallengeReviewer]:
    return Agent(
        model=model,
        output_type=ChallengeReviewer,
        deps_type=WorkspaceDeps,
        system_prompt=_SYSTEM.format(lens_instruction=CHALLENGE_LENSES[lens]),
        tools=[read, grep],
    )


def resolve_challenge(
    reviewers: list[ChallengeReviewer], current_verdict: str
) -> Challenge:
    """Deterministic resolution (ADR-0052 §2).

    Majority ``refuted`` -> downgrade to ``needs_review`` (conservative: a failed
    challenge never auto-promotes to ``real``). A tie holds but caps confidence.
    """
    if not reviewers:
        return Challenge(verdict_holds=True, reviewers=[], confidence_adjustment=0.0)

    refuted = sum(1 for r in reviewers if r.verdict == "refuted")
    holds = len(reviewers) - refuted

    if refuted > holds:
        return Challenge(
            verdict_holds=False,
            reviewers=reviewers,
            downgraded_verdict="needs_review",
            confidence_adjustment=-0.25,
        )
    if refuted == holds and refuted > 0:
        # Tie — the verdict survives but is no longer high-confidence.
        return Challenge(
            verdict_holds=True, reviewers=reviewers, confidence_adjustment=-0.1
        )
    return Challenge(verdict_holds=True, reviewers=reviewers, confidence_adjustment=0.0)


async def run_challenge_panel(
    deps: WorkspaceDeps, model: Model, current_verdict: str
) -> Challenge:
    """Run every lens reviewer in parallel and resolve deterministically."""
    prompt = render_context(deps)

    async def _one(lens: str) -> ChallengeReviewer:
        agent = build_reviewer_agent(model, lens)
        # Fresh per-reviewer read budget so the panel can't overflow context.
        rdeps = replace(deps, read_budget=ReadBudget(DEEP_DIVE_READ_BUDGET))
        try:
            result = await agent.run(
                prompt, deps=rdeps, usage_limits=UsageLimits(request_limit=DEEP_DIVE_REQUEST_LIMIT)
            )
        except Exception:  # noqa: BLE001 — a reviewer that can't finish must not
            # crash the panel or wrongly downgrade: an incomplete challenge holds.
            return ChallengeReviewer(
                lens=lens, verdict="holds", refutation="reviewer did not complete"
            )
        # Pin the lens — the reviewer's job is fixed by construction, not its choice.
        return result.output.model_copy(update={"lens": lens})

    reviewers = await asyncio.gather(*(_one(lens) for lens in CHALLENGE_LENSES))
    return resolve_challenge(list(reviewers), current_verdict)


__all__ = [
    "CHALLENGE_LENSES",
    "build_reviewer_agent",
    "resolve_challenge",
    "run_challenge_panel",
]
