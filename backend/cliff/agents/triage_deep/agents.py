"""The Deep dive's four linear-stage agents (ADR-0052 §2).

gather_facts -> rule_out -> trace_path -> plan_exploit. (The fifth stage,
``challenge``, is an adversarial panel — see ``challenge.py``.) All are
in-process Pydantic AI agents (ADR-0047), **read-only** (read + grep over the
cached clone, nothing else), driven by TestModel/FunctionModel in CI. Verdict
quality is the key-gated eval.

Deps reuse (documented, as for the profile builders): ``WorkspaceDeps`` with
``workspace_dir`` = the repo clone and the prior stage artifacts + repo
knowledge threaded through ``prior_context`` + the rendered prompt.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.usage import UsageLimits

from cliff.agents.runtime.deps import ReadBudget, WorkspaceDeps
from cliff.agents.runtime.tools.grep import grep
from cliff.agents.runtime.tools.read import read
from cliff.agents.schemas import (
    DeepReachability,
    ExploitPlan,
    FindingFacts,
    RuleOutResult,
)

if TYPE_CHECKING:
    from pydantic_ai.models import Model

#: The Deep dive's COMPLETE tool surface — read-only (ADR-0052 §3). One constant
#: the trust-boundary test asserts on.
DEEP_DIVE_TOOLS = (read, grep)

#: trace_path / challenge can read several files on a real repo; cap so a weak
#: model can't loop forever. A breach degrades the stage (the runner routes it to
#: needs_review), it never crashes the pipeline.
DEEP_DIVE_REQUEST_LIMIT = 40

#: Cumulative read/grep byte cap per stage run (ADR-0052). Bounds context so a
#: large real repo can't overflow the model window — ~120KB ≈ 30K tokens of file
#: content, plenty for the cited file + its callers, far under the 200K limit.
DEEP_DIVE_READ_BUDGET = 120 * 1024

GATHER_PROMPT = """\
You are pinning down a vulnerability finding in THIS repository. Using `read` \
and `grep`, locate the root cause in this repo's actual code (file:line \
candidates), identify the vulnerability class, and state the entry-point \
hypothesis. Collect the static evidence later stages will reuse so they don't \
re-locate it. For an inbound report, also extract the reporter's claim. Read \
sparingly: open only the specific file(s) the finding names and `grep` for \
symbols, not the whole repo — you have a limited read budget for this analysis."""

RULE_OUT_PROMPT = """\
Decide whether this finding can be ruled out cheaply, BEFORE any expensive \
reachability analysis. Work through the false-positive catalog:
- root cause only in test / fixture / example / vendored / dead code (use the \
code map) -> kill_class=root_cause_in_nonship_code
- a dispatcher-level gate or a downstream consumer that filters the input \
-> dispatcher_gate / downstream_filter
- gated behind a production-default-off flag -> production_default_off
- a duplicate of a known/fixed issue (use the threat history) -> duplicate_of_known
- a sibling site has the guard (walk-the-parallel-guard) or a surrounding \
catch frame (walk-the-catch-frame)
- not reachable by design -> not_reachable_by_design
If a kill applies, set killed=true with the kill_class and file:line evidence, \
and recommend `false_positive` (not a real issue) or `unexploitable` (real \
advisory, not reachable here). Otherwise killed=false and list the surviving \
concerns.

A kill is a STRONG claim that the finding is not real, it ENDS the analysis \
before reachability and the adversarial review ever run, and falsely killing a \
real vulnerability is the worst possible outcome. So you may ONLY kill on a \
STRUCTURAL false-positive that needs no judgement about whether the code is \
"safe":
  (a) the root cause lives only in non-shipping code (confirmed via the code map),
  (b) it is a confirmed duplicate of an already-fixed issue (threat history),
  (c) it is gated behind a production-default-off flag you can see is off,
  (d) the sink has no caller anywhere (dead code).
Anything that turns on judging whether a guard, validation, or sanitizer makes \
the code safe is NOT a rule_out kill — that is a reachability DISPROOF. In that \
case set killed=false and let Trace the path establish the specific guard at a \
file:line (which the challenge panel then checks). When in any doubt, killed=false."""

TRACE_PROMPT = """\
Determine whether an attacker can actually REACH the vulnerable code AND control \
the dangerous behaviour. Walk from a user-controlled entry point to the sink with \
file:line at EVERY hop, using `read` and `grep`.

CRITICAL — hunt for a neutralizing guard BEFORE you conclude reached=yes. Open \
EVERY function on the path, INCLUDING the helpers it calls (follow them with \
`read`), and look for a validation / sanitization / confinement / authorization \
check that strips the attacker's control before the sink. A guard tucked inside a \
helper (e.g. an `is_safe_path(...)`, `validate(...)`, `normalize(...)`, or an \
allow-list check whose failure aborts the request) STILL counts: a sink is only \
reachable if the attacker's input survives every such check on the way to it. \
Apply and record which disciplines you used:
- walk-the-catch-frame (a surrounding catch neutralizes it)
- walk-the-parallel-guard (a sibling site / the entry function holds the guard)
- walk-the-downstream-gate (a consumer downstream validates the input)
- runtime-overrides-summarized-source (reachable in the real build, not behind a \
disabled flag)
- tail-call-vs-post-call
If a guard neutralizes the attack and you cannot demonstrate a concrete bypass, \
return reached=no with the disproof (the guard's file:line and why it blocks the \
attack). If the path is clear of any such guard, return reached=yes with the path \
(source -> hops -> sink). If undeterminable, reached=unknown. AI confidence is not \
a vulnerability — no hop, and no guard, without a file:line you actually read."""

PLAN_PROMPT = """\
The vulnerability is reachable. Lay out how it could be exploited: ranked \
hypotheses, each with the trigger condition, the attacker input that reaches \
the sink (file:line), the expected impact and impact_class, and a docker repro \
recipe (setup steps, trigger, expected observation). DO NOT run anything — \
author the plan only; it is a plan, not a demonstrated exploit. If despite \
reachability there is no credible exploit (an architectural gap, hardening not \
a vuln), set no_credible_exploit=true."""


def _agent(model: Model, output_type: type, system_prompt: str) -> Agent:
    return Agent(
        model=model,
        output_type=output_type,
        deps_type=WorkspaceDeps,
        system_prompt=system_prompt,
        tools=list(DEEP_DIVE_TOOLS),
    )


def build_gather_facts_agent(model: Model) -> Agent[WorkspaceDeps, FindingFacts]:
    return _agent(model, FindingFacts, GATHER_PROMPT)


def build_rule_out_agent(model: Model) -> Agent[WorkspaceDeps, RuleOutResult]:
    return _agent(model, RuleOutResult, RULE_OUT_PROMPT)


def build_trace_path_agent(model: Model) -> Agent[WorkspaceDeps, DeepReachability]:
    return _agent(model, DeepReachability, TRACE_PROMPT)


def build_plan_exploit_agent(model: Model) -> Agent[WorkspaceDeps, ExploitPlan]:
    return _agent(model, ExploitPlan, PLAN_PROMPT)


def render_context(deps: WorkspaceDeps) -> str:
    """The data blob handed to a stage agent: the finding + the prior artifacts /
    repo knowledge it declared in ``prior_context``."""
    parts = [f"## Finding\n{json.dumps(deps.finding, indent=2, default=str)}"]
    for key, value in deps.prior_context.items():
        if value:
            parts.append(f"## {key}\n{json.dumps(value, indent=2, default=str)}")
    return "\n\n".join(parts)


#: Provider statuses worth retrying — rate limit / transient overload (e.g.
#: Gemini's 503 "high demand"). Anything else surfaces.
_TRANSIENT_STATUS = frozenset({429, 503})


async def run_agent_with_retry(
    agent: Agent, prompt: str, deps: WorkspaceDeps, *, attempts: int = 12
):
    """Run *agent*, retrying transient provider errors (429/503) with backoff.

    Gemini's AI-Studio tier returns intermittent 503 "high demand" that typically
    clears within ~2s, so MANY SHORT retries beat a few long ones: a capped
    exponential backoff (1, 2, 4, 4, … up to 4s) across enough attempts that a
    multi-call pipeline can push through a saturated window instead of one
    unlucky call collapsing the whole Deep dive to needs_review."""
    for i in range(attempts):
        try:
            return await agent.run(
                prompt,
                deps=deps,
                usage_limits=UsageLimits(request_limit=DEEP_DIVE_REQUEST_LIMIT),
            )
        except ModelHTTPError as exc:
            if exc.status_code in _TRANSIENT_STATUS and i < attempts - 1:
                await asyncio.sleep(min(2**i, 4))
                continue
            raise
        except httpx.TransportError:  # ReadTimeout/ConnectError/etc. — a hung or
            # dropped connection is transient like a 503; retry rather than
            # collapsing the whole case to needs_review on one stalled request.
            if i < attempts - 1:
                await asyncio.sleep(min(2**i, 4))
                continue
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


async def _run(agent: Agent, deps: WorkspaceDeps) -> dict:
    # Fresh per-stage read budget so cumulative tool output can't overflow the
    # context window on a large real repo (ADR-0052).
    deps = replace(deps, read_budget=ReadBudget(DEEP_DIVE_READ_BUDGET))
    result = await run_agent_with_retry(agent, render_context(deps), deps)
    return result.output.model_dump()


async def run_gather_facts(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(build_gather_facts_agent(model), deps)


async def run_rule_out(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(build_rule_out_agent(model), deps)


async def run_trace_path(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(build_trace_path_agent(model), deps)


async def run_plan_exploit(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(build_plan_exploit_agent(model), deps)


__all__ = [
    "DEEP_DIVE_REQUEST_LIMIT",
    "DEEP_DIVE_TOOLS",
    "build_gather_facts_agent",
    "build_plan_exploit_agent",
    "build_rule_out_agent",
    "build_trace_path_agent",
    "render_context",
    "run_gather_facts",
    "run_plan_exploit",
    "run_rule_out",
    "run_trace_path",
]
