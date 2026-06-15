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


# ---------------------------------------------------------------------------
# Speculative reachability must never become a confident verdict (the Plan-gate
# bright line). The exposure analyzer reasons about code findings from the file
# PATH, not the file's code — so a hedged "likely reachable … needs verification"
# is speculation, not a confirmed reachable, and must not project to `real`.
# ---------------------------------------------------------------------------

# The real-world false positive: SAST SQLi the analyzer never read, hedged.
_EXPOSURE_HEDGED_REACHABLE = {
    "reachable": "Likely reachable - this is likely part of the search/query "
    "functionality, but the exact call chain needs verification to confirm "
    "user-controlled data reaches this code path.",
    "internet_facing": True,
    "reachability_evidence": "The file path suggests dynamic query construction; "
    "need to trace whether user input flows into the text() parameters.",
}


def test_hedged_reachability_is_not_promoted_to_real() -> None:
    """A dependency finding whose reachability is only *speculated* ("likely …
    needs verification to confirm") must not be classified as a confident
    reachable — it routes to needs_review, never a confident `real`."""
    out = synthesize_triage(_WITH_CVE, _EXPOSURE_HEDGED_REACHABLE)
    assert out.verdict == "needs_review"
    assert out.verdict != "real"


@pytest.mark.parametrize(
    "reachable",
    [
        "Likely reachable - needs verification to confirm",
        "The file path suggests this may be reachable",
        "This appears reachable but the call chain needs analysis",
        "Could be reachable; would need to trace the entry point",
    ],
    ids=["likely-needs-verify", "suggests-may", "appears-needs-analysis", "could-would"],
)
def test_speculative_phrasings_classify_as_uncertain(reachable: str) -> None:
    """Hedge language never yields a confident `real`, regardless of facing."""
    out = synthesize_triage(_WITH_CVE, {"reachable": reachable, "internet_facing": True})
    assert out.verdict != "real"


# ---------------------------------------------------------------------------
# Code/SAST findings: the quick read can't open the flagged file:line, so it
# DEFERS (needs_review → auto-escalates to the file-reading Deep dive). It never
# emits a confident verdict for a code finding from path-level speculation —
# neither a `real` nor a `false_positive`/`unexploitable` clear.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reachable",
    [
        "cannot confirm it is not reachable",
        "probably unreachable but needs verification",
        "appears to have no path, though unverified",
        "likely not reachable, but the call chain is unclear",
    ],
    ids=["cannot-confirm-not", "probably-unreachable", "appears-nopath", "likely-not"],
)
def test_hedged_negative_is_not_confidently_cleared(reachable: str) -> None:
    """A HEDGED negative ("cannot confirm it is not reachable", "appears
    unreachable but unverified") is uncertainty, not a clear no-path — it must
    NOT be confidently cleared as `unexploitable`. Hedging dominates a negative
    substring, so the verdict routes to needs_review."""
    out = synthesize_triage(_WITH_CVE, {"reachable": reachable, "internet_facing": True})
    assert out.verdict != "unexploitable"
    assert out.verdict == "needs_review"


def test_clean_no_path_still_clears_unexploitable() -> None:
    """The fix must not over-trigger: a confident, un-hedged no-path still clears."""
    out = synthesize_triage(
        _WITH_CVE, {"reachable": "No path found from any entrypoint", "internet_facing": False}
    )
    assert out.verdict == "unexploitable"


def test_secret_finding_abstained_defers_not_false_positive() -> None:
    """A `secret` finding has no advisory (the enricher always abstains), so the
    dependency projection would clear it as `false_positive` — false-clearing a
    real leaked secret. Like code, a secret defers to needs_review (the same
    no-advisory-model class)."""
    out = synthesize_triage(
        _ABSTAINED, {"reachable": "unclear", "internet_facing": None}, finding_type="secret"
    )
    assert out.verdict == "needs_review"


def test_secret_finding_speculative_reachable_defers_not_real() -> None:
    out = synthesize_triage(
        _WITH_CVE,
        {"reachable": "Reachable from the public API", "internet_facing": True},
        finding_type="secret",
    )
    assert out.verdict == "needs_review"


def test_code_finding_speculative_reachable_defers_not_real() -> None:
    """The recipe.py false positive: a code finding the analyzer flagged as
    reachable+internet-facing must NOT ship as a confident `real` — it defers."""
    out = synthesize_triage(
        _WITH_CVE,
        {"reachable": "Reachable from the public search API", "internet_facing": True},
        finding_type="code",
    )
    assert out.verdict == "needs_review"
    assert out.exploitability is not None
    assert out.exploitability.exploitable == "unknown"


def test_code_finding_abstained_unknown_defers_not_false_positive() -> None:
    """A code finding with no advisory (always true for SAST) + undetermined
    reachability must NOT be cleared as `false_positive` from the quick read —
    clearing requires a file read (the Deep dive). It defers to needs_review."""
    out = synthesize_triage(
        _ABSTAINED,
        {"reachable": "unclear", "internet_facing": None},
        finding_type="code",
    )
    assert out.verdict == "needs_review"


def test_dependency_finding_still_clears_and_confirms() -> None:
    """The code-finding deferral must not regress dependency triage: a dependency
    finding still projects to its terminal verdicts (default type='dependency')."""
    real = synthesize_triage(
        _WITH_CVE,
        {"reachable": "Reachable from the public upload API", "internet_facing": True},
        finding_type="dependency",
    )
    assert real.verdict == "real"
    fp = synthesize_triage(_ABSTAINED, {"reachable": "unclear", "internet_facing": None})
    assert fp.verdict == "false_positive"  # default finding_type is 'dependency'
