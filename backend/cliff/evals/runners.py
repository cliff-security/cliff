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

from cliff.evals.adapter import run_agent
from cliff.evals.evaluators import (
    assess_references,
    check_abstention,
    check_cve_ids,
    check_cvss_within,
    check_no_jargon_title,
)
from cliff.evals.registry import get_spec

if TYPE_CHECKING:
    from cliff.evals.cases import EvalCase


@dataclass
class EvalRunResult:
    agent: str
    n_cases: int
    graded_floor: float
    hard_failures: list[str] = field(default_factory=list)
    graded_rates: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.hard_failures and all(
            rate >= self.graded_floor for rate in self.graded_rates.values()
        )

    def report(self) -> str:
        lines = [f"{self.agent}: {self.n_cases} cases — {'PASS' if self.passed else 'FAIL'}"]
        for metric, rate in sorted(self.graded_rates.items()):
            flag = "" if rate >= self.graded_floor else f"  ⛔ < {self.graded_floor:.0%}"
            lines.append(f"  graded {metric:18s} {rate:.0%}{flag}")
        for hf in self.hard_failures:
            lines.append(f"  ⛔ HARD {hf}")
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
    spec = get_spec("finding_enricher")
    result = EvalRunResult(agent=spec.name, n_cases=len(cases), graded_floor=graded_floor)
    graded: dict[str, list[bool]] = {
        "cve_ids": [],
        "cvss_within": [],
        "no_jargon_title": [],
        "reference_liveness": [],
    }

    for case in cases:
        out = await run_agent(spec, case.finding, env=env, model_id=model_id)
        refs = await assess_references(out)

        if refs.structural:
            bad = "; ".join(f"{u} ({why})" for u, why in refs.structural)
            result.hard_failures.append(f"{case.id}: structural_citations — {bad}")
        if case.abstain:
            ok, reason = check_abstention(out)
            if not ok:
                result.hard_failures.append(f"{case.id}: abstention — {reason}")

        graded["cve_ids"].append(check_cve_ids(out, case.expected)[0])
        graded["cvss_within"].append(check_cvss_within(out, case.expected)[0])
        graded["no_jargon_title"].append(check_no_jargon_title(out)[0])
        graded["reference_liveness"].append(not refs.network)

    result.graded_rates = {
        metric: (sum(vals) / len(vals) if vals else 1.0)
        for metric, vals in graded.items()
    }
    return result


__all__ = ["EvalRunResult", "run_enricher_eval"]
