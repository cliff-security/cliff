"""Live lane for the report_triager eval (ADR-0050 §5 Lane 2 / ADR-0051 §4).

Runs the REAL report triager over the report dataset and scores it. Skipped
automatically when no API key is set (this file is in ``_LIVE_LLM_FILES`` —
see ``conftest.py``); never masks a deterministic lane.

Hard gates (zero tolerance): ``tool_trace`` (read-only tool surface) +
false-clear of a ``real`` report + abstention on the cites-nonexistent-code
case. Graded: exact verdict match must clear a dataset-wide floor.

Budget: ~3 LLM calls with a couple of small file reads each — well under the
ADR-0051 §Evaluation per-case ceiling.
"""

from __future__ import annotations

from cliff.evals import load_cases, run_report_triager_eval
from tests.agents.eval_utils import LLM_ENV as _LLM_ENV
from tests.agents.eval_utils import LLM_MODEL as _LLM_MODEL


async def test_report_triager_eval():
    cases = load_cases("report_triager", tier="live")
    assert cases, "no live cases in the active report_triager dataset"

    result = await run_report_triager_eval(
        cases, env=_LLM_ENV, model_id=_LLM_MODEL, graded_floor=0.6
    )
    assert result.passed, "\n" + result.report()
