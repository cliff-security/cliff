"""LLM-powered finding normalizer using the singleton OpenCode process.

Accepts raw scanner data from any vendor and normalizes it into FindingCreate
records via a dedicated extraction prompt. See ADR-0022 for design rationale.

Token-cost note (IMPL-0002 C1, 2026-04-16): the prompt grew by roughly
~625 input tokens when ``plain_description`` rules + examples were added.
The growth is a fixed per-request cost, so ``MAX_BATCH_SIZE`` is unchanged.
Small batches (1-3 findings) see ~30% input-token inflation per call —
worth tracking in the cost report if ingest volume trends low.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from cliff.engine.client import opencode_client
from cliff.models import FindingCreate

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 50
_MAX_RETRIES = 2  # Total attempts: 1 original + 2 retries = 3

_RE_FENCED = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
_RE_TRAILING_COMMA = re.compile(r",\s*([}\]])")

# ---------------------------------------------------------------------------
# Normalizer prompt — tight extraction, few-shot, no chain-of-thought
# ---------------------------------------------------------------------------

NORMALIZER_PROMPT = """\
You are a security finding normalizer. Your job is to extract structured fields \
from raw vulnerability scanner data into a standard JSON format.

## Output schema

Each finding must match this JSON schema exactly:

```json
{
  "source_type": "string (scanner name, e.g. 'wiz', 'snyk', 'trivy')",
  "source_id": "string (unique ID from the source system)",
  "title": "string (concise finding title)",
  "description": "string or null (longer description if available)",
  "raw_severity": "string or null (original severity from the scanner, e.g. 'CRITICAL', 'High')",
  "normalized_priority": "string or null (one of: 'critical', 'high', 'medium', 'low', 'info')",
  "asset_id": "string or null (affected resource identifier)",
  "asset_label": "string or null (human-readable resource name)",
  "status": "new",
  "likely_owner": "string or null (team or person if identifiable)",
  "why_this_matters": "string or null (one sentence on business impact)",
  "plain_description": "string or null (2-4 sentences, plain language, ends with a fix hint)",
  "raw_payload": "object or null (the original raw finding object, preserved as-is)"
}
```

## Rules

- Output ONLY a JSON array of objects. No explanation, no markdown fences, no text before or after.
- Every object must have `source_type`, `source_id`, and `title` — these are required.
- Set `status` to `"new"` for all findings.
- Map the scanner's severity to `normalized_priority` using: critical, high, medium, low, info.
- If a field is not present in the raw data, set it to null.
- Preserve the original `source_id` from the scanner (e.g. Wiz issue ID, Snyk issue ID).
- Include the entire original raw finding object in `raw_payload` for reference.

## `plain_description` rules

Write this field as if for a developer who has never seen this class of
vulnerability before. It is the text the dashboard shows in the finding row —
the user decides whether to care based on this sentence alone.

- **Length: 2 to 4 sentences.** Never 1. Never 5+.
- **No jargon, no acronyms, no identifier strings.** Do NOT include:
  `CWE-...`, `CVSS:...`, bare acronyms like `RCE`, `DoS`, `ReDoS`, `JNDI`,
  `SOCKS5`, `XSS` without an explanation in the same sentence.
- **No raw CVE IDs inside prose.** `CVE-YYYY-NNNN` belongs in structured
  fields, not the human sentence.
- **Name the affected thing in plain terms** — the package, the bucket, the
  user, the file. Quote the version if you have it.
- **The last sentence MUST be a fix hint** — an imperative phrase that starts
  with a verb like "Upgrade", "Update", "Bump", "Remove", "Restrict",
  "Disable", "Replace". Include the fix version or the action if the raw
  data provides it.
- If the raw data is too sparse to write four useful sentences, write two
  honest ones. Do not pad.
- If no meaningful fix is possible from the raw data, set the field to null.
  Do not fabricate a fix.

## Examples

### Example 1: Wiz-style input

Source: wiz
Raw data:
```json
[{
  "id": "wiz-123",
  "name": "S3 bucket publicly accessible",
  "severity": "CRITICAL",
  "resource": {"id": "arn:aws:s3:::my-bucket", "name": "my-bucket"},
  "description": "The S3 bucket allows public read access."
}]
```

Output:
[{
  "source_type": "wiz",
  "source_id": "wiz-123",
  "title": "S3 bucket publicly accessible",
  "description": "The S3 bucket allows public read access.",
  "raw_severity": "CRITICAL",
  "normalized_priority": "critical",
  "asset_id": "arn:aws:s3:::my-bucket",
  "asset_label": "my-bucket",
  "status": "new",
  "likely_owner": null,
  "why_this_matters": "Public S3 buckets can expose sensitive data.",
  "plain_description": "The S3 bucket named my-bucket is readable by anyone on the internet. Anyone who learns the name can list and download every object inside. Remove public read on the bucket and block public access at the account level.",
  "raw_payload": {
    "id": "wiz-123",
    "name": "S3 bucket publicly accessible",
    "severity": "CRITICAL",
    "resource": {"id": "arn:aws:s3:::my-bucket", "name": "my-bucket"},
    "description": "The S3 bucket allows public read access."
  }
}]

### Example 2: Snyk-style input

Source: snyk
Raw data:
```json
[{
  "id": "SNYK-JS-LODASH-590103",
  "title": "Prototype Pollution in lodash",
  "severity": "high",
  "packageName": "lodash",
  "version": "4.17.15",
  "from": ["myapp@1.0.0", "lodash@4.17.15"]
}]
```

Output:
[{
  "source_type": "snyk",
  "source_id": "SNYK-JS-LODASH-590103",
  "title": "Prototype Pollution in lodash",
  "description": null,
  "raw_severity": "high",
  "normalized_priority": "high",
  "asset_id": "lodash@4.17.15",
  "asset_label": "lodash",
  "status": "new",
  "likely_owner": null,
  "why_this_matters": "Prototype pollution can cause DoS or RCE.",
  "plain_description": "Your app depends on lodash 4.17.15, a popular JavaScript utility library. This version lets an attacker inject properties into shared objects, which can change how unrelated code behaves. Upgrade lodash to a version Snyk lists as fixed.",
  "raw_payload": {
    "id": "SNYK-JS-LODASH-590103",
    "title": "Prototype Pollution in lodash",
    "severity": "high",
    "packageName": "lodash",
    "version": "4.17.15",
    "from": ["myapp@1.0.0", "lodash@4.17.15"]
  }
}]

### Example 3: Snyk-style input with CVE details

Source: snyk
Raw data:
```json
[{
  "id": "SNYK-JS-LODASH-1018905",
  "title": "Prototype Pollution in lodash",
  "severity": "CRITICAL",
  "packageName": "lodash",
  "version": "4.17.20",
  "fixedIn": ["4.17.21"],
  "CVSSv3": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
  "cvssScore": 9.8,
  "exploitMaturity": "Proof of Concept",
  "description": "The lodash package is vulnerable to Prototype Pollution via the set function.",
  "identifiers": {"CVE": ["CVE-2021-23337"], "CWE": ["CWE-1321"]},
  "from": ["myapp@1.0.0", "lodash@4.17.20"],
  "upgradePath": ["lodash@4.17.21"]
}]
```

Output:
[{
  "source_type": "snyk",
  "source_id": "SNYK-JS-LODASH-1018905",
  "title": "Prototype Pollution in lodash",
  "description": "The lodash package is vulnerable to Prototype Pollution via the set function.",
  "raw_severity": "CRITICAL",
  "normalized_priority": "critical",
  "asset_id": "lodash@4.17.20",
  "asset_label": "lodash",
  "status": "new",
  "likely_owner": null,
  "why_this_matters": "Prototype pollution with a known CVE and public exploit can lead to RCE.",
  "plain_description": "Your app uses lodash 4.17.20, a JavaScript helper library. Attackers can abuse the set function to inject values into internal objects and trick your code into running logic it shouldn't. A fix exists and public exploit proofs are available. Upgrade lodash to 4.17.21.",
  "raw_payload": {
    "id": "SNYK-JS-LODASH-1018905",
    "title": "Prototype Pollution in lodash",
    "severity": "CRITICAL",
    "packageName": "lodash",
    "version": "4.17.20",
    "fixedIn": ["4.17.21"],
    "cvssScore": 9.8,
    "exploitMaturity": "Proof of Concept",
    "identifiers": {"CVE": ["CVE-2021-23337"], "CWE": ["CWE-1321"]}
  }
}]

---

Now normalize the following findings.

IMPORTANT: Respond with ONLY the JSON array. No other text.
"""


def _build_prompt(source: str, raw_json: str) -> str:
    return (
        f"{NORMALIZER_PROMPT}\n"
        f"Source: {source}\n"
        f"Raw data:\n```json\n{raw_json}\n```\n\n"
        "JSON array output:"
    )


# ---------------------------------------------------------------------------
# JSON array extractor — handles fenced blocks and bare arrays
# ---------------------------------------------------------------------------


def _extract_json_array(text: str) -> list[dict[str, Any]] | None:
    """Extract a JSON array from LLM response text.

    Handles: bare JSON arrays, ```json fenced blocks, trailing commas.
    Returns None if no valid array is found.
    """
    fenced = _RE_FENCED.search(text)
    candidate = fenced.group(1).strip() if fenced else text.strip()

    start = candidate.find("[")
    if start == -1:
        return None

    # Fix trailing commas before attempting parse (common LLM quirk)
    cleaned = _RE_TRAILING_COMMA.sub(r"\1", candidate[start:])

    # Use raw_decode to correctly handle brackets inside JSON strings
    try:
        parsed, _ = json.JSONDecoder().raw_decode(cleaned)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list):
        return None
    return parsed


# ---------------------------------------------------------------------------
# Main normalize function
# ---------------------------------------------------------------------------


async def normalize_findings(
    source: str, raw_data: list[dict[str, Any]], *, model: str | None = None
) -> tuple[list[FindingCreate], list[str]]:
    """Normalize raw scanner findings via LLM extraction.

    Returns (valid_findings, errors) where errors contains human-readable
    strings for items that failed validation.

    Args:
        source: Scanner name (e.g. 'snyk', 'wiz').
        raw_data: List of raw finding dicts from the scanner.
        model: Optional model override (e.g. 'openai/gpt-4.1-mini').
               If provided, temporarily sets the OpenCode model config.
    """
    if not raw_data:
        return [], []

    if len(raw_data) > MAX_BATCH_SIZE:
        return [], [
            f"Batch too large: {len(raw_data)} items (max {MAX_BATCH_SIZE}). "
            "Use the async ingest endpoint for larger batches."
        ]

    # Build prompt — compact JSON to minimize token cost
    raw_json = json.dumps(raw_data, separators=(",", ":"))
    prompt = _build_prompt(source, raw_json)

    # Temporarily override model if requested
    original_model: str | None = None
    if model:
        try:
            config = await opencode_client.get_config()
            original_model = config.get("model", None)
            await opencode_client.update_config({"model": model})
            logger.info("Normalizer using model override: %s", model)
        except Exception as exc:
            logger.warning("Failed to set model override %s: %s", model, exc)

    try:
        items = await _call_llm_with_retry(prompt)
    finally:
        # Restore original model if we changed it
        if original_model is not None:
            try:
                await opencode_client.update_config({"model": original_model})
            except Exception:
                logger.warning("Failed to restore original model %s", original_model)

    if items is None:
        return [], ["Failed to parse JSON array from LLM response after 3 attempts"]

    # Validate each item against FindingCreate schema
    findings: list[FindingCreate] = []
    errors: list[str] = []

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"Finding {i + 1}: expected object, got {type(item).__name__}")
            continue
        if "source_type" not in item:
            item["source_type"] = source
        # Coerce raw_payload: LLM sometimes wraps the original object in a list
        rp = item.get("raw_payload")
        if isinstance(rp, list):
            item["raw_payload"] = rp[0] if len(rp) == 1 and isinstance(rp[0], dict) else None
        try:
            findings.append(FindingCreate.model_validate(item))
        except ValidationError as exc:
            errors.append(f"Finding {i + 1}: {exc}")

    return findings, errors


async def _call_llm_with_retry(prompt: str) -> list[dict[str, Any]] | None:
    """Send prompt to LLM and extract JSON array, with up to 3 attempts.

    Creates a fresh session for each retry to avoid stuck generation patterns.
    Returns the parsed JSON array or None if all attempts fail.
    """
    last_response: str | None = None

    for attempt in range(_MAX_RETRIES + 1):
        session = await opencode_client.create_session()
        try:
            full_text = await opencode_client.send_and_get_response(
                session.id, prompt
            )
        except Exception as exc:
            logger.warning(
                "Normalizer attempt %d/%d: LLM error: %s",
                attempt + 1, _MAX_RETRIES + 1, exc,
            )
            last_response = f"[exception] {exc}"
            continue

        if not full_text:
            logger.warning(
                "Normalizer attempt %d/%d: LLM returned empty response",
                attempt + 1, _MAX_RETRIES + 1,
            )
            last_response = "[empty response]"
            continue

        last_response = full_text
        items = _extract_json_array(full_text)
        if items is not None:
            if attempt > 0:
                logger.info("Normalizer succeeded on attempt %d", attempt + 1)
            return items

        # Log what the LLM actually said for debugging
        snippet = full_text[:500].replace("\n", "\\n")
        logger.warning(
            "Normalizer attempt %d/%d: Failed to parse JSON from response: %s",
            attempt + 1, _MAX_RETRIES + 1, snippet,
        )

    # All attempts failed — include a snippet in the error for the user
    if last_response and not last_response.startswith("["):
        snippet = last_response[:200].replace("\n", " ").strip()
        logger.error(
            "Normalizer gave up after %d attempts. Last response: %s",
            _MAX_RETRIES + 1, snippet,
        )

    return None
