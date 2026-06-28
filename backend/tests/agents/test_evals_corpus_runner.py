"""run_triage_corpus_eval drives a pipeline over staged cases + scores it."""
import pytest

from cliff.agents.schemas import TriageOutput
from cliff.evals.cases import EvalCase
from cliff.evals.corpus import run_triage_corpus_eval


def _case(cid, truth, files):
    return EvalCase.model_validate(
        {"id": cid, "tier": "ci", "finding": {"t": cid}, "files": files, "corpus_verdict": truth}
    )


def _stub(outputs):
    async def _run(case, repo_dir):
        # Assert that the runner actually staged the declared files into repo_dir
        # so the test catches a regression where staging is silently skipped.
        for rel, expected_text in (case.files or {}).items():
            staged = repo_dir / rel
            assert staged.exists(), f"staged file {rel!r} missing under repo_dir"
            assert staged.read_text() == expected_text, f"staged file {rel!r} has wrong content"
        return outputs[case.id]

    return _run


async def test_runner_scores_staged_cases():
    cases = [
        _case("a", "noise", {"x.py": "p\n"}),
        _case("b", "noise", {"x.py": "p\n"}),
    ]
    outs = {"a": TriageOutput(verdict="false_positive", confidence=0.9),
            "b": TriageOutput(verdict="real", confidence=0.9)}
    sc, records = await run_triage_corpus_eval(cases, run_pipeline=_stub(outs))
    assert sc.total == 2
    assert sc.right == 1 and sc.wrong == 1 and sc.false_alarms == 1
    assert {r.id: r.bucket for r in records} == {"a": "right", "b": "wrong"}


async def test_runner_infra_error_counts_not_sure():
    """Infra error → not_sure, but the loop must continue past it to score the next case."""
    cases = [
        _case("boom", "noise", {"x.py": "p\n"}),
        _case("ok", "real", {"x.py": "p\n"}),
    ]

    async def _explode_then_succeed(case, repo_dir):
        if case.id == "boom":
            raise RuntimeError("checkout blew up")
        return TriageOutput(verdict="real", confidence=0.9)

    sc, records = await run_triage_corpus_eval(cases, run_pipeline=_explode_then_succeed)
    assert sc.total == 2
    assert sc.not_sure == 1 and sc.right == 1
    by_id = {r.id: r for r in records}
    assert by_id["boom"].cliff_verdict == "needs_review"
    assert by_id["boom"].bucket == "not_sure"
    assert by_id["ok"].cliff_verdict == "real"
    assert by_id["ok"].bucket == "right"


async def test_runner_empty_cases_raises():
    with pytest.raises(ValueError):
        await run_triage_corpus_eval([], run_pipeline=_stub({}))


async def test_runner_missing_corpus_verdict_raises():
    # A case with no corpus_verdict is a data-contract violation — must raise,
    # not be silently scored.
    case = EvalCase.model_validate(
        {"id": "x", "tier": "ci", "finding": {}, "files": {"a.py": "p\n"}}
    )
    with pytest.raises(ValueError):
        await run_triage_corpus_eval([case], run_pipeline=_stub({}))
