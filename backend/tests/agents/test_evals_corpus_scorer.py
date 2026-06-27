"""The triage corpus scorer (ADR-0050) — three buckets, pure + keyless."""
import pytest

from cliff.evals.corpus import classify, disposition, score_corpus


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("real", "flag"),
        ("unexploitable", "clear"),
        ("false_positive", "clear"),
        ("needs_review", "unsure"),
    ],
)
def test_disposition(verdict, expected):
    assert disposition(verdict) == expected


@pytest.mark.parametrize(
    "cliff,truth,bucket",
    [
        # noise: clearing is right, flagging is the false alarm, hedging is unsure
        ("false_positive", "noise", "right"),
        ("unexploitable", "noise", "right"),
        ("real", "noise", "wrong"),  # false alarm
        ("needs_review", "noise", "not_sure"),
        # real: flagging is right, clearing is the false clear, hedging is unsure
        ("real", "real", "right"),
        ("false_positive", "real", "wrong"),  # false clear
        ("needs_review", "real", "not_sure"),
        # your-call: unsure OR flag is right; clearing it is a false clear
        ("needs_review", "your-call", "right"),
        ("real", "your-call", "right"),
        ("false_positive", "your-call", "wrong"),  # false clear
        ("unexploitable", "your-call", "wrong"),
    ],
)
def test_classify(cliff, truth, bucket):
    assert classify(cliff, truth) == bucket


def test_classify_rejects_unknown_inputs():
    with pytest.raises(ValueError):
        classify("bogus", "noise")
    with pytest.raises(ValueError):
        classify("real", "bogus")


def test_score_corpus_counts_and_subtypes():
    pairs = [
        ("false_positive", "noise"),   # right
        ("unexploitable", "noise"),    # right
        ("needs_review", "noise"),     # not_sure
        ("real", "noise"),             # wrong — false alarm
        ("false_positive", "your-call"),  # wrong — false clear
        ("needs_review", "your-call"),    # right
    ]
    sc = score_corpus(pairs)
    assert sc.total == 6
    assert sc.right == 3
    assert sc.wrong == 2
    assert sc.not_sure == 1
    assert sc.false_alarms == 1
    assert sc.false_clears == 1
    assert round(sc.right_pct) == 50


def test_score_corpus_empty_raises():
    with pytest.raises(ValueError):
        score_corpus([])


def test_report_renders_three_buckets():
    sc = score_corpus([("false_positive", "noise"), ("real", "noise")])
    text = sc.report()
    assert "2 findings" in text
    assert "right" in text and "wrong" in text and "not sure" in text
    assert "false alarm" in text
