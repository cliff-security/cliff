"""Tests for the TriageOutput contract (ADR-0051 §2 / IMPL-0024 §3.3).

TriageOutput is the single schema both triage producers emit — the
deterministic scanner ``triage_synthesizer`` and the LLM ``report_triager`` —
and the V1↔V2 seam the frontend consumes. The verdict↔recommended_close
pairing is a HARD invariant (ADR-0051 §2): it is filled from the verdict when
omitted and rejected when it contradicts the verdict.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cliff.agents.schemas import AGENT_OUTPUT_SCHEMAS, TriageOutput


class TestTriageOutputSchema:
    def test_scanner_verdict_round_trips(self) -> None:
        out = TriageOutput(
            verdict="real",
            confidence=0.92,
            reachability={
                "reached": True,
                "path": [
                    {"label": "your upload handler", "kind": "entrypoint"},
                    {"label": "vulnerable sink", "kind": "sink"},
                ],
                "summary": "Untrusted upload reaches the deserialize call.",
            },
            exploitability={"exploitable": "yes", "reason": "attacker-controlled bytes"},
            checks=[
                {"eyebrow": "REACHABILITY", "result": "Reachable", "kind": "fail",
                 "detail": "2-hop path from the upload handler"},
            ],
        )
        dumped = out.model_dump()
        assert dumped["verdict"] == "real"
        assert dumped["recommended_close"] is None
        assert dumped["report"] is None

        again = TriageOutput.model_validate(dumped)
        assert again.reachability is not None
        assert again.reachability.reached is True
        assert again.reachability.path[0].label == "your upload handler"
        assert again.exploitability is not None
        assert again.exploitability.exploitable == "yes"
        assert again.checks[0].eyebrow == "REACHABILITY"

    def test_no_path_found_reachability_round_trips(self) -> None:
        out = TriageOutput(
            verdict="unexploitable",
            confidence=0.86,
            reachability={"reached": False, "path": [], "summary": "No path found."},
            exploitability={"exploitable": "no", "reason": "vulnerable function never called"},
        )
        again = TriageOutput.model_validate(out.model_dump())
        assert again.reachability is not None
        assert again.reachability.reached is False
        assert again.reachability.path == []
        assert again.recommended_close == "unexploitable"

    @pytest.mark.parametrize(
        "verdict,expected",
        [
            ("real", None),
            ("needs_review", None),
            ("false_positive", "false_positive"),
            ("unexploitable", "unexploitable"),
        ],
    )
    def test_recommended_close_filled_from_verdict(self, verdict, expected) -> None:
        out = TriageOutput(verdict=verdict, confidence=0.5)
        assert out.recommended_close == expected

    @pytest.mark.parametrize(
        "verdict,bad",
        [
            ("real", "unexploitable"),
            ("real", "false_positive"),
            ("needs_review", "unexploitable"),
            ("unexploitable", "false_positive"),
            ("false_positive", "unexploitable"),
        ],
    )
    def test_incoherent_recommended_close_rejected(self, verdict, bad) -> None:
        with pytest.raises(ValidationError):
            TriageOutput(verdict=verdict, confidence=0.5, recommended_close=bad)

    def test_explicit_coherent_close_accepted(self) -> None:
        out = TriageOutput(
            verdict="unexploitable", confidence=0.8, recommended_close="unexploitable"
        )
        assert out.recommended_close == "unexploitable"

    def test_out_of_vocab_verdict_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriageOutput(verdict="probably_fine", confidence=0.5)

    @pytest.mark.parametrize("conf", [-0.1, 1.1])
    def test_confidence_out_of_range_rejected(self, conf) -> None:
        with pytest.raises(ValidationError):
            TriageOutput(verdict="real", confidence=conf)

    def test_report_block_round_trips(self) -> None:
        out = TriageOutput(
            verdict="false_positive",
            confidence=0.81,
            report={
                "claim": "RCE via eval() in utils.py",
                "claim_vs_code": {
                    "file": "utils.py",
                    "claimed": "eval(user_input)",
                    "actual": "ast.literal_eval(user_input)",
                    "assessment": "Cited line uses a safe parser, not eval.",
                },
                "duplicate": False,
                "poc_present": False,
                "ai_slop_signals": ["no concrete PoC", "generic CVE prose"],
                "drafted_reply": "Thanks for the report — the cited line uses ast.literal_eval.",
            },
        )
        d = out.model_dump()
        assert d["report"]["claim_vs_code"]["actual"] == "ast.literal_eval(user_input)"
        assert d["report"]["ai_slop_signals"] == ["no concrete PoC", "generic CVE prose"]
        assert d["recommended_close"] == "false_positive"

    def test_report_triager_registered_with_triage_schema(self) -> None:
        assert AGENT_OUTPUT_SCHEMAS["report_triager"] is TriageOutput
