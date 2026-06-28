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

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cliff.evals.adapter import run_agent_measured
from cliff.evals.deep_dive_evaluators import (
    check_citation_grounding,
    check_false_clear,
    check_tool_boundary,
    check_verdict_match,
)
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
    from collections.abc import Awaitable, Callable

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
        case_cost = estimate_cost_usd(pricing_model_id, run.input_tokens, run.output_tokens)
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
            result.budget_failures.append(f"run: ~${run_cost:.4f} > ${budget.max_run_usd:.4f} cap")

    result.graded_rates = {
        metric: (sum(vals) / len(vals) if vals else 1.0) for metric, vals in graded.items()
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

    result = EvalRunResult(agent="report_triager", n_cases=len(cases), graded_floor=graded_floor)

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
            root = Path(tmp).resolve()
            for rel, text in (case.files or {}).items():
                # Confine staged files to the temp workspace — a dataset row
                # with an absolute path or ``..`` segment must not escape it.
                target = (root / rel).resolve()
                if not target.is_relative_to(root):
                    raise ValueError(f"case file path escapes the workspace: {rel!r}")
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
                    usage_limits=UsageLimits(request_limit=REPORT_TRIAGER_REQUEST_LIMIT),
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


async def run_deep_dive_eval(
    cases: list[EvalCase],
    *,
    run_pipeline: Callable[[EvalCase, Path], Awaitable[Any]],
    graded_floor: float = 0.7,
) -> EvalRunResult:
    """Run the Deep dive (ADR-0052) over each case's staged repo + apply the gates.

    ``run_pipeline(case, repo_dir) -> TriageOutput`` is injected: a deterministic
    stub in CI, the real DeepDiveRunner (``make_live_deep_dive_pipeline``) in the
    live lane — same scorer either way (ADR-0050 hybrid).

    HARD gates: false-clear (golden ``real`` never cleared), citation grounding
    (every cited file:line resolves), read-only tool boundary. GRADED: verdict
    match against a floor.
    """
    if not cases:
        raise ValueError(
            "run_deep_dive_eval got 0 cases — check the dataset path / tier filter "
            "(a silent empty run would falsely report PASS)."
        )
    result = EvalRunResult(agent="triage_deep_dive", n_cases=len(cases), graded_floor=graded_floor)
    matches: list[bool] = []

    for case in cases:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / "repo"
                if case.repo and case.sha:
                    # Live lane: walk the REAL repo at the pinned commit.
                    from cliff.evals.repo_fetch import checkout_at_sha

                    await checkout_at_sha(case.repo, case.sha, repo_dir)
                else:
                    # CI / synthetic: stage the inline micro-repo.
                    repo_dir.mkdir()
                    repo_dir_resolved = repo_dir.resolve()
                    for rel, text in (case.files or {}).items():
                        # Confine staged files to the temp workspace — a dataset
                        # row with an absolute path or ``..`` segment must not
                        # escape it (matches the guard in run_report_triager_eval
                        # and run_triage_corpus_eval).
                        target = (repo_dir / rel).resolve()
                        if not target.is_relative_to(repo_dir_resolved):
                            raise ValueError(
                                f"case file path escapes the workspace: {rel!r}"
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(text)

                triage = await run_pipeline(case, repo_dir)
                golden = case.expected.as_dict().get("verdict")

                ok, reason = check_false_clear(triage.verdict, golden)
                if not ok:
                    result.hard_failures.append(f"{case.id}: {reason}")
                ok, reason = check_citation_grounding(triage.model_dump(), repo_dir)
                if not ok:
                    result.hard_failures.append(f"{case.id}: {reason}")
                if golden is not None:
                    matches.append(check_verdict_match(triage.verdict, golden)[0])
        except Exception as exc:  # noqa: BLE001 — one case's infra failure (e.g. a
            # checkout error / network blip) must not abort the whole ship gate;
            # record it and continue scoring the rest.
            result.hard_failures.append(f"{case.id}: infra error — {type(exc).__name__}: {exc}")

    ok, reason = check_tool_boundary()
    if not ok:
        result.hard_failures.append(reason)

    if matches:
        result.graded_rates["verdict_match"] = sum(matches) / len(matches)
    return result


def make_live_deep_dive_pipeline(
    env: dict[str, str], model_full_id: str
) -> Callable[[EvalCase, Path], Awaitable[Any]]:
    """A ``run_pipeline`` driving the real DeepDiveRunner over the staged repo.

    Used by the private ``cliff-os/eval`` live lane (the real golden datasets).
    The case's ``finding`` may carry ``repo_knowledge`` / ``enrichment`` /
    ``exposure`` that the staged pipeline reads.
    """
    from cliff.agents.runtime.model_tiers import clearing_is_trusted
    from cliff.agents.triage_deep.runner import DeepDiveRunner, build_tier_models

    runner = DeepDiveRunner(
        build_tier_models(env, model_full_id),
        can_clear=clearing_is_trusted(model_full_id),
    )

    async def _run(case: EvalCase, repo_dir: Path) -> Any:
        finding = case.finding
        return await runner.run(
            finding=finding,
            repo_knowledge=finding.get("repo_knowledge", {}),
            clone_dir=repo_dir,
            enrichment=finding.get("enrichment"),
            exposure=finding.get("exposure"),
            traced_sha=case.sha,  # provenance: the commit this verdict is valid for
        )

    return _run


__all__ = [
    "EvalRunResult",
    "make_live_deep_dive_pipeline",
    "run_deep_dive_eval",
    "run_enricher_eval",
    "run_report_triager_eval",
    "run_triage_synthesis_eval",
]
