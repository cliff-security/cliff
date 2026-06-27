"""Corpus eval cases carry 3-way ground truth (ADR-0050 triage corpus)."""
from cliff.evals.cases import EvalCase


def test_corpus_fields_optional_and_default_none():
    # An existing-style case still loads (back-compat).
    c = EvalCase(id="legacy", finding={})
    assert c.corpus_verdict is None
    assert c.fp_class is None
    assert c.scanner is None


def test_corpus_case_round_trips():
    c = EvalCase.model_validate(
        {
            "id": "f1",
            "tier": "live",
            "finding": {"title": "x", "type": "code"},
            "repo": "https://github.com/o/r",
            "sha": "abc123",
            "corpus_verdict": "noise",
            "fp_class": "test-only",
            "scanner": "snyk-code",
        }
    )
    assert c.corpus_verdict == "noise"
    assert c.fp_class == "test-only"
    assert c.scanner == "snyk-code"


def test_corpus_verdict_rejects_unknown_value():
    import pytest

    with pytest.raises(ValueError):
        EvalCase.model_validate({"id": "f", "finding": {}, "corpus_verdict": "bogus"})
