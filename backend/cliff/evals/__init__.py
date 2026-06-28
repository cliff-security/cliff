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
from cliff.evals.corpus import (
    CorpusCaseResult,
    Scorecard,
    run_triage_corpus_eval,
    score_corpus,
)
from cliff.evals.models import eval_runnable, harvest_env, select_eval_model
from cliff.evals.registry import AgentEvalSpec, get_spec
from cliff.evals.runners import (
    EvalRunResult,
    make_live_deep_dive_pipeline,
    run_deep_dive_eval,
    run_enricher_eval,
    run_report_triager_eval,
    run_triage_synthesis_eval,
)

__all__ = [
    "AgentEvalSpec",
    "CorpusCaseResult",
    "EvalCase",
    "EvalRunResult",
    "Scorecard",
    "dataset_dir",
    "eval_runnable",
    "get_spec",
    "harvest_env",
    "load_cases",
    "make_live_deep_dive_pipeline",
    "run_agent",
    "run_deep_dive_eval",
    "run_enricher_eval",
    "run_report_triager_eval",
    "run_triage_corpus_eval",
    "run_triage_synthesis_eval",
    "score_corpus",
    "select_eval_model",
]
