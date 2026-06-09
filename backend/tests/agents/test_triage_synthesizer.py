"""The deterministic scanner triage synthesizer (ADR-0051 §3 / IMPL-0024 V1-3).

``synthesize_triage`` is a pure function over recorded ``EnrichmentOutput`` +
``ExposureOutput`` — no LLM, $0, runs in keyless CI. These tests pin the full
ADR-0051 §3 mapping matrix and the ADR-0051 §9 ``needs_review`` threshold.

Safety note (the asymmetric gate): the mapping is reachability-first, so a
finding the exposure analyzer reports as *reachable* is never closed as
``false_positive`` even when the enricher abstained — false-clearing a real
finding is the load-bearing failure (ADR-0051 §10).
"""

from __future__ import annotations

import pytest

from cliff.agents.runtime.triage_synthesizer import synthesize_triage
from cliff.agents.schemas import TriageOutput

# Enrichment fixtures.
_WITH_CVE = {
    "normalized_title": "RCE in libfoo",
    "cve_ids": ["CVE-2026-0001"],
    "cvss_score": 9.1,
    "known_exploits": False,
}
_WITH_CVE_KNOWN_EXPLOIT = {**_WITH_CVE, "known_exploits": True}
_ABSTAINED = {  # enricher found no public advisory substantiating a real vuln
    "normalized_title": "Suspicious string in config",
    "cve_ids": [],
    "cvss_score": None,
    "known_exploits": False,
}


# (label, enrichment, exposure, expected_verdict, expected_close)
_MATRIX = [
    (
        "air-gapped, clear no-path → unexploitable",
        _WITH_CVE,
        {"reachable": "No path found from any entrypoint", "internet_facing": False},
        "unexploitable",
        "unexploitable",
    ),
    (
        "not reachable, facing unknown → unexploitable",
        _WITH_CVE,
        {"reachable": "not reachable", "internet_facing": None},
        "unexploitable",
        "unexploitable",
    ),
    (
        "reachable + internet-facing → real",
        _WITH_CVE,
        {"reachable": "Reachable from the public upload API", "internet_facing": True},
        "real",
        None,
    ),
    (
        "reachable but internal only → needs_review (deployment-dependent)",
        _WITH_CVE,
        {"reachable": "reachable", "internet_facing": False},
        "needs_review",
        None,
    ),
    (
        "reachable, facing unknown → needs_review (unknown-provenance SSTI)",
        _WITH_CVE,
        {"reachable": "reachable", "internet_facing": None},
        "needs_review",
        None,
    ),
    (
        "reachability undetermined, real advisory → needs_review",
        _WITH_CVE,
        {"reachable": "unknown", "internet_facing": True},
        "needs_review",
        None,
    ),
    (
        "enricher abstained + reachability unknown → false_positive",
        _ABSTAINED,
        {"reachable": "unclear", "internet_facing": None},
        "false_positive",
        "false_positive",
    ),
    (
        "enricher abstained + clear no-path → unexploitable (reachability wins)",
        _ABSTAINED,
        {"reachable": "no path", "internet_facing": False},
        "unexploitable",
        "unexploitable",
    ),
    (
        "enricher abstained but reachable+facing → real (never false-clear)",
        _ABSTAINED,
        {"reachable": "reachable", "internet_facing": True},
        "real",
        None,
    ),
    (
        "missing exposure → needs_review (never a confident clear)",
        _WITH_CVE,
        None,
        "needs_review",
        None,
    ),
]


@pytest.mark.parametrize(
    "label,enrichment,exposure,expected_verdict,expected_close",
    _MATRIX,
    ids=[c[0] for c in _MATRIX],
)
def test_synthesis_mapping_matrix(
    label, enrichment, exposure, expected_verdict, expected_close
) -> None:
    out = synthesize_triage(enrichment, exposure)
    assert isinstance(out, TriageOutput)
    assert out.verdict == expected_verdict, label
    assert out.recommended_close == expected_close, label


def test_needs_review_iff_low_confidence_or_unknown_exploitability() -> None:
    """ADR-0051 §9 invariant: a verdict is ``needs_review`` exactly when
    confidence < 0.70 OR exploitability is unknown; every confident verdict
    (real/unexploitable/false_positive) is ≥ 0.70 with a definite
    exploitability or none."""
    for _label, enrichment, exposure, _v, _c in _MATRIX:
        out = synthesize_triage(enrichment, exposure)
        exploit_unknown = (
            out.exploitability is not None and out.exploitability.exploitable == "unknown"
        )
        low_conf = out.confidence < 0.70
        if out.verdict == "needs_review":
            assert low_conf or exploit_unknown, _label
        else:
            assert not low_conf, f"{_label}: confident verdict must be ≥0.70"
            assert not exploit_unknown, f"{_label}: confident verdict can't be unknown"


def test_known_exploit_raises_confidence_on_real() -> None:
    exposure = {"reachable": "reachable from public API", "internet_facing": True}
    base = synthesize_triage(_WITH_CVE, exposure)
    boosted = synthesize_triage(_WITH_CVE_KNOWN_EXPLOIT, exposure)
    assert base.verdict == boosted.verdict == "real"
    assert boosted.confidence > base.confidence


def test_internet_facing_known_raises_confidence_on_unexploitable() -> None:
    known = synthesize_triage(
        _WITH_CVE, {"reachable": "no path found", "internet_facing": False}
    )
    unknown = synthesize_triage(
        _WITH_CVE, {"reachable": "no path found", "internet_facing": None}
    )
    assert known.verdict == unknown.verdict == "unexploitable"
    assert known.confidence > unknown.confidence


def test_no_path_state_sets_reachability_reached_false_with_empty_path() -> None:
    out = synthesize_triage(
        _WITH_CVE, {"reachable": "No path found", "internet_facing": False}
    )
    assert out.reachability is not None
    assert out.reachability.reached is False
    assert out.reachability.path == []


def test_reachable_state_sets_reachability_reached_true() -> None:
    out = synthesize_triage(
        _WITH_CVE,
        {
            "reachable": "reachable",
            "internet_facing": True,
            "reachability_evidence": "upload() → parse() → deserialize()",
        },
    )
    assert out.reachability is not None
    assert out.reachability.reached is True
    assert out.reachability.summary == "upload() → parse() → deserialize()"


def test_output_always_has_proof_checks() -> None:
    for _label, enrichment, exposure, _v, _c in _MATRIX:
        out = synthesize_triage(enrichment, exposure)
        assert out.checks, f"{_label}: synthesis must emit at least one proof row"
        assert all(c.kind in {"pass", "warn", "fail", "info"} for c in out.checks)
