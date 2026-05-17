"""Tests for the LLM-powered finding normalizer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from cliff.integrations.normalizer import MAX_BATCH_SIZE, _extract_json_array, normalize_findings

# ---------------------------------------------------------------------------
# _extract_json_array unit tests
# ---------------------------------------------------------------------------


class TestExtractJsonArray:
    def test_bare_array(self):
        text = '[{"source_type": "wiz", "source_id": "1", "title": "test"}]'
        result = _extract_json_array(text)
        assert result is not None
        assert len(result) == 1
        assert result[0]["source_id"] == "1"

    def test_fenced_json(self):
        text = '```json\n[{"source_type": "wiz", "source_id": "1", "title": "t"}]\n```'
        result = _extract_json_array(text)
        assert result is not None
        assert len(result) == 1

    def test_fenced_no_lang(self):
        text = '```\n[{"a": 1}]\n```'
        result = _extract_json_array(text)
        assert result == [{"a": 1}]

    def test_trailing_comma(self):
        text = '[{"a": 1}, {"b": 2},]'
        result = _extract_json_array(text)
        assert result is not None
        assert len(result) == 2

    def test_surrounding_text(self):
        text = 'Here are the results:\n[{"x": 1}]\nDone!'
        result = _extract_json_array(text)
        assert result == [{"x": 1}]

    def test_no_array(self):
        assert _extract_json_array("no json here") is None

    def test_empty_array(self):
        assert _extract_json_array("[]") == []

    def test_not_an_array(self):
        assert _extract_json_array('{"key": "value"}') is None

    def test_malformed_json(self):
        assert _extract_json_array("[{bad json}]") is None

    def test_nested_brackets(self):
        text = '[{"tags": ["a", "b"], "name": "test"}]'
        result = _extract_json_array(text)
        assert result is not None
        assert result[0]["tags"] == ["a", "b"]


# ---------------------------------------------------------------------------
# normalize_findings tests (mocked OpenCode client)
# ---------------------------------------------------------------------------

WIZ_LLM_RESPONSE = json.dumps([
    {
        "source_type": "wiz",
        "source_id": "wiz-123",
        "title": "S3 bucket publicly accessible",
        "description": "Public read access via bucket policy.",
        "raw_severity": "CRITICAL",
        "normalized_priority": "critical",
        "asset_id": "arn:aws:s3:::my-bucket",
        "asset_label": "my-bucket",
        "status": "new",
        "likely_owner": None,
        "why_this_matters": "Publicly accessible S3 buckets can expose sensitive data.",
    }
])

PARTIAL_LLM_RESPONSE = json.dumps([
    {
        "source_type": "snyk",
        "source_id": "SNYK-001",
        "title": "Prototype pollution in lodash",
        "status": "new",
    },
    {
        "source_type": "snyk",
        # Missing required field: source_id
        "title": "Another vuln",
    },
])


@pytest.fixture
def mock_opencode():
    """Patch the opencode_client singleton for normalizer tests.

    The normalizer uses Mode 1 (synchronous RPC) via send_and_get_response,
    so we mock that single call. It returns the LLM text or None.
    """
    with patch("cliff.integrations.normalizer.opencode_client") as mock:
        mock.create_session = AsyncMock()
        mock.create_session.return_value.id = "test-session-id"
        mock.send_and_get_response = AsyncMock(return_value=None)
        mock.get_config = AsyncMock(return_value={"model": "openai/gpt-4.1-nano"})
        mock.update_config = AsyncMock(return_value={})
        yield mock


@pytest.mark.asyncio
async def test_normalize_success(mock_opencode):
    mock_opencode.send_and_get_response.return_value = WIZ_LLM_RESPONSE

    findings, errors = await normalize_findings("wiz", [{"id": "wiz-123", "name": "test"}])

    assert len(findings) == 1
    assert findings[0].source_type == "wiz"
    assert findings[0].source_id == "wiz-123"
    assert findings[0].title == "S3 bucket publicly accessible"
    assert findings[0].normalized_priority == "critical"
    assert errors == []

    mock_opencode.create_session.assert_called_once()
    mock_opencode.send_and_get_response.assert_called_once()


@pytest.mark.asyncio
async def test_normalize_partial_failure(mock_opencode):
    """One valid finding, one missing source_id — partial result."""
    mock_opencode.send_and_get_response.return_value = PARTIAL_LLM_RESPONSE

    findings, errors = await normalize_findings("snyk", [{"a": 1}, {"b": 2}])

    assert len(findings) == 1
    assert findings[0].source_id == "SNYK-001"
    assert len(errors) == 1
    assert "Finding 2" in errors[0]


@pytest.mark.asyncio
async def test_normalize_empty_input(mock_opencode):
    findings, errors = await normalize_findings("wiz", [])
    assert findings == []
    assert errors == []
    mock_opencode.create_session.assert_not_called()


@pytest.mark.asyncio
async def test_normalize_batch_too_large(mock_opencode):
    raw = [{"id": str(i)} for i in range(MAX_BATCH_SIZE + 1)]
    findings, errors = await normalize_findings("wiz", raw)
    assert findings == []
    assert len(errors) == 1
    assert "Batch too large" in errors[0]
    mock_opencode.create_session.assert_not_called()


@pytest.mark.asyncio
async def test_normalize_llm_error(mock_opencode):
    mock_opencode.send_and_get_response.side_effect = RuntimeError("rate limit exceeded")

    findings, errors = await normalize_findings("wiz", [{"id": "1"}])
    assert findings == []
    assert len(errors) == 1
    assert "Failed to parse JSON array" in errors[0]
    # With retry, it should have been called 3 times (1 original + 2 retries)
    assert mock_opencode.create_session.call_count == 3


@pytest.mark.asyncio
async def test_normalize_empty_response(mock_opencode):
    # send_and_get_response returns None by default (fixture)
    findings, errors = await normalize_findings("wiz", [{"id": "1"}])
    assert findings == []
    assert "Failed to parse JSON array" in errors[0]
    # Retried 3 times
    assert mock_opencode.create_session.call_count == 3


@pytest.mark.asyncio
async def test_normalize_malformed_response(mock_opencode):
    mock_opencode.send_and_get_response.return_value = "Sorry, I can't do that."

    findings, errors = await normalize_findings("wiz", [{"id": "1"}])
    assert findings == []
    assert "Failed to parse" in errors[0]
    # Retried 3 times
    assert mock_opencode.create_session.call_count == 3


@pytest.mark.asyncio
async def test_normalize_fenced_response(mock_opencode):
    """LLM wraps JSON in markdown fences — should still parse."""
    fenced = f"```json\n{WIZ_LLM_RESPONSE}\n```"
    mock_opencode.send_and_get_response.return_value = fenced

    findings, errors = await normalize_findings("wiz", [{"id": "wiz-123"}])
    assert len(findings) == 1
    assert errors == []


@pytest.mark.asyncio
async def test_normalize_injects_source_type(mock_opencode):
    """If LLM omits source_type, it's injected from the request."""
    response = json.dumps([
        {"source_id": "x-1", "title": "Test vuln", "status": "new"},
    ])
    mock_opencode.send_and_get_response.return_value = response

    findings, errors = await normalize_findings("trivy", [{"id": "x-1"}])
    assert len(findings) == 1
    assert findings[0].source_type == "trivy"
    assert errors == []
