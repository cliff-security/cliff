"""LLM-powered finding normalizer (Pydantic AI, app-level).

Accepts raw scanner data from any vendor and normalizes it into FindingCreate
records via a dedicated extraction prompt. See ADR-0022 for design rationale
and ADR-0047 / IMPL-0022 PR #3b for the OpenCode → Pydantic AI migration.

This is an *app-level* agent (no workspace), so its provider key + model are
passed in by the caller (``env`` + ``model``) rather than resolved from a
workspace. Pydantic AI's structured ``output_type`` + internal retry loop
replace the hand-rolled JSON extraction and retry machinery the OpenCode-era
normalizer carried; the per-item ``FindingCreate`` validation below is
unchanged and still drives the partial-success ``(valid, errors)`` contract.

Token-cost note (IMPL-0002 C1, 2026-04-16): the prompt grew by roughly
~625 input tokens when ``plain_description`` rules + examples were added.
The growth is a fixed per-request cost, so ``MAX_BATCH_SIZE`` is unchanged.
Small batches (1-3 findings) see ~30% input-token inflation per call —
worth tracking in the cost report if ingest volume trends low.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from pydantic_ai.exceptions import (
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UserError,
)

from cliff.agents.runtime.normalizer_agent import build_normalizer_agent
from cliff.agents.runtime.provider import ProviderConfigurationError, build_model
from cliff.models import FindingCreate

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 50

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


def _build_user_message(source: str, raw_json: str) -> str:
    """The per-call user message — just the scanner source + raw data.

    The schema, rules, and few-shot examples live in ``NORMALIZER_PROMPT``,
    which is the agent's *system* prompt; this is only the variable payload.
    """
    return (
        f"Source: {source}\n"
        f"Raw data:\n```json\n{raw_json}\n```\n\n"
        "Normalize these findings."
    )


# ---------------------------------------------------------------------------
# Main normalize function
# ---------------------------------------------------------------------------


async def normalize_findings(
    source: str,
    raw_data: list[dict[str, Any]],
    *,
    env: dict[str, str],
    model: str | None = None,
) -> tuple[list[FindingCreate], list[str]]:
    """Normalize raw scanner findings via a Pydantic AI extraction call.

    Returns (valid_findings, errors) where errors holds human-readable
    strings for items that failed validation. Partial success is normal —
    one malformed item lands in ``errors`` while the rest succeed.

    Args:
        source: Scanner name (e.g. 'snyk', 'wiz').
        raw_data: List of raw finding dicts from the scanner.
        env: Provider credentials (e.g. ``{"OPENAI_API_KEY": ...}``) used to
            build the model — the app-level analogue of the per-workspace
            env the pipeline agents receive.
        model: Full model id (``'<provider>/<model>'``) to run with. Required
            in practice; ``build_model`` rejects a missing/blank value.
    """
    if not raw_data:
        return [], []

    if len(raw_data) > MAX_BATCH_SIZE:
        return [], [
            f"Batch too large: {len(raw_data)} items (max {MAX_BATCH_SIZE}). "
            "Use the async ingest endpoint for larger batches."
        ]

    try:
        pa_model = build_model(env, model)
    except ProviderConfigurationError as exc:
        return [], [f"Normalizer model not configured: {exc}"]

    agent = build_normalizer_agent(pa_model, system_prompt=NORMALIZER_PROMPT)
    raw_json = json.dumps(raw_data, separators=(",", ":"))

    try:
        result = await agent.run(_build_user_message(source, raw_json))
    except (
        ModelHTTPError,
        UnexpectedModelBehavior,
        UsageLimitExceeded,
        UserError,
    ) as exc:
        logger.warning("Normalizer LLM call failed: %s", exc)
        return [], [f"Normalizer LLM call failed: {type(exc).__name__}: {exc}"]

    # Pydantic AI handed back validated (lenient) NormalizedFinding objects;
    # the strict FindingCreate contract — and the per-item partial-success
    # accounting — is enforced here, exactly as on the OpenCode-era path.
    findings: list[FindingCreate] = []
    errors: list[str] = []

    for i, nf in enumerate(result.output):
        item = nf.model_dump()
        # The model_dump always carries every key; fill the load-bearing
        # defaults the LLM may have left null.
        if item.get("source_type") is None:
            item["source_type"] = source
        # Normalized findings are always brand-new — force the status rather
        # than trusting the model's value, so a stray string (e.g. "open")
        # doesn't drop an otherwise-valid finding into ``errors``.
        item["status"] = "new"
        # Coerce raw_payload: the model sometimes wraps the original object
        # in a single-element list.
        rp = item.get("raw_payload")
        if isinstance(rp, list):
            item["raw_payload"] = (
                rp[0] if len(rp) == 1 and isinstance(rp[0], dict) else None
            )
        try:
            findings.append(FindingCreate.model_validate(item))
        except ValidationError as exc:
            errors.append(f"Finding {i + 1}: {exc}")

    return findings, errors
