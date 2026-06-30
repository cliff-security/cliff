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
import os
from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.settings import ModelSettings
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

def _int_env(name: str, default: int) -> int:
    """Positive-int env override, falling back to *default* on a missing or
    malformed value. This module is imported by the LIVE triage path (not just
    the eval), so a typo like ``CLIFF_DEEP_DIVE_TOKEN_LIMIT_CHEAP=200k`` must not
    crash all triage with a ValueError at import time."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return val if val > 0 else default


#: Per-stage cumulative token ceilings (input+output across the whole tool-loop of
#: one agent.run). Each tool call re-sends the GROWING conversation, so an N-call
#: loop costs ~O(N²) input tokens — a single large-repo stage was measured at
#: ~670K cheap-tier tokens before it overflowed the window and 400'd ("prompt too
#: long"), having billed every request on the way to the wall. A breach raises
#: ``UsageLimitExceeded`` (the runner degrades it to ``incomplete``) at a BOUNDED
#: cost instead of send-fail-bill.
#:
#: TIERED because the windows differ. The CHEAP tier is haiku (200K window) — cap
#: below it to bound the runaway AND avoid the overflow-400. The STRONG/JUDGE tiers
#: are sonnet/opus (1M window): a single flat 200K cap would clip a legitimately
#: deep trace/plan/challenge into ``incomplete`` (a recall regression), so they get
#: a higher ceiling that still bounds a true unbounded loop and opus cost while
#: leaving room for real analysis. Both env-tunable.
DEEP_DIVE_TOKEN_LIMIT_CHEAP = _int_env("CLIFF_DEEP_DIVE_TOKEN_LIMIT_CHEAP", 180_000)
DEEP_DIVE_TOKEN_LIMIT_STRONG = _int_env("CLIFF_DEEP_DIVE_TOKEN_LIMIT_STRONG", 800_000)

#: Cumulative read/grep byte cap per stage run (ADR-0052). Bounds context so a
#: large real repo can't overflow the model window — ~120KB ≈ 30K tokens of file
#: content, plenty for the cited file + its callers, far under the 200K limit.
DEEP_DIVE_READ_BUDGET = 120 * 1024

#: Deterministic decoding for every deep-dive agent. Security triage must be
#: REPRODUCIBLE — the same finding + code should yield the same verdict, not a
#: dice roll that flips real/needs_review between runs. Perspective diversity in
#: the challenge panel comes from the LENSES, not from sampling temperature.
DEEP_DIVE_MODEL_SETTINGS = ModelSettings(temperature=0.0)

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
A switch to a SAFE API also counts as a guard — if the dangerous operation has \
been REPLACED by a safe equivalent on the path, the original sink is no longer \
reachable: e.g. a safe loader (`yaml.safe_load`), a sandboxed evaluator \
(`SandboxedEnvironment`), an extraction call with security flags (libarchive \
`EXTRACT_SECURE_*`, a `safe_join`/`tar_xf`-style wrapper), a parameterized query, \
an escaping helper (`escape_filter_chars`), or a redirect/return that branches \
away before the sink. INLINE sanitization right before the sink ALSO counts — a \
loop or block that validates/rewrites the attacker data before it reaches the \
sink (e.g. rejecting or stripping `../` from archive member names, or checking \
each `realpath` stays within a base dir, before `extractall`) confines it: read \
the lines IMMEDIATELY ABOVE the sink, not just the sink call. A check that \
REJECTS the attacker's malicious input — raising/aborting/erroring when the value \
is dangerous (an allow-list whose miss raises, `if not is_local_uri(...): raise`, \
a stricter validator that now rejects the documented payload) — likewise confines \
the sink: the attacker can't drive the DANGEROUS behaviour even though the sink \
line still runs for legitimate input. Ask: is there a check on the path that \
rejects the SPECIFIC malicious input this finding describes? But do NOT invent \
one — if no such check exists (the genuinely-vulnerable case) the sink IS \
reachable, reached=yes. When several similar sinks exist, assess the one on the \
path the FINDING names (follow its entry point), not an unrelated lookalike \
elsewhere. Apply and record which disciplines you used:
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
        model_settings=DEEP_DIVE_MODEL_SETTINGS,
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
    agent: Agent,
    prompt: str,
    deps: WorkspaceDeps,
    *,
    attempts: int = 12,
    total_tokens_limit: int = DEEP_DIVE_TOKEN_LIMIT_STRONG,
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
                usage_limits=UsageLimits(
                    request_limit=DEEP_DIVE_REQUEST_LIMIT,
                    # Per-tier cumulative-token ceiling: stop a ballooning tool-loop
                    # BEFORE it overflows the window and bills the doomed request. A
                    # breach raises UsageLimitExceeded, which DeepDiveRunner.run
                    # catches and degrades to incomplete (never a crash, never a
                    # false clear) — bounded cost. The caller passes the cheap vs
                    # strong/judge ceiling so a deep 1M-window stage isn't clipped.
                    total_tokens_limit=total_tokens_limit,
                ),
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


async def _run(agent: Agent, deps: WorkspaceDeps, *, total_tokens_limit: int) -> dict:
    # Fresh per-stage read budget so cumulative tool output can't overflow the
    # context window on a large real repo (ADR-0052).
    deps = replace(deps, read_budget=ReadBudget(DEEP_DIVE_READ_BUDGET))
    result = await run_agent_with_retry(
        agent, render_context(deps), deps, total_tokens_limit=total_tokens_limit
    )
    return result.output.model_dump()


# gather_facts + rule_out run on the CHEAP tier (haiku, 200K window); trace_path +
# plan_exploit run on the STRONG tier (sonnet, 1M window). Each passes its tier's
# token ceiling so the 1M-window stages aren't clipped by the cheap cap. (The judge
# challenge panel calls run_agent_with_retry directly and gets the STRONG default.)
async def run_gather_facts(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(
        build_gather_facts_agent(model), deps, total_tokens_limit=DEEP_DIVE_TOKEN_LIMIT_CHEAP
    )


async def run_rule_out(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(
        build_rule_out_agent(model), deps, total_tokens_limit=DEEP_DIVE_TOKEN_LIMIT_CHEAP
    )


async def run_trace_path(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(
        build_trace_path_agent(model), deps, total_tokens_limit=DEEP_DIVE_TOKEN_LIMIT_STRONG
    )


async def run_plan_exploit(deps: WorkspaceDeps, model: Model) -> dict:
    return await _run(
        build_plan_exploit_agent(model), deps, total_tokens_limit=DEEP_DIVE_TOKEN_LIMIT_STRONG
    )


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
