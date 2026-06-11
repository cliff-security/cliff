"""Challenge — the adversarial disprove panel (ADR-0052 §2).

The single check standing between us and shipping a confidently-wrong verdict.
A small fixed panel of reviewers, each on a distinct lens, each tasked to BREAK
the verdict, on the judge tier (a stronger model than the generator, ADR-0050).
Resolution is DETERMINISTIC (review finding #4): a majority of ``refuted``
reviewers downgrades the verdict; a tie holds but caps confidence.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pydantic_ai import Agent

from cliff.agents.runtime.deps import ReadBudget, WorkspaceDeps
from cliff.agents.runtime.tools.grep import grep
from cliff.agents.runtime.tools.read import read
from cliff.agents.schemas import Challenge, ChallengeReviewer
from cliff.agents.triage_deep.agents import (
    DEEP_DIVE_MODEL_SETTINGS,
    DEEP_DIVE_READ_BUDGET,
    render_context,
    run_agent_with_retry,
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
        "Attack the impact. Does the traced path actually support the claimed "
        "impact and severity, or is the severity inflated beyond what the code at "
        "the sink can do? Judge the impact the path PROVES — not whether an exploit "
        "was executed (this triage plans exploits, it does not run them)."
    ),
}

#: Lenses for challenging a DISPROOF — a guard the tracer says CLEARS the finding.
#: Each attacks a way a disproof can be wrong; a concrete hit means the guard does
#: NOT hold and the finding must not be cleared.
DISPROOF_LENSES: dict[str, str] = {
    "bypass": (
        "The tracer CLEARED this finding by claiming a guard makes the REPORTED "
        "vulnerability unreachable. Read the guard's ACTUAL code and try to defeat "
        "it: can a SPECIFIC attacker input (encoding, normalization, absolute path, "
        "symlink, null byte, alias) slip past it and STILL reach the REPORTED sink "
        "named in the finding? Refute ONLY if you can name a concrete input that "
        "provably reaches that sink. If the guard correctly validates the input, OR "
        "the fixed code no longer calls the reported sink at all (e.g. it returns / "
        "branches away before the sink, or now uses a safe API), the report is "
        "unexploitable — HOLD. A DIFFERENT weakness (e.g. an open redirect when the "
        "report is SSRF) is NOT a refutation — stay scoped to the reported vuln."
    ),
    "scope": (
        "The tracer CLEARED this finding via a guard. Check the guard actually "
        "protects the path to the REPORTED sink: does it run BEFORE that sink, on "
        "the finding's route (not just a sibling), and is it not behind a "
        "default-off flag or in never-called code? Refute ONLY with a concrete "
        "file:line showing the REPORTED sink is STILL reached despite the guard. If "
        "the guard covers the path to the reported sink, HOLD."
    ),
    "phantom": (
        "The tracer CLEARED this finding via a guard. Verify the guard is REAL and "
        "operative: is the cited code an actual validation / confinement / safe-API "
        "change, or did the tracer mistake an unrelated line (a type check, a log, "
        "a comment, an unrelated branch) for one? If a genuine guard or a safe API "
        "now neutralizes the attacker's control on the path to the reported sink, "
        "HOLD; refute only if no real guard exists and the sink is still reachable."
    ),
}

_SYSTEM = """\
You are an adversarial reviewer. Your job is to try to PROVE the triage verdict \
WRONG through one specific lens — not to confirm it. {lens_instruction} Read the \
cited code with `read`/`grep` to check the claims yourself rather than trusting \
the summary. Refute ONLY when you can name a SPECIFIC, concrete defect you \
verified in the code — a guard at a file:line the tracer missed, an input that is \
actually validated or normalized upstream, or an impact the traced path does not \
support. If the verdict is backed by a path you checked and you cannot point to a \
concrete hole, it HOLDS — do NOT refute out of generic caution, a wish for more \
evidence, or because the exploit was planned rather than demonstrated (this \
triage plans exploits, it does not run them). Return holds or refuted; a \
refutation must cite the specific file:line defect that breaks the verdict."""


def build_reviewer_agent(
    model: Model, lens_instruction: str
) -> Agent[WorkspaceDeps, ChallengeReviewer]:
    return Agent(
        model=model,
        output_type=ChallengeReviewer,
        deps_type=WorkspaceDeps,
        system_prompt=_SYSTEM.format(lens_instruction=lens_instruction),
        tools=[read, grep],
        model_settings=DEEP_DIVE_MODEL_SETTINGS,
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


def resolve_disproof(reviewers: list[ChallengeReviewer]) -> Challenge:
    """Resolve a DISPROOF challenge by MAJORITY (matches ``resolve_challenge``).

    A disproof CLEARS a finding, so a MAJORITY of reviewers must back the guard: if
    as many reviewers refute as hold (a tie) or more, the clear drops to
    ``needs_review``. Unanimous-to-clear proved too strict — one reviewer nitpicking
    a complex-but-correct patch (e.g. the file branch of a fixed SSRF route) vetoed
    every legitimate clear. The panel's majority view is the right balance; the
    refute-on-concrete discipline in ``_SYSTEM`` keeps refutals honest, and the
    eval's zero-false-clear gate validates that real vulns never slip through (they
    reach ``real`` via trace's reached=yes path, not this panel).
    """
    if not reviewers:
        return Challenge(
            verdict_holds=False,
            reviewers=[],
            downgraded_verdict="needs_review",
            confidence_adjustment=-0.25,
        )
    refuted = sum(1 for r in reviewers if r.verdict == "refuted")
    holds = len(reviewers) - refuted
    if refuted >= holds:  # tie or majority refute → do not clear (conservative)
        return Challenge(
            verdict_holds=False,
            reviewers=reviewers,
            downgraded_verdict="needs_review",
            confidence_adjustment=-0.25,
        )
    return Challenge(verdict_holds=True, reviewers=reviewers, confidence_adjustment=0.0)


async def _run_reviewers(
    deps: WorkspaceDeps, model: Model, lenses: dict[str, str], *, incomplete_verdict: str
) -> list[ChallengeReviewer]:
    """Run one reviewer per lens, sequentially, each with a fresh read budget."""
    prompt = render_context(deps)

    async def _one(lens: str) -> ChallengeReviewer:
        agent = build_reviewer_agent(model, lenses[lens])
        rdeps = replace(deps, read_budget=ReadBudget(DEEP_DIVE_READ_BUDGET))
        try:
            result = await run_agent_with_retry(agent, prompt, rdeps)
        except Exception:  # noqa: BLE001 — an incomplete reviewer must not crash the
            # panel. The SAFE default depends on direction: holding a 'real' verdict
            # over-flags (safe); for a disproof we must NOT clear, so an incomplete
            # disproof reviewer defaults to 'refuted'.
            return ChallengeReviewer(
                lens=lens, verdict=incomplete_verdict, refutation="reviewer did not complete"
            )
        # Pin the lens — the reviewer's job is fixed by construction, not its choice.
        return result.output.model_copy(update={"lens": lens})

    # Sequential, not gathered: 3 simultaneous calls burst into the rate/capacity
    # ceiling (Gemini AI Studio 503s under load).
    return [await _one(lens) for lens in lenses]


async def run_challenge_panel(
    deps: WorkspaceDeps, model: Model, current_verdict: str
) -> Challenge:
    """Stress-test a 'real' verdict; majority-refutes downgrades (deterministic)."""
    reviewers = await _run_reviewers(deps, model, CHALLENGE_LENSES, incomplete_verdict="holds")
    return resolve_challenge(reviewers, current_verdict)


async def run_disproof_challenge(deps: WorkspaceDeps, model: Model) -> Challenge:
    """Stress-test a DISPROOF — a guard that would CLEAR the finding.

    The symmetric safety gate: the 'real' path is challenged, so the clearing path
    must be too. Resolution is MAJORITY (``resolve_disproof``) — a majority that
    finds a concrete bypass / scope gap / phantom guard routes to needs_review
    instead of false-clearing; a lone over-refuter no longer vetoes a good clear.
    """
    reviewers = await _run_reviewers(deps, model, DISPROOF_LENSES, incomplete_verdict="refuted")
    return resolve_disproof(reviewers)


__all__ = [
    "CHALLENGE_LENSES",
    "DISPROOF_LENSES",
    "build_reviewer_agent",
    "resolve_challenge",
    "resolve_disproof",
    "run_challenge_panel",
    "run_disproof_challenge",
]
