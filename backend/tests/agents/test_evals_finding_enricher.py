"""Live lane for the finding_enricher eval (ADR-0050 §5, Lane 2).

Runs the REAL enricher over the active dataset (the public synthetic sample by
default; the private ``cliff-os/eval`` datasets when ``CLIFF_EVAL_DATASET_DIR``
is set — ADR-0050 hybrid) and scores it via the shared ``run_enricher_eval``
loop. Skipped automatically when no API key is set (see ``conftest.py`` — this
file is in ``_LIVE_LLM_FILES``); never masks the deterministic CI lane.

Hard gates (zero tolerance): structural citation fabrication on every case +
abstention on every ``abstain`` case. Graded metrics (cve_ids / cvss_within /
no_jargon_title / reference_liveness) must clear a dataset-wide floor.

Budget: a handful of LLM calls + HTTP HEADs, well under the registry ceiling.
"""

from __future__ import annotations

from cliff.evals import load_cases, run_enricher_eval
from tests.agents.eval_utils import LLM_ENV as _LLM_ENV
from tests.agents.eval_utils import LLM_MODEL as _LLM_MODEL


async def test_finding_enricher_eval():
    cases = load_cases("finding_enricher", tier="live")
    assert cases, "no live cases in the active finding_enricher dataset"

    result = await run_enricher_eval(
        cases, env=_LLM_ENV, model_id=_LLM_MODEL, graded_floor=0.6
    )
    assert result.passed, "\n" + result.report()
