"""Cliff agent-evaluation harness (ADR-0050).

A thin, generic layer over ``pydantic-evals``: a per-agent registry, an
adapter that drives any agent through one call, and a small set of custom
evaluators. Datasets live as JSONL under ``backend/tests/agents/eval/``.

Two lanes (ADR-0050 §5):

* **CI** — deterministic, ``FunctionModel``/``TestModel``, every push. Proves
  the evaluators + adapter are correct without a key.
* **Live** — key-gated, real model, measures actual agent quality.

The first agent wired is ``finding_enricher`` (the reference implementation,
ADR-0050 rollout §7).
"""

from cliff.evals.adapter import run_agent
from cliff.evals.cases import EvalCase, dataset_dir, load_cases
from cliff.evals.registry import AgentEvalSpec, get_spec
from cliff.evals.runners import EvalRunResult, run_enricher_eval

__all__ = [
    "AgentEvalSpec",
    "EvalCase",
    "EvalRunResult",
    "dataset_dir",
    "get_spec",
    "load_cases",
    "run_agent",
    "run_enricher_eval",
]
