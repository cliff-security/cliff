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
    # Price against the model the adapter actually runs (it falls back to
    # spec.default_model when model_id is None), so a None id can't silently
    # skip the USD caps.
    pricing_model_id = model_id or spec.default_model
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
        case_cost = estimate_cost_usd(
            pricing_model_id, run.input_tokens, run.output_tokens
        )
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


_TRIAGE_VOCAB = {"real", "unexploitable", "false_positive", "needs_review"}
_CLEARING_VERDICTS = {"unexploitable", "false_positive"}
_VERDICT_TO_CLOSE = {
    "real": None,
    "needs_review": None,
    "false_positive": "false_positive",
    "unexploitable": "unexploitable",
}


def run_triage_synthesis_eval(
    cases: list[EvalCase],
    *,
    graded_floor: float = 0.9,
) -> EvalRunResult:
    """Score the deterministic scanner ``triage_synthesizer`` over *cases*
    (ADR-0051 §Evaluation, ADR-0050 Lane 1 — $0, keyless, every CI push).

    Each case's ``finding`` carries ``{enrichment, exposure}``; the function is
    pure, so this needs no model/env.

    Hard gates (zero tolerance):
      - verdict in vocabulary,
      - verdict↔recommended_close pairing coherent,
      - **false-clear**: a ``real`` golden verdict closed as
        unexploitable/false_positive (the asymmetric, load-bearing failure),
      - abstention: ``abstain`` cases must resolve to ``needs_review``.
    Graded: exact verdict match against the golden label.
    """
    if not cases:
        raise ValueError(
            "run_triage_synthesis_eval got 0 cases — an empty dataset must fail, "
            "not silently report PASS. Check the dataset path / tier filter."
        )

    from cliff.agents.runtime.triage_synthesizer import synthesize_triage

    result = EvalRunResult(
        agent="triage_synthesizer", n_cases=len(cases), graded_floor=graded_floor
    )
    matches: list[bool] = []

    for case in cases:
        finding = case.finding or {}
        out = synthesize_triage(finding.get("enrichment"), finding.get("exposure"))

        if out.verdict not in _TRIAGE_VOCAB:
            result.hard_failures.append(f"{case.id}: out-of-vocab verdict {out.verdict!r}")
        if out.recommended_close != _VERDICT_TO_CLOSE.get(out.verdict):
            result.hard_failures.append(
                f"{case.id}: incoherent pairing verdict={out.verdict!r} "
                f"close={out.recommended_close!r}"
            )

        golden = case.expected.verdict
        if golden == "real" and out.verdict in _CLEARING_VERDICTS:
            result.hard_failures.append(
                f"{case.id}: FALSE-CLEAR — a real finding was closed as "
                f"{out.verdict!r} (asymmetric zero-tolerance gate)"
            )
        if case.abstain and out.verdict != "needs_review":
            result.hard_failures.append(
                f"{case.id}: abstention — expected needs_review, got {out.verdict!r}"
            )

        if golden is not None:
            matches.append(out.verdict == golden)

    result.graded_rates = {"verdict_match": sum(matches) / len(matches) if matches else 1.0}
    result.est_cost_usd = 0.0
    return result


async def run_report_triager_eval(
    cases: list[EvalCase],
    *,
    env: dict[str, str],
    model_id: str | None,
    graded_floor: float = 0.6,
) -> EvalRunResult:
    """Run the REAL report triager over *cases* and score it (ADR-0051 §4 /
    ADR-0050 Lane 2 — live, key-gated).

    Each case stages its cited files (``case.files``) into a temp workspace so
    the read-only agent can do the claim-vs-code check.

    Hard gates (zero tolerance):
      - ``tool_trace``: the report triager exposes NO mutating/side-effecting
        tool (it can never auto-close or auto-reply) — ADR-0051 §8,
      - **false-clear**: a ``real`` report dismissed as
        unexploitable/false_positive (the asymmetric, load-bearing failure),
      - abstention: ``abstain`` cases (e.g. a report citing nonexistent code)
        must resolve to ``needs_review``, never a confident dismissal.
    Graded: exact verdict match against the golden label.
    """
    if not cases:
        raise ValueError(
            "run_report_triager_eval got 0 cases — an empty dataset must fail, "
            "not silently report PASS. Check the dataset path / tier filter."
        )

    import tempfile
    from pathlib import Path

    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.usage import UsageLimits

    from cliff.agents.runtime._prompts import build_user_prompt
    from cliff.agents.runtime.deps import WorkspaceDeps
    from cliff.agents.runtime.provider import build_model
    from cliff.agents.runtime.report_triager import (
        REPORT_TRIAGER_REQUEST_LIMIT,
        REPORT_TRIAGER_TOOLS,
        build_agent,
    )
    from cliff.agents.runtime.tools import bash, edit, gh, webfetch
    from cliff.agents.schemas import TriageOutput

    result = EvalRunResult(
        agent="report_triager", n_cases=len(cases), graded_floor=graded_floor
    )

    # tool_trace HARD gate (static, but the whole safety story): the report
    # triager must carry no tool that can mutate the repo, push, or reply.
    mutating = [t for t in (bash, edit, gh, webfetch) if t in REPORT_TRIAGER_TOOLS]
    if mutating:
        names = ", ".join(t.__name__ for t in mutating)
        result.hard_failures.append(f"tool_trace: report_triager exposes {names}")

    model = build_model(env, model_id)
    matches: list[bool] = []

    for case in cases:
        with tempfile.TemporaryDirectory() as tmp:
            for rel, text in (case.files or {}).items():
                target = Path(tmp) / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            deps = WorkspaceDeps(
                workspace_id=case.id,
                workspace_dir=tmp,
                finding=case.finding,
                prior_context={},
                env_vars=env,
                user_note=None,
            )
            try:
                run = await build_agent(model).run(
                    build_user_prompt(deps),
                    deps=deps,
                    usage_limits=UsageLimits(
                        request_limit=REPORT_TRIAGER_REQUEST_LIMIT
                    ),
                )
                out = run.output
                usage = run.usage
                result.total_tokens += getattr(usage, "total_tokens", 0) or 0
            except UsageLimitExceeded:
                # Ran out of read budget without a conclusion. Production
                # surfaces this as a failed run (a Retry), never a clear; the
                # eval scores it as the safe abstention so a loopy model can't
                # false-clear — but it still counts against verdict_match for
                # any non-abstain case.
                out = TriageOutput(verdict="needs_review", confidence=0.0)

        golden = case.expected.verdict
        if golden == "real" and out.verdict in _CLEARING_VERDICTS:
            result.hard_failures.append(
                f"{case.id}: FALSE-CLEAR — a real report was dismissed as "
                f"{out.verdict!r} (asymmetric zero-tolerance gate)"
            )
        if case.abstain and out.verdict != "needs_review":
            result.hard_failures.append(
                f"{case.id}: abstention — expected needs_review, got {out.verdict!r}"
            )
        if golden is not None:
            matches.append(out.verdict == golden)

    result.graded_rates = {"verdict_match": sum(matches) / len(matches) if matches else 1.0}
    return result


__all__ = [
    "EvalRunResult",
    "run_enricher_eval",
    "run_report_triager_eval",
    "run_triage_synthesis_eval",
]
