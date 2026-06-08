"""Evaluators for the finding_enricher (ADR-0050 §3).

"Code first, judge last." Everything here is deterministic. The headline gate
is ``citation_liveness``: it reuses the production reference verifier
(``services.reference_verifier.clean_references``) — if that verifier would
*drop* any reference the agent emitted (structurally bogus GHSA/SHA, or a URL
the host 404s), the agent fabricated a citation and the case FAILS. Production
already strips these before the user sees them; the eval measures how often the
model tries.

Each check is a pure ``(passed: bool, reason: str)`` function (clear pytest
messages, trivially unit-tested). The ``pydantic-evals`` ``Evaluator`` wrappers
at the bottom call them so the Dataset/Report path (ADR-0050 §1) works too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cliff.services.reference_verifier import clean_references

# Scanner-specific jargon that a normalized title must not carry (ADR-0040:
# "a human should understand the title without knowing which scanner produced
# it"). Raw rule ids, leading bracket tags, dotted semgrep rule paths.
_JARGON_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bSNYK-[A-Z0-9-]+", re.IGNORECASE),
    re.compile(r"\bGHSA-[a-z0-9]{4}-", re.IGNORECASE),
    re.compile(r"^\s*\[[^\]]+\]"),  # leading "[semgrep] ..." style tag
    re.compile(r"\b[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_.-]+\b"),  # dotted rule path
)


def _norm_cves(values: Any) -> set[str]:
    if not isinstance(values, (list, tuple)):
        return set()
    return {str(v).strip().upper() for v in values if str(v).strip()}


@dataclass
class ReferenceAssessment:
    """Classification of the verifier's dropped references.

    ``structural`` = structurally-impossible (fabricated GHSA id, garbled
    commit SHA, non-http, unsafe IP) — pure fabrication, caught in the
    no-network sanitize pass. ``network`` = a plausible URL the host 404/410s
    — a dead-link guess. They are scored differently (ADR-0050 §3): structural
    is the zero-tolerance hard gate; network is a graded liveness metric.
    """

    structural: list[tuple[str, str]]
    network: list[tuple[str, str]]
    kept: list[str]


async def assess_references(output: Any, *, http: Any = None) -> ReferenceAssessment:
    """Run the production verifier once and classify its drops.

    ``http`` (an ``httpx.AsyncClient``) is injectable so the CI lane can drive
    the network pass deterministically; the live lane leaves it ``None``.
    """
    refs = getattr(output, "references", None)
    check = (
        await clean_references(refs, http=http)
        if http is not None
        else await clean_references(refs)
    )
    structural = [(u, r) for u, r in check.dropped if not r.startswith("http_")]
    network = [(u, r) for u, r in check.dropped if r.startswith("http_")]
    return ReferenceAssessment(structural, network, check.kept)


async def check_structural_citations(output: Any, *, http: Any = None) -> tuple[bool, str]:
    """HARD GATE: FAIL on a structurally-impossible (fabricated) reference."""
    a = await assess_references(output, http=http)
    if a.structural:
        bad = "; ".join(f"{u} ({why})" for u, why in a.structural)
        return False, f"fabricated references: {bad}"
    return True, f"{len(a.kept)} ok, {len(a.network)} dead-link(s)"


async def check_reference_liveness(output: Any, *, http: Any = None) -> tuple[bool, str]:
    """GRADED: FAIL if any reference 404/410s (a plausible-but-dead URL guess —
    production strips these, so this measures the guess rate, not user impact)."""
    a = await assess_references(output, http=http)
    if a.network:
        dead = "; ".join(u for u, _ in a.network)
        return False, f"dead links: {dead}"
    return True, f"all {len(a.kept)} reference(s) live"


def check_cve_ids(output: Any, expected: dict[str, Any]) -> tuple[bool, str]:
    """Exact set match against the golden CVE ids (case-insensitive). No
    ``cve_ids`` key declared → no expectation → pass (the abstention gate, not
    this one, enforces emptiness on no-CVE cases)."""
    if "cve_ids" not in expected:
        return True, "no cve_ids expectation"
    got = _norm_cves(getattr(output, "cve_ids", None))
    want = _norm_cves(expected.get("cve_ids", []))
    if got == want:
        return True, f"cve_ids match ({sorted(want) or 'none'})"
    return False, f"cve_ids mismatch: got {sorted(got)}, expected {sorted(want)}"


def check_cvss_within(
    output: Any, expected: dict[str, Any], *, tol: float = 0.5
) -> tuple[bool, str]:
    """CVSS within ±tol of golden, or inside [cvss_min, cvss_max], or null
    when the case expects abstention. No expectation declared → pass."""
    got = getattr(output, "cvss_score", None)
    if "cvss_score" in expected:
        want = expected["cvss_score"]
        if want is None:
            return (got is None), f"cvss expected null, got {got}"
        if got is None:
            return False, f"cvss expected ~{want}, got null"
        ok = abs(float(got) - float(want)) <= tol
        return ok, f"cvss {got} vs {want} (±{tol})"
    if "cvss_min" in expected or "cvss_max" in expected:
        lo = expected.get("cvss_min", 0.0)
        hi = expected.get("cvss_max", 10.0)
        if got is None:
            return False, f"cvss expected in [{lo},{hi}], got null"
        return (lo <= float(got) <= hi), f"cvss {got} in [{lo},{hi}]"
    return True, "no cvss expectation"


def check_no_jargon_title(output: Any) -> tuple[bool, str]:
    """normalized_title must carry no scanner jargon."""
    title = getattr(output, "normalized_title", None)
    if not isinstance(title, str) or not title.strip():
        return False, "normalized_title missing/empty"
    for pat in _JARGON_PATTERNS:
        m = pat.search(title)
        if m:
            return False, f"title contains scanner jargon {m.group(0)!r}: {title!r}"
    return True, "title clean"


def check_abstention(output: Any) -> tuple[bool, str]:
    """For a no-CVE / post-cutoff case: no invented CVE id and no invented
    CVSS score (the agent must decline rather than fabricate)."""
    cves = _norm_cves(getattr(output, "cve_ids", None))
    cvss = getattr(output, "cvss_score", None)
    if cves:
        return False, f"should abstain but invented cve_ids {sorted(cves)}"
    if cvss is not None:
        return False, f"should abstain but invented cvss_score {cvss}"
    return True, "abstained (no invented CVE/CVSS)"


# --- pydantic-evals Evaluator wrappers (Dataset/Report path) -----------------

try:  # pydantic-evals is an optional [evals] extra; degrade if absent
    from pydantic_evals.evaluators import Evaluator, EvaluatorContext

    @dataclass
    class StructuralCitations(Evaluator):
        """Hard gate — no fabricated (structurally-impossible) references."""

        async def evaluate(self, ctx: EvaluatorContext) -> bool:
            passed, _ = await check_structural_citations(ctx.output)
            return passed

    @dataclass
    class ReferenceLiveness(Evaluator):
        """Graded — no dead-link (404/410) references."""

        async def evaluate(self, ctx: EvaluatorContext) -> bool:
            passed, _ = await check_reference_liveness(ctx.output)
            return passed

    @dataclass
    class CveIds(Evaluator):
        async def evaluate(self, ctx: EvaluatorContext) -> bool:
            return check_cve_ids(ctx.output, ctx.expected_output or {})[0]

    @dataclass
    class CvssWithin(Evaluator):
        tol: float = 0.5

        async def evaluate(self, ctx: EvaluatorContext) -> bool:
            return check_cvss_within(ctx.output, ctx.expected_output or {}, tol=self.tol)[0]

    @dataclass
    class NoJargonTitle(Evaluator):
        async def evaluate(self, ctx: EvaluatorContext) -> bool:
            return check_no_jargon_title(ctx.output)[0]

    @dataclass
    class Abstention(Evaluator):
        """Only meaningful on cases flagged ``abstain`` in metadata."""

        async def evaluate(self, ctx: EvaluatorContext) -> bool:
            if not (ctx.metadata or {}).get("abstain"):
                return True
            return check_abstention(ctx.output)[0]

    _HAS_PYDANTIC_EVALS = True
except ImportError:  # pragma: no cover
    _HAS_PYDANTIC_EVALS = False


__all__ = [
    "ReferenceAssessment",
    "assess_references",
    "check_abstention",
    "check_cve_ids",
    "check_cvss_within",
    "check_no_jargon_title",
    "check_reference_liveness",
    "check_structural_citations",
]
