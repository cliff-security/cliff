"""run_triage_corpus_eval drives a pipeline over staged cases + scores it."""
from cliff.agents.schemas import TriageOutput
from cliff.evals.cases import EvalCase
from cliff.evals.corpus import run_triage_corpus_eval


def _case(cid, truth, files):
    return EvalCase.model_validate(
        {"id": cid, "tier": "ci", "finding": {"t": cid}, "files": files, "corpus_verdict": truth}
    )


def _stub(outputs):
    async def _run(case, repo_dir):
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
    cases = [_case("boom", "noise", {"x.py": "p\n"})]

    async def _explode(case, repo_dir):
        raise RuntimeError("checkout blew up")

    sc, records = await run_triage_corpus_eval(cases, run_pipeline=_explode)
    assert sc.total == 1 and sc.not_sure == 1
    assert records[0].cliff_verdict == "needs_review"
