"""Triage corpus scorer (ADR-0050) — the three-bucket scorecard.

Pure + keyless: turns ``(cliff_verdict, ground_truth)`` pairs into Right /
Wrong / Not-sure counts. Reused unchanged by every way of producing Cliff's
verdict (the live Deep dive baseline today; the deterministic resolver later).

Cliff's 4 verdicts collapse to 3 DISPOSITIONS; ground truth is 3-way. The
mapping is the whole policy:

* noise      → clearing is Right; flagging is the FALSE ALARM (Wrong); hedging is Not-sure.
* real       → flagging is Right; clearing is the FALSE CLEAR (Wrong); hedging is Not-sure.
* your-call  → flagging OR hedging is Right (it genuinely needs human judgement);
               clearing it is a FALSE CLEAR (Wrong).

Wrong is split into ``false_alarms`` (a non-issue called real) and
``false_clears`` (a real/your-call dismissed) — the two trust-burning mistakes.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from cliff.agents.schemas import TriageOutput
    from cliff.evals.cases import EvalCase

Disposition = Literal["flag", "clear", "unsure"]
Bucket = Literal["right", "wrong", "not_sure"]

_FLAG = {"real"}
_CLEAR = {"unexploitable", "false_positive"}
_UNSURE = {"needs_review"}
_CLIFF_VOCAB = _FLAG | _CLEAR | _UNSURE
_TRUTH_VOCAB = {"noise", "your-call", "real"}


def disposition(cliff_verdict: str) -> Disposition:
    if cliff_verdict in _FLAG:
        return "flag"
    if cliff_verdict in _CLEAR:
        return "clear"
    if cliff_verdict in _UNSURE:
        return "unsure"
    raise ValueError(f"unknown cliff verdict {cliff_verdict!r} (vocab: {sorted(_CLIFF_VOCAB)})")


def classify(cliff_verdict: str, ground_truth: str) -> Bucket:
    if ground_truth not in _TRUTH_VOCAB:
        raise ValueError(f"unknown ground truth {ground_truth!r} (vocab: {sorted(_TRUTH_VOCAB)})")
    disp = disposition(cliff_verdict)
    if ground_truth == "noise":
        return {"clear": "right", "flag": "wrong", "unsure": "not_sure"}[disp]
    if ground_truth == "real":
        return {"flag": "right", "clear": "wrong", "unsure": "not_sure"}[disp]
    # your-call: needs human judgement — flag or hedge is fine; clearing is wrong.
    return {"flag": "right", "unsure": "right", "clear": "wrong"}[disp]


def _is_false_alarm(cliff_verdict: str, ground_truth: str) -> bool:
    return ground_truth == "noise" and disposition(cliff_verdict) == "flag"


def _is_false_clear(cliff_verdict: str, ground_truth: str) -> bool:
    return ground_truth in {"real", "your-call"} and disposition(cliff_verdict) == "clear"


@dataclass(frozen=True)
class Scorecard:
    total: int
    right: int
    wrong: int
    not_sure: int
    false_alarms: int
    false_clears: int

    def _pct(self, n: int) -> float:
        return 100.0 * n / self.total if self.total else 0.0

    @property
    def right_pct(self) -> float:
        return self._pct(self.right)

    @property
    def wrong_pct(self) -> float:
        return self._pct(self.wrong)

    @property
    def not_sure_pct(self) -> float:
        return self._pct(self.not_sure)

    def report(self) -> str:
        return (
            f"{self.total} findings → "
            f"{self.right} right ({self.right_pct:.0f}%), "
            f"{self.wrong} wrong ({self.wrong_pct:.0f}%), "
            f"{self.not_sure} not sure ({self.not_sure_pct:.0f}%)\n"
            f"  wrong breakdown: {self.false_alarms} false alarm(s) (noise→real), "
            f"{self.false_clears} false clear(s) (real/your-call→cleared)"
        )


def score_corpus(pairs: list[tuple[str, str]]) -> Scorecard:
    """Score ``(cliff_verdict, ground_truth)`` pairs into the three buckets."""
    if not pairs:
        raise ValueError("score_corpus got 0 pairs — an empty run must fail, not report 100%.")
    right = wrong = not_sure = false_alarms = false_clears = 0
    for cliff_verdict, ground_truth in pairs:
        bucket = classify(cliff_verdict, ground_truth)
        if bucket == "right":
            right += 1
        elif bucket == "wrong":
            wrong += 1
            if _is_false_alarm(cliff_verdict, ground_truth):
                false_alarms += 1
            if _is_false_clear(cliff_verdict, ground_truth):
                false_clears += 1
        else:
            not_sure += 1
    return Scorecard(
        total=len(pairs),
        right=right,
        wrong=wrong,
        not_sure=not_sure,
        false_alarms=false_alarms,
        false_clears=false_clears,
    )


@dataclass(frozen=True)
class CorpusCaseResult:
    id: str
    cliff_verdict: str
    ground_truth: str
    bucket: str
    fp_class: str | None = None
    scanner: str | None = None


async def run_triage_corpus_eval(
    cases: list[EvalCase],
    *,
    run_pipeline: Callable[[EvalCase, Path], Awaitable[TriageOutput]],
) -> tuple[Scorecard, list[CorpusCaseResult]]:
    """Run *run_pipeline* over each case's staged repo, score the verdicts.

    ``run_pipeline(case, repo_dir) -> TriageOutput`` is injected (a stub in CI;
    ``make_live_deep_dive_pipeline`` in the live baseline). A per-case infra
    failure (checkout/network) is recorded as ``needs_review`` (Not-sure) and
    the run continues — never a silent drop, never a crash.
    """
    if not cases:
        raise ValueError("run_triage_corpus_eval got 0 cases — check the dataset / sample.")
    records: list[CorpusCaseResult] = []
    for case in cases:
        truth = case.corpus_verdict
        if truth is None:
            raise ValueError(f"{case.id}: corpus case has no corpus_verdict")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / "repo"
                if case.repo and case.sha:
                    from cliff.evals.repo_fetch import checkout_at_sha

                    await checkout_at_sha(case.repo, case.sha, repo_dir)
                else:
                    repo_dir.mkdir()
                    for rel, text in (case.files or {}).items():
                        fp = repo_dir / rel
                        fp.parent.mkdir(parents=True, exist_ok=True)
                        fp.write_text(text)
                triage = await run_pipeline(case, repo_dir)
                cliff_verdict = triage.verdict
        except Exception:  # noqa: BLE001 — one case's infra blip must not abort the run
            cliff_verdict = "needs_review"
        records.append(
            CorpusCaseResult(
                id=case.id,
                cliff_verdict=cliff_verdict,
                ground_truth=truth,
                bucket=classify(cliff_verdict, truth),
                fp_class=case.fp_class,
                scanner=case.scanner,
            )
        )
    scorecard = score_corpus([(r.cliff_verdict, r.ground_truth) for r in records])
    return scorecard, records


__all__ = [
    "CorpusCaseResult",
    "Scorecard",
    "classify",
    "disposition",
    "run_triage_corpus_eval",
    "score_corpus",
]
