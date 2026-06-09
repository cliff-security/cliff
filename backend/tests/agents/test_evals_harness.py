"""CI lane for the eval harness (ADR-0050 §5, Lane 1).

Deterministic, no API key, no real network. Proves the finding_enricher
evaluators + adapter + registry/dataset wiring are correct — so a green CI
means the harness itself won't silently mis-score the live lane.
"""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from cliff.agents.schemas import EnrichmentOutput
from cliff.evals import get_spec, load_cases, run_agent
from cliff.evals.evaluators import (
    check_abstention,
    check_cve_ids,
    check_cvss_within,
    check_no_jargon_title,
    check_reference_liveness,
    check_structural_citations,
)

# --- citation_liveness (the fail-closed gate) --------------------------------


class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeHttp:
    """Stand-in httpx.AsyncClient: every probe returns *status*."""

    def __init__(self, status: int = 200) -> None:
        self._status = status

    async def get(self, url: str, **_kw: object) -> _FakeResp:
        return _FakeResp(self._status)

    async def aclose(self) -> None:  # pragma: no cover - never owns the client
        pass


async def test_structural_gate_fails_on_fabricated_github_sha():
    """A garbled commit SHA is structurally bogus → dropped in the no-network
    sanitize pass → the HARD gate FAILS (the agent fabricated a citation)."""
    out = EnrichmentOutput(
        normalized_title="x",
        references=["https://github.com/foo/bar/commit/zzzzzzz"],
    )
    passed, reason = await check_structural_citations(out)
    assert passed is False
    assert "fabricated" in reason


async def test_liveness_graded_separates_dead_link_from_fabrication():
    """A plausible URL that 404s is a GRADED dead-link, NOT a structural-gate
    failure — the key distinction the live eval taught us."""
    out = EnrichmentOutput(
        normalized_title="x", references=["https://example.com/moved-page"]
    )
    # structural gate passes (the URL is well-formed)...
    structural_ok, _ = await check_structural_citations(out, http=_FakeHttp(404))
    assert structural_ok is True
    # ...but the graded liveness check flags the 404.
    live_ok, reason = await check_reference_liveness(out, http=_FakeHttp(404))
    assert live_ok is False
    assert "dead links" in reason


async def test_both_gates_pass_for_live_and_empty():
    live = EnrichmentOutput(
        normalized_title="x",
        references=["https://nvd.nist.gov/vuln/detail/CVE-2021-44228"],
    )
    assert (await check_structural_citations(live, http=_FakeHttp(200)))[0] is True
    assert (await check_reference_liveness(live, http=_FakeHttp(200)))[0] is True
    empty = EnrichmentOutput(normalized_title="x", references=[])
    assert (await check_structural_citations(empty))[0] is True
    assert (await check_reference_liveness(empty))[0] is True


# --- deterministic field evaluators ------------------------------------------


def test_cve_ids_set_match_case_insensitive():
    out = EnrichmentOutput(normalized_title="x", cve_ids=["cve-2021-44228"])
    assert check_cve_ids(out, {"cve_ids": ["CVE-2021-44228"]})[0] is True
    assert check_cve_ids(out, {"cve_ids": ["CVE-2020-8203"]})[0] is False


def test_cvss_within_tolerance_and_range_and_null():
    out = EnrichmentOutput(normalized_title="x", cvss_score=9.8)
    assert check_cvss_within(out, {"cvss_score": 10.0})[0] is True  # within ±0.5
    assert check_cvss_within(out, {"cvss_score": 7.0})[0] is False
    assert check_cvss_within(out, {"cvss_min": 9.0, "cvss_max": 10.0})[0] is True
    null_out = EnrichmentOutput(normalized_title="x", cvss_score=None)
    assert check_cvss_within(null_out, {"cvss_score": None})[0] is True


def test_no_jargon_title_flags_scanner_ids():
    clean = EnrichmentOutput(normalized_title="Prototype pollution in lodash")
    assert check_no_jargon_title(clean)[0] is True
    jargon = EnrichmentOutput(
        normalized_title="SNYK-JS-LODASH-1018905: Prototype Pollution"
    )
    assert check_no_jargon_title(jargon)[0] is False


def test_abstention_rejects_invented_cve_or_cvss():
    abstained = EnrichmentOutput(normalized_title="x", cve_ids=[], cvss_score=None)
    assert check_abstention(abstained)[0] is True
    invented_cve = EnrichmentOutput(normalized_title="x", cve_ids=["CVE-2026-99999"])
    assert check_abstention(invented_cve)[0] is False
    invented_cvss = EnrichmentOutput(normalized_title="x", cvss_score=7.5)
    assert check_abstention(invented_cvss)[0] is False


# --- adapter + registry + dataset wiring -------------------------------------


async def test_adapter_runs_enricher_via_testmodel():
    """run_agent builds + drives the real enricher agent; TestModel synthesises
    a schema-valid EnrichmentOutput so the wiring is exercised without a key."""
    spec = get_spec("finding_enricher")
    out = await run_agent(spec, {"title": "x", "description": "y"}, model=TestModel())
    assert isinstance(out, EnrichmentOutput)


def test_dataset_loads_and_assertions_are_supported():
    spec = get_spec("finding_enricher")
    cases = load_cases("finding_enricher")
    assert len(cases) >= 5
    assert {c.id for c in cases} >= {"log4shell", "semgrep-no-cve-eval"}
    # every abstain case declares an empty expected cve_ids (abstention contract)
    for c in cases:
        if c.abstain:
            assert c.expected.cve_ids == []
    # registry advertises exactly the assertion families this agent's evaluators
    # implement (ADR-0050 §1: dataset assertions ⊆ supported_assertions)
    assert spec.supported_assertions == frozenset(
        {"citation_liveness", "cve_ids", "cvss_within", "no_jargon_title", "abstention"}
    )
    assert spec.abstention_required is True
