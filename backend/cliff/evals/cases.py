"""Eval dataset cases (ADR-0050 §2).

One typed schema for every agent's cases, stored as JSONL at
``backend/tests/agents/eval/<agent>.jsonl`` — one case per line, append a
line to add a case. ``load_cases`` enumerates them in file order.

(The dataset lives under ``tests/`` and is only read by the eval tests; the
loader resolving a ``tests/`` path from a ``cliff.*`` module is the
test/prod-line blur tracked as ADR-0050 Open question #7.)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# Public synthetic sample lives in-repo; backend/ root is parents[2].
_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "tests" / "agents" / "eval"


def dataset_dir() -> Path:
    """Where datasets are read from (ADR-0050 hybrid: harness public, data
    private). Defaults to the public synthetic sample; the private eval project
    (``cliff-os/eval``) overrides it via ``CLIFF_EVAL_DATASET_DIR`` to point at
    the real/confidential golden sets — which never enter this public repo."""
    override = os.environ.get("CLIFF_EVAL_DATASET_DIR")
    return Path(override) if override else _SAMPLE_DIR


class EvalCase(BaseModel):
    """One eval case. ``finding`` is the raw input; ``expected`` holds the
    golden labels the deterministic evaluators check; ``abstain`` marks a
    case where the agent MUST decline (no CVE / post-cutoff)."""

    id: str
    tier: Literal["ci", "live"] = "live"
    edge_case: str | None = None
    abstain: bool = False
    finding: dict[str, Any]
    expected: dict[str, Any] = Field(default_factory=dict)


def load_cases(agent: str, *, tier: str | None = None) -> list[EvalCase]:
    """Load ``<agent>.jsonl`` from the active dataset dir into typed cases."""
    path = dataset_dir() / f"{agent}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"No eval dataset for {agent!r} at {path}")
    cases: list[EvalCase] = []
    for line_no, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            cases.append(EvalCase.model_validate_json(line))
        except ValueError as exc:  # malformed line — surface which one
            raise ValueError(f"{path.name}:{line_no}: invalid case — {exc}") from exc
    if tier is not None:
        cases = [c for c in cases if c.tier == tier]
    return cases


__all__ = ["EvalCase", "load_cases"]
