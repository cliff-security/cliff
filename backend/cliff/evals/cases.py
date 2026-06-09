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

Tier = Literal["ci", "live"]

# Public synthetic sample lives in-repo; backend/ root is parents[2].
_SAMPLE_DIR = Path(__file__).resolve().parents[2] / "tests" / "agents" / "eval"


def dataset_dir() -> Path:
    """Where datasets are read from (ADR-0050 hybrid: harness public, data
    private). Defaults to the public synthetic sample; the private eval project
    (``cliff-os/eval``) overrides it via ``CLIFF_EVAL_DATASET_DIR`` to point at
    the real/confidential golden sets — which never enter this public repo.

    A relative override is anchored to an absolute path (``.resolve()``) so the
    same value resolves identically regardless of the process cwd."""
    override = os.environ.get("CLIFF_EVAL_DATASET_DIR")
    return Path(override).expanduser().resolve() if override else _SAMPLE_DIR


class Expected(BaseModel):
    """Golden labels for a case. A typed contract (not a free-form dict) so a
    malformed JSONL row fails in ``load_cases`` instead of silently slipping a
    bad shape past ``check_cve_ids`` / ``check_cvss_within``. Only declared
    keys are graded — an omitted field means "no expectation"."""

    model_config = {"extra": "forbid"}

    cve_ids: list[str] | None = None
    cvss_score: float | None = None
    cvss_min: float | None = None
    cvss_max: float | None = None
    # ADR-0051 — triage golden verdict (triage_synthesizer / report_triager).
    verdict: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """The declared-only mapping the deterministic evaluators consume."""
        return self.model_dump(exclude_unset=True)


class EvalCase(BaseModel):
    """One eval case. ``finding`` is the raw input; ``expected`` holds the
    golden labels the deterministic evaluators check; ``abstain`` marks a
    case where the agent MUST decline (no CVE / post-cutoff)."""

    id: str
    tier: Tier = "live"
    edge_case: str | None = None
    abstain: bool = False
    finding: dict[str, Any]
    expected: Expected = Field(default_factory=Expected)


def load_cases(agent: str, *, tier: Tier | None = None) -> list[EvalCase]:
    """Load ``<agent>.jsonl`` from the active dataset dir into typed cases."""
    path = dataset_dir() / f"{agent}.jsonl"
    if not path.is_file():
        hint = ""
        if not os.environ.get("CLIFF_EVAL_DATASET_DIR"):
            # The in-repo synthetic sample isn't packaged in the wheel (tests/
            # is excluded), so a wheel-installed consumer must point at its own
            # dataset dir rather than rely on the default.
            hint = (
                " — set CLIFF_EVAL_DATASET_DIR (the sample dataset ships only"
                " in a source checkout, not the installed package)"
            )
        raise FileNotFoundError(f"No eval dataset for {agent!r} at {path}{hint}")
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
