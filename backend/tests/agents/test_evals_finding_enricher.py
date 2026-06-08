"""Live lane for the finding_enricher eval (ADR-0050 §5, Lane 2).

Runs the REAL enricher over ``eval/finding_enricher.jsonl`` and scores the
output. Skipped automatically when no API key is set (see ``conftest.py`` —
this file is in ``_LIVE_LLM_FILES``); never masks the deterministic CI lane.

Two classes of check (ADR-0050 §3):

* **Hard gates — zero tolerance.** ``citation_liveness`` (real network HEAD via
  the production verifier) on every case, and ``abstention`` on every case
  flagged ``abstain``. A single failure fails the run: a fabricated citation
  or an invented CVE/CVSS is the load-bearing failure mode.
* **Graded — aggregate threshold.** ``cve_ids`` / ``cvss_within`` /
  ``no_jargon_title`` are accuracy metrics; we assert the dataset-wide pass
  rate clears a floor rather than demanding every case (reasonable models
  defensibly miss a CVE id now and then).

Budget: ~6 LLM calls + a few HTTP HEADs, well under the registry's per-case
ceiling. Tune ``_GRADED_FLOOR`` as the golden set grows.
"""

from __future__ import annotations

from cliff.evals import get_spec, load_cases, run_agent
from cliff.evals.evaluators import (
    assess_references,
    check_abstention,
    check_cve_ids,
    check_cvss_within,
    check_no_jargon_title,
)
from tests.agents.eval_utils import LLM_ENV as _LLM_ENV
from tests.agents.eval_utils import LLM_MODEL as _LLM_MODEL

_GRADED_FLOOR = 0.6  # dataset-wide pass-rate floor for accuracy metrics


async def test_finding_enricher_eval():
    spec = get_spec("finding_enricher")
    cases = load_cases("finding_enricher", tier="live")
    assert cases, "no live cases in finding_enricher.jsonl"

    hard_failures: list[str] = []
    graded: dict[str, list[bool]] = {
        "cve_ids": [],
        "cvss_within": [],
        "no_jargon_title": [],
        "reference_liveness": [],
    }

    for case in cases:
        out = await run_agent(
            spec, case.finding, env=_LLM_ENV, model_id=_LLM_MODEL
        )

        # One verifier pass per case → classify structural vs dead-link drops.
        refs = await assess_references(out)

        # Hard gate (zero tolerance): no STRUCTURALLY-fabricated citation
        # (fake GHSA id / garbled SHA / non-http). Dead-link 404s are graded
        # below, not a hard fail (production strips them; even good models
        # occasionally guess a doc URL that has moved).
        if refs.structural:
            bad = "; ".join(f"{u} ({why})" for u, why in refs.structural)
            hard_failures.append(f"{case.id}: structural_citations — {bad}")

        # Hard gate: declines on no-CVE / fabrication-bait cases.
        if case.abstain:
            ab_ok, ab_reason = check_abstention(out)
            if not ab_ok:
                hard_failures.append(f"{case.id}: abstention — {ab_reason}")

        # Graded accuracy metrics.
        graded["cve_ids"].append(check_cve_ids(out, case.expected)[0])
        graded["cvss_within"].append(check_cvss_within(out, case.expected)[0])
        graded["no_jargon_title"].append(check_no_jargon_title(out)[0])
        graded["reference_liveness"].append(not refs.network)

    assert not hard_failures, "Zero-tolerance hard-gate failures:\n" + "\n".join(
        hard_failures
    )

    below: list[str] = []
    for metric, results in graded.items():
        rate = sum(results) / len(results)
        if rate < _GRADED_FLOOR:
            below.append(f"{metric}: {rate:.0%} < {_GRADED_FLOOR:.0%}")
    assert not below, "Graded metric(s) below floor:\n" + "\n".join(below)
