"""Unit tests for the Pydantic AI finding normalizer (IMPL-0022 PR #3b).

These drive ``normalize_findings`` with a ``FunctionModel`` (no live LLM):
``build_model`` is patched to return the fake model, so each test controls
the structured output the agent "returns" and asserts the downstream
``FindingCreate`` validation + partial-success ``(valid, errors)`` contract.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from cliff.integrations.normalizer import MAX_BATCH_SIZE, normalize_findings

_ENV = {"OPENAI_API_KEY": "test-key"}
_MODEL = "openai/gpt-4o-mini"


def _model_returning(items: list[dict]) -> FunctionModel:
    """A FunctionModel that emits *items* as the agent's structured output.

    PA wraps a ``list[...]`` output in a synthetic ``final_result`` tool whose
    single argument is ``response`` — see the agent's output schema.
    """

    def _fn(messages, info: AgentInfo) -> ModelResponse:
        tool_name = info.output_tools[0].name
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool_name, args={"response": items})]
        )

    return FunctionModel(_fn)


def _erroring_model() -> FunctionModel:
    def _fn(messages, info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(status_code=429, model_name="x", body="rate limited")

    return FunctionModel(_fn)


def _patch_model(model: FunctionModel):
    return patch("cliff.integrations.normalizer.build_model", return_value=model)


_WIZ_ITEM = {
    "source_type": "wiz",
    "source_id": "wiz-123",
    "title": "S3 bucket publicly accessible",
    "description": "Public read access via bucket policy.",
    "raw_severity": "CRITICAL",
    "normalized_priority": "critical",
    "asset_id": "arn:aws:s3:::my-bucket",
    "asset_label": "my-bucket",
    "status": "new",
    "why_this_matters": "Publicly accessible S3 buckets can expose data.",
}


@pytest.mark.asyncio
async def test_normalize_success():
    with _patch_model(_model_returning([_WIZ_ITEM])):
        findings, errors = await normalize_findings(
            "wiz", [{"id": "wiz-123", "name": "test"}], env=_ENV, model=_MODEL
        )

    assert len(findings) == 1
    assert findings[0].source_type == "wiz"
    assert findings[0].source_id == "wiz-123"
    assert findings[0].title == "S3 bucket publicly accessible"
    assert findings[0].normalized_priority == "critical"
    assert errors == []


@pytest.mark.asyncio
async def test_normalize_partial_failure():
    """One valid finding, one missing source_id — partial result preserved."""
    items = [
        {
            "source_type": "snyk",
            "source_id": "SNYK-001",
            "title": "Prototype pollution in lodash",
            "status": "new",
        },
        {"source_type": "snyk", "title": "Another vuln"},  # missing source_id
    ]
    with _patch_model(_model_returning(items)):
        findings, errors = await normalize_findings(
            "snyk", [{"a": 1}, {"b": 2}], env=_ENV, model=_MODEL
        )

    assert len(findings) == 1
    assert findings[0].source_id == "SNYK-001"
    assert len(errors) == 1
    assert "Finding 2" in errors[0]


@pytest.mark.asyncio
async def test_normalize_injects_source_type():
    """If the model omits source_type, it's filled from the request source."""
    items = [{"source_id": "x-1", "title": "Test vuln", "status": "new"}]
    with _patch_model(_model_returning(items)):
        findings, errors = await normalize_findings(
            "trivy", [{"id": "x-1"}], env=_ENV, model=_MODEL
        )

    assert len(findings) == 1
    assert findings[0].source_type == "trivy"
    assert errors == []


@pytest.mark.asyncio
async def test_normalize_fills_status_when_null():
    """A null status from the model defaults to 'new' (not a validation error)."""
    items = [{"source_type": "wiz", "source_id": "w-9", "title": "T", "status": None}]
    with _patch_model(_model_returning(items)):
        findings, errors = await normalize_findings(
            "wiz", [{"id": "w-9"}], env=_ENV, model=_MODEL
        )

    assert errors == []
    assert findings[0].status == "new"


@pytest.mark.asyncio
async def test_normalize_forces_status_new_over_stray_value():
    """A stray status string (e.g. 'open') must not drop an otherwise-valid
    finding — the normalizer always emits brand-new findings."""
    items = [
        {"source_type": "wiz", "source_id": "w-1", "title": "T", "status": "open"}
    ]
    with _patch_model(_model_returning(items)):
        findings, errors = await normalize_findings(
            "wiz", [{"id": "w-1"}], env=_ENV, model=_MODEL
        )

    assert errors == []
    assert findings[0].status == "new"


@pytest.mark.asyncio
async def test_normalize_coerces_listwrapped_raw_payload():
    """The model sometimes wraps raw_payload in a single-element list."""
    payload = {"id": "w-1", "extra": True}
    items = [
        {
            "source_type": "wiz",
            "source_id": "w-1",
            "title": "T",
            "status": "new",
            "raw_payload": [payload],
        }
    ]
    with _patch_model(_model_returning(items)):
        findings, _ = await normalize_findings(
            "wiz", [{"id": "w-1"}], env=_ENV, model=_MODEL
        )

    assert findings[0].raw_payload == payload


@pytest.mark.asyncio
async def test_normalize_empty_input():
    # No model call at all for empty input.
    with patch("cliff.integrations.normalizer.build_model") as build:
        findings, errors = await normalize_findings("wiz", [], env=_ENV, model=_MODEL)
    assert findings == []
    assert errors == []
    build.assert_not_called()


@pytest.mark.asyncio
async def test_normalize_batch_too_large():
    raw = [{"id": str(i)} for i in range(MAX_BATCH_SIZE + 1)]
    with patch("cliff.integrations.normalizer.build_model") as build:
        findings, errors = await normalize_findings(
            "wiz", raw, env=_ENV, model=_MODEL
        )
    assert findings == []
    assert len(errors) == 1
    assert "Batch too large" in errors[0]
    build.assert_not_called()


@pytest.mark.asyncio
async def test_normalize_llm_error_returns_error_not_raises():
    """An LLM transport error is captured as an error string, not raised."""
    with _patch_model(_erroring_model()):
        findings, errors = await normalize_findings(
            "wiz", [{"id": "1"}], env=_ENV, model=_MODEL
        )
    assert findings == []
    assert len(errors) == 1
    assert "Normalizer LLM call failed" in errors[0]


@pytest.mark.asyncio
async def test_normalize_model_not_configured():
    """A missing/blank model surfaces as a friendly error, not a crash."""
    findings, errors = await normalize_findings(
        "wiz", [{"id": "1"}], env={}, model=None
    )
    assert findings == []
    assert len(errors) == 1
    assert "Normalizer model not configured" in errors[0]
