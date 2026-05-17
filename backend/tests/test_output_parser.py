"""Tests for the agent output parser."""

from __future__ import annotations

import json

from cliff.agents.output_parser import (
    extract_json_block,
    parse_agent_response,
    validate_structured_output,
)

# ---------------------------------------------------------------------------
# extract_json_block
# ---------------------------------------------------------------------------


class TestExtractJsonBlock:
    def test_json_in_fenced_block(self):
        text = 'Some preamble\n```json\n{"key": "value"}\n```\nMore text'
        result = extract_json_block(text)
        assert result == {"key": "value"}

    def test_json_in_plain_fence(self):
        text = 'Preamble\n```\n{"key": "value"}\n```'
        result = extract_json_block(text)
        assert result == {"key": "value"}

    def test_bare_json_object(self):
        text = 'Here is the result: {"summary": "test", "score": 42}'
        result = extract_json_block(text)
        assert result is not None
        assert result["summary"] == "test"

    def test_no_json_returns_none(self):
        text = "This is just plain text with no JSON"
        assert extract_json_block(text) is None

    def test_empty_string_returns_none(self):
        assert extract_json_block("") is None

    def test_multiple_json_blocks_returns_first(self):
        text = '```json\n{"first": true}\n```\n```json\n{"second": true}\n```'
        result = extract_json_block(text)
        assert result == {"first": True}

    def test_malformed_json_returns_none(self):
        text = '```json\n{"key": value}\n```'
        assert extract_json_block(text) is None

    def test_json_array_ignored(self):
        """extract_json_block only returns dicts, not arrays."""
        text = '```json\n[1, 2, 3]\n```'
        assert extract_json_block(text) is None

    def test_trailing_comma_fixed(self):
        text = '```json\n{"key": "value",}\n```'
        result = extract_json_block(text)
        assert result == {"key": "value"}

    def test_single_line_comments_stripped(self):
        text = '```json\n{"key": "value" // this is a comment\n}\n```'
        result = extract_json_block(text)
        assert result == {"key": "value"}

    def test_nested_json(self):
        data = {"outer": {"inner": [1, 2, 3]}, "flag": True}
        text = f"```json\n{json.dumps(data)}\n```"
        result = extract_json_block(text)
        assert result == data

    def test_json_with_surrounding_prose(self):
        text = (
            "I've analyzed the finding. Here are the results:\n\n"
            "```json\n"
            '{"summary": "Critical RCE", "structured_output": {}}\n'
            "```\n\n"
            "Let me know if you need more details."
        )
        result = extract_json_block(text)
        assert result is not None
        assert result["summary"] == "Critical RCE"


# ---------------------------------------------------------------------------
# validate_structured_output
# ---------------------------------------------------------------------------


class TestValidateStructuredOutput:
    def test_enrichment_valid(self):
        data = {"normalized_title": "CVE-2026-1234", "cve_ids": ["CVE-2026-1234"]}
        validated, warnings = validate_structured_output(data, "finding_enricher")
        assert not warnings
        assert validated["normalized_title"] == "CVE-2026-1234"

    def test_enrichment_missing_required(self):
        data = {"cve_ids": ["CVE-2026-1234"]}  # missing normalized_title
        _, warnings = validate_structured_output(data, "finding_enricher")
        assert len(warnings) > 0
        assert any("normalized_title" in w for w in warnings)

    def test_enrichment_cvss_out_of_range(self):
        data = {"normalized_title": "Test", "cvss_score": 15.0}
        _, warnings = validate_structured_output(data, "finding_enricher")
        assert len(warnings) > 0

    def test_ownership_valid(self):
        data = {"recommended_owner": "Platform Team", "candidates": []}
        validated, warnings = validate_structured_output(data, "owner_resolver")
        assert not warnings
        assert validated["recommended_owner"] == "Platform Team"

    def test_plan_valid(self):
        data = {
            "plan_steps": ["Upgrade package", "Run tests"],
            "definition_of_done": ["Tests pass"],
        }
        validated, warnings = validate_structured_output(data, "remediation_planner")
        assert not warnings
        assert len(validated["plan_steps"]) == 2

    def test_validation_valid(self):
        data = {"verdict": "fixed", "recommendation": "close"}
        validated, warnings = validate_structured_output(data, "validation_checker")
        assert not warnings

    def test_unknown_agent_type(self):
        data = {"foo": "bar"}
        _, warnings = validate_structured_output(data, "unknown_agent")
        assert len(warnings) == 1
        assert "No schema" in warnings[0]

    def test_extra_fields_allowed(self):
        data = {
            "normalized_title": "Test",
            "cve_ids": [],
            "custom_field": "extra data",
        }
        validated, warnings = validate_structured_output(data, "finding_enricher")
        assert not warnings
        assert validated["custom_field"] == "extra data"


# ---------------------------------------------------------------------------
# parse_agent_response
# ---------------------------------------------------------------------------


class TestParseAgentResponse:
    def _make_response(self, **overrides):
        """Build a valid agent response with defaults."""
        data = {
            "summary": "Test summary",
            "result_card_markdown": "## Result\n\nDetails here",
            "structured_output": {"normalized_title": "Test", "cve_ids": []},
            "confidence": 0.85,
            "evidence_sources": ["scanner"],
            "suggested_next_action": "confirm_owner",
        }
        data.update(overrides)
        return f"Here are my findings:\n\n```json\n{json.dumps(data)}\n```"

    def test_happy_path(self):
        text = self._make_response()
        result = parse_agent_response(text, agent_type="finding_enricher")
        assert result.success is True
        assert result.summary == "Test summary"
        assert result.confidence == 0.85
        assert result.suggested_next_action == "confirm_owner"
        assert result.structured_output is not None

    def test_empty_response(self):
        result = parse_agent_response("")
        assert result.success is False
        assert "Empty" in (result.error or "")

    def test_no_json_in_response(self):
        result = parse_agent_response("Just some plain text analysis.")
        assert result.success is False
        assert "No JSON" in (result.error or "")
        assert result.raw_text == "Just some plain text analysis."
        assert result.summary  # fallback summary extracted

    def test_missing_summary_field(self):
        text = '```json\n{"not_summary": "oops"}\n```'
        result = parse_agent_response(text)
        assert result.success is False
        assert "validation failed" in (result.error or "").lower()
        # Structured output still preserved for inspection
        assert result.structured_output == {"not_summary": "oops"}

    def test_with_agent_type_validation(self):
        text = self._make_response(
            structured_output={"normalized_title": "Test", "cve_ids": ["CVE-2026-1"]}
        )
        result = parse_agent_response(text, agent_type="finding_enricher")
        assert result.success is True
        assert result.structured_output is not None
        assert result.structured_output["normalized_title"] == "Test"

    def test_validation_warnings_non_fatal(self):
        """Per-agent validation warnings don't cause failure."""
        text = self._make_response(
            structured_output={"cve_ids": []}  # missing normalized_title
        )
        result = parse_agent_response(text, agent_type="finding_enricher")
        assert result.success is True  # still succeeds
        assert len(result._validation_errors) > 0

    def test_raw_text_always_preserved(self):
        text = self._make_response()
        result = parse_agent_response(text, agent_type="finding_enricher")
        assert result.raw_text == text

    def test_confidence_range_enforced(self):
        text = self._make_response(confidence=1.5)
        result = parse_agent_response(text)
        assert result.success is False
        assert "validation failed" in (result.error or "").lower()

    def test_result_card_markdown_extracted(self):
        text = self._make_response(result_card_markdown="## CVE-2026-1234\n\nCritical")
        result = parse_agent_response(text)
        assert result.success is True
        assert result.result_card_markdown == "## CVE-2026-1234\n\nCritical"

    def test_fallback_summary_from_text(self):
        """When no JSON found, first sentence becomes summary."""
        text = "The vulnerability is critical.\nMore details follow."
        result = parse_agent_response(text)
        assert result.success is False
        assert result.summary == "The vulnerability is critical."
