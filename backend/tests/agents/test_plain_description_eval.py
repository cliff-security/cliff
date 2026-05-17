"""Evaluation harness for the plain_description field (IMPL-0002 C1).

Runs a set of known CVE / misconfiguration fixtures through the real LLM
normalizer and asserts shape-level properties on the resulting
``plain_description`` (2-4 sentences, no jargon, ends with a fix hint).

Each fixture record declares:
  - ``source``: scanner source to feed ``normalize_findings``
  - ``raw_finding``: the raw scanner dict
  - ``must_contain_any``: at least one of these substrings must appear
  - ``must_not_contain_regex``: none of these regexes may match (jargon)
  - ``fix_hint_keywords``: at least one must appear (the fix hint)
  - ``sentence_count_range``: [min, max] sentences allowed

Budget: ~10 LLM calls, roughly $0.02. Skipped automatically when no API
key or OpenCode binary is present (see ``conftest.py``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cliff.integrations.normalizer import normalize_findings

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "plain_description_evals.json"


def _load_fixtures() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())


def _count_sentences(text: str) -> int:
    """Rough sentence count — splits on ``. ! ?`` boundaries.

    Strips trailing whitespace/punctuation and ignores empty segments.
    """
    # Replace sentence terminators with a single delimiter, then split.
    segments = re.split(r"(?<=[.!?])\s+", text.strip())
    return len([s for s in segments if s.strip()])


@pytest.mark.asyncio
@pytest.mark.parametrize("record", _load_fixtures(), ids=lambda r: r["id"])
async def test_plain_description_shape(record: dict) -> None:
    """Each fixture produces a plain_description that passes shape checks."""
    findings, errors = await normalize_findings(
        record["source"], [record["raw_finding"]]
    )
    assert not errors, f"Normalizer errors for {record['id']}: {errors}"
    assert len(findings) == 1, f"Expected 1 finding, got {len(findings)}"

    finding = findings[0]
    pd = finding.plain_description
    assert pd, f"plain_description missing or empty for {record['id']}"
    assert isinstance(pd, str)

    # Sentence count range.
    lo, hi = record["sentence_count_range"]
    count = _count_sentences(pd)
    assert lo <= count <= hi, (
        f"{record['id']}: expected {lo}-{hi} sentences, got {count}. "
        f"plain_description={pd!r}"
    )

    # At least one of the must_contain_any strings.
    must_any = record["must_contain_any"]
    pd_lower = pd.lower()
    assert any(s.lower() in pd_lower for s in must_any), (
        f"{record['id']}: plain_description missing all of {must_any}. "
        f"Got: {pd!r}"
    )

    # None of the must_not_contain_regex patterns.
    for pattern in record["must_not_contain_regex"]:
        assert not re.search(pattern, pd), (
            f"{record['id']}: plain_description contains jargon matching "
            f"/{pattern}/. Got: {pd!r}"
        )

    # At least one fix hint keyword.
    fix_hints = record["fix_hint_keywords"]
    assert any(k.lower() in pd_lower for k in fix_hints), (
        f"{record['id']}: plain_description missing a fix hint. "
        f"Expected any of {fix_hints}. Got: {pd!r}"
    )
