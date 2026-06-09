"""Report triager trust boundary + report-source tagging (ADR-0051 §4/§8).

Keyless — these assert the *shape* of the report triager (its tool surface and
output type) and the normalizer's report tagging, none of which need an LLM.
The live behaviour (verdict quality, claim-vs-code grounding) is the key-gated
eval in ``test_evals_report_triager.py``.
"""

from __future__ import annotations

from cliff.agents.runtime.report_triager import (
    REPORT_TRIAGER_TOOLS,
    build_agent,
)
from cliff.agents.runtime.tools import bash, edit, gh, read, webfetch
from cliff.agents.schemas import AGENT_OUTPUT_SCHEMAS, TriageOutput
from cliff.integrations.normalizer import REPORT_SOURCE_TYPE, _resolve_source_type


def test_report_triager_tool_surface_is_read_only() -> None:
    """The report triager's COMPLETE tool surface is the read tool — it can
    never mutate the repo, close the report, push, or reach the network
    (ADR-0051 §8 trust boundary / the `tool_trace` HARD gate)."""
    assert len(REPORT_TRIAGER_TOOLS) == 1
    assert REPORT_TRIAGER_TOOLS[0] is read
    for forbidden in (bash, edit, gh, webfetch):
        assert forbidden not in REPORT_TRIAGER_TOOLS, (
            f"{forbidden.__name__} must not be in the report triager's tools"
        )


def test_report_triager_builds_with_triage_output() -> None:
    """It can be constructed (the executor builds it per-run) and emits the
    shared TriageOutput contract."""
    from pydantic_ai.models.test import TestModel

    agent = build_agent(TestModel())
    assert agent is not None
    assert AGENT_OUTPUT_SCHEMAS["report_triager"] is TriageOutput


def test_report_import_is_always_tagged_report() -> None:
    """A report import is force-tagged source_type='report' so triage routes
    it to the report triager — even if the model guessed a scanner name."""
    assert REPORT_SOURCE_TYPE == "report"
    assert _resolve_source_type("report", None) == "report"
    assert _resolve_source_type("report", "snyk") == "report"


def test_scanner_source_type_preserved() -> None:
    assert _resolve_source_type("snyk", "snyk") == "snyk"
    assert _resolve_source_type("snyk", None) == "snyk"
    assert _resolve_source_type("trivy", "trivy-secret") == "trivy-secret"
