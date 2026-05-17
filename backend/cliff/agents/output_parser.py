"""Agent output parser — extracts structured JSON from LLM response text.

LLMs wrap JSON in markdown code fences, add preamble text, and sometimes
produce malformed JSON. This module handles all of that reliably.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from cliff.agents.schemas import AGENT_OUTPUT_SCHEMAS, AgentOutput

logger = logging.getLogger(__name__)

# Patterns for extracting JSON from LLM output, tried in order:
# 1. ```json ... ``` — explicitly tagged (most reliable)
# 2. ``` {...} ``` — untagged code fence containing a JSON object
# 3. Bare {...} — outermost brace pair (lenient fallback)
_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)
_ANY_FENCE_RE = re.compile(r"```\s*\n(\{.*?\})\n\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{[\s\S]*\}")

# Lenient fixup patterns (compiled once).
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_LINE_COMMENT_RE = re.compile(r"//.*$", re.MULTILINE)


@dataclass
class ParseResult:
    """Result of parsing an agent's LLM response."""

    success: bool
    structured_output: dict[str, Any] | None = None
    raw_text: str = ""
    summary: str = ""
    result_card_markdown: str | None = None
    confidence: float | None = None
    suggested_next_action: str | None = None
    error: str | None = None
    _validation_errors: list[str] = field(default_factory=list)


def extract_json_block(text: str) -> dict[str, Any] | None:
    """Extract the first valid JSON object from LLM response text.

    Tries strategies in order:
    1. ```json ... ``` fenced block
    2. ``` { ... } ``` any fenced block containing JSON object
    3. Outermost { ... } in the text
    """
    # Strategy 1: ```json ... ```
    for match in _JSON_FENCE_RE.finditer(text):
        result = _try_parse_json(match.group(1))
        if result is not None:
            return result

    # Strategy 2: ``` { ... } ```
    for match in _ANY_FENCE_RE.finditer(text):
        result = _try_parse_json(match.group(1))
        if result is not None:
            return result

    # Strategy 3: outermost { ... }
    match = _BARE_JSON_RE.search(text)
    if match:
        result = _try_parse_json(match.group(0))
        if result is not None:
            return result

    return None


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Try to parse JSON, applying lenient fixups if strict parse fails."""
    # Strict parse first
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Lenient: strip trailing commas before } or ]
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", text)
    # Strip single-line // comments
    cleaned = _LINE_COMMENT_RE.sub("", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    return None


def validate_agent_output(data: dict[str, Any]) -> AgentOutput:
    """Validate extracted JSON against the common AgentOutput schema.

    Raises:
        ValidationError: If required fields are missing or invalid.
    """
    return AgentOutput.model_validate(data)


def validate_structured_output(
    data: dict[str, Any], agent_type: str
) -> tuple[dict[str, Any], list[str]]:
    """Validate the structured_output dict against the per-agent schema.

    Returns (validated_data, validation_warnings). Warnings are non-fatal —
    the data is still usable but some fields may be missing or wrong.
    """
    schema_cls = AGENT_OUTPUT_SCHEMAS.get(agent_type)
    if schema_cls is None:
        return data, [f"No schema defined for agent_type={agent_type!r}"]

    warnings: list[str] = []
    try:
        validated = schema_cls.model_validate(data)
        return validated.model_dump(), warnings
    except ValidationError as exc:
        # Collect warnings but return original data — partial output is still useful
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            warnings.append(f"{loc}: {err['msg']}")
        return data, warnings


def parse_agent_response(
    text: str, *, agent_type: str | None = None
) -> ParseResult:
    """Parse a full LLM response into a structured ParseResult.

    This is the main entry point. It:
    1. Extracts JSON from the response text
    2. Validates against the common AgentOutput schema
    3. Optionally validates structured_output against the per-agent schema
    4. Returns a ParseResult with all extracted data

    Never throws — always returns a ParseResult (success may be False).
    """
    if not text or not text.strip():
        return ParseResult(
            success=False,
            raw_text=text or "",
            error="Empty response from agent",
        )

    # Extract JSON
    json_data = extract_json_block(text)
    if json_data is None:
        return ParseResult(
            success=False,
            raw_text=text,
            summary=_extract_first_sentence(text),
            error="No JSON block found in agent response",
        )

    # Validate common output contract
    try:
        agent_output = validate_agent_output(json_data)
    except ValidationError as exc:
        return ParseResult(
            success=False,
            raw_text=text,
            structured_output=json_data,
            summary=json_data.get("summary", _extract_first_sentence(text)),
            error=f"Output validation failed: {exc.error_count()} error(s)",
        )

    # Validate per-agent structured_output (non-fatal)
    validation_warnings: list[str] = []
    structured = agent_output.structured_output
    if agent_type and structured:
        structured, validation_warnings = validate_structured_output(
            structured, agent_type
        )

    return ParseResult(
        success=True,
        structured_output=structured,
        raw_text=text,
        summary=agent_output.summary,
        result_card_markdown=agent_output.result_card_markdown or None,
        confidence=agent_output.confidence,
        suggested_next_action=agent_output.suggested_next_action,
        _validation_errors=validation_warnings,
    )


def _extract_first_sentence(text: str) -> str:
    """Extract the first non-empty sentence from text as a fallback summary."""
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("```", "#", "---", "{")):
            # Truncate to ~200 chars
            return stripped[:200]
    return text[:200].strip()
