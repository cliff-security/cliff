"""CI lane for the scanner triage synthesizer eval (ADR-0051 / ADR-0050 §5).

The synthesizer is a pure function, so this lane is fully deterministic, $0,
and keyless — it runs on every push (NOT in ``_LIVE_LLM_FILES``). It proves the
ADR-0051 §3 mapping holds on the golden corpus and that the asymmetric
false-clear gate has teeth.
"""

from __future__ import annotations

from cliff.evals import load_cases, run_triage_synthesis_eval
from cliff.evals.cases import EvalCase


def test_triage_synthesizer_eval_passes() -> None:
    cases = load_cases("triage_synthesizer", tier="ci")
    assert cases, "no CI cases in the triage_synthesizer dataset"

    result = run_triage_synthesis_eval(cases, graded_floor=0.9)
    assert result.passed, "\n" + result.report()
    # The corpus is hand-labeled to match the deterministic mapping exactly.
    assert result.graded_rates["verdict_match"] == 1.0, "\n" + result.report()


def test_false_clear_gate_has_teeth() -> None:
    """A mislabeled case — a clearly-unreachable finding labeled ``real`` —
    must trip the zero-tolerance false-clear HARD gate, proving the gate
    actually fails the run rather than rubber-stamping."""
    mislabeled = EvalCase.model_validate(
        {
            "id": "mislabeled-real",
            "tier": "ci",
            "finding": {
                "enrichment": {"cve_ids": ["CVE-2026-9999"], "cvss_score": 9.0},
                "exposure": {"reachable": "No path found", "internet_facing": False},
            },
            "expected": {"verdict": "real"},
        }
    )
    result = run_triage_synthesis_eval([mislabeled], graded_floor=0.9)
    assert not result.passed
    assert any("FALSE-CLEAR" in hf for hf in result.hard_failures), result.report()
