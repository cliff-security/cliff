"""Reusable eval run loops (ADR-0050).

The orchestration lives here — in the public ``cliff`` package — so it can be
driven from BOTH the in-repo live test (public synthetic sample) AND the
private ``cliff-os/eval`` project (real/confidential datasets), which depends
on ``cliff`` and only supplies its own dataset dir. Same scorer, two data
sources (ADR-0050 hybrid).

Agent-specific for now (only ``finding_enricher`` is wired). Generalize into a
registry-driven loop when the second agent lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cliff.evals.adapter import run_agent_measured
from cliff.evals.evaluators import (
    assess_references,
    check_abstention,
    check_cve_ids,
    check_cvss_within,
    check_no_jargon_title,
)
from cliff.evals.pricing import estimate_cost_usd
from cliff.evals.registry import get_spec

if TYPE_CHECKING:
    from cliff.evals.cases import EvalCase


@dataclass
class EvalRunResult:
    agent: str
    n_cases: int
    graded_floor: float
    hard_failures: list[str] = field(default_factory=list)
    budget_failures: list[str] = field(default_factory=list)
    graded_rates: dict[str, float] = field(default_factory=dict)
    # Advisory metrics are reported + tracked but do NOT gate pass/fail — e.g.
    # reference_liveness, since production strips dead links so they never reach
    # the user. Only structural fabrication (the hard gate) is user-harmful.
    advisory: set[str] = field(default_factory=set)
    total_tokens: int = 0
    est_cost_usd: float | None = None

    @property
    def passed(self) -> bool:
        return (
            not self.hard_failures
            and not self.budget_failures
            and all(
                rate >= self.graded_floor
                for metric, rate in self.graded_rates.items()
                if metric not in self.advisory
            )
        )

    def report(self) -> str:
        cost = f"~${self.est_cost_usd:.4f}" if self.est_cost_usd is not None else "$?"
        lines = [
            f"{self.agent}: {self.n_cases} cases — {'PASS' if self.passed else 'FAIL'}"
            f"  ({self.total_tokens:,} tok, {cost})"
        ]
        for metric, rate in sorted(self.graded_rates.items()):
            if metric in self.advisory:
                lines.append(f"  advis. {metric:18s} {rate:.0%}  (tracked, non-gating)")
                continue
            flag = "" if rate >= self.graded_floor else f"  ⛔ < {self.graded_floor:.0%}"
            lines.append(f"  graded {metric:18s} {rate:.0%}{flag}")
        for hf in self.hard_failures:
            lines.append(f"  ⛔ HARD   {hf}")
        for bf in self.budget_failures:
            lines.append(f"  ⛔ BUDGET {bf}")
        return "\n".join(lines)


async def run_enricher_eval(
    cases: list[EvalCase],
    *,
    env: dict[str, str],
    model_id: str | None,
    graded_floor: float = 0.6,
) -> EvalRunResult:
    """Run the real finding_enricher over *cases* and score it.

    Hard gates (zero tolerance, collected into ``hard_failures``): structural
    citation fabrication on every case, abstention on every ``abstain`` case.
    Graded metrics (dataset-wide pass rate vs ``graded_floor``): cve_ids,
    cvss_within, no_jargon_title, reference_liveness.
    """
    if not cases:
        raise ValueError(
            "run_enricher_eval got 0 cases — an empty dataset must fail, not "
            "silently report PASS. Check the dataset path / tier filter."
        )

    spec = get_spec("finding_enricher")
    budget = spec.budget
    result = EvalRunResult(
        agent=spec.name,
        n_cases=len(cases),
        graded_floor=graded_floor,
        # Dead-link guesses are stripped by production before the user sees
        # them, so reference_liveness is a model-quality signal, not a gate.
        advisory={"reference_liveness"},
    )
    graded: dict[str, list[bool]] = {
        "cve_ids": [],
        "cvss_within": [],
        "no_jargon_title": [],
        "reference_liveness": [],
    }
    run_cost = 0.0
    run_cost_known = True

    for case in cases:
        run = await run_agent_measured(spec, case.finding, env=env, model_id=model_id)
        out = run.output

        # Per-case budget (ADR-0050 §4): tokens + duration are hard; $ is
        # best-effort (skipped when the model isn't priced).
        if budget.max_tokens is not None and run.total_tokens > budget.max_tokens:
            result.budget_failures.append(
                f"{case.id}: {run.total_tokens:,} tok > {budget.max_tokens:,} cap"
            )
        if budget.max_duration_s is not None and run.duration_s > budget.max_duration_s:
            result.budget_failures.append(
                f"{case.id}: {run.duration_s:.0f}s > {budget.max_duration_s:.0f}s cap"
            )
        case_cost = estimate_cost_usd(model_id, run.input_tokens, run.output_tokens)
        if case_cost is None:
            run_cost_known = False
        else:
            run_cost += case_cost
            if budget.max_usd is not None and case_cost > budget.max_usd:
                result.budget_failures.append(
                    f"{case.id}: ~${case_cost:.4f} > ${budget.max_usd:.4f} cap"
                )
        result.total_tokens += run.total_tokens

        refs = await assess_references(out)
        if refs.structural:
            bad = "; ".join(f"{u} ({why})" for u, why in refs.structural)
            result.hard_failures.append(f"{case.id}: structural_citations — {bad}")
        if case.abstain:
            ok, reason = check_abstention(out)
            if not ok:
                result.hard_failures.append(f"{case.id}: abstention — {reason}")

        expected = case.expected.as_dict()
        graded["cve_ids"].append(check_cve_ids(out, expected)[0])
        graded["cvss_within"].append(check_cvss_within(out, expected)[0])
        graded["no_jargon_title"].append(check_no_jargon_title(out)[0])
        graded["reference_liveness"].append(not refs.network)

    # Per-run budget (the runaway-bill stop).
    if budget.max_run_tokens is not None and result.total_tokens > budget.max_run_tokens:
        result.budget_failures.append(
            f"run: {result.total_tokens:,} tok > {budget.max_run_tokens:,} cap"
        )
    if run_cost_known:
        result.est_cost_usd = run_cost
        if budget.max_run_usd is not None and run_cost > budget.max_run_usd:
            result.budget_failures.append(
                f"run: ~${run_cost:.4f} > ${budget.max_run_usd:.4f} cap"
            )

    result.graded_rates = {
        metric: (sum(vals) / len(vals) if vals else 1.0)
        for metric, vals in graded.items()
    }
    return result


__all__ = ["EvalRunResult", "run_enricher_eval"]
