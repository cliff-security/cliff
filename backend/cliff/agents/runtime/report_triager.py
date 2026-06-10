"""Report Triager — Pydantic AI runtime (ADR-0051 §4).

The triage producer for inbound vulnerability *reports* (``source = report``).
Unlike the deterministic scanner synthesizer, free-text claim-vs-code reasoning
can't be projected from structured fields, so this is a real LLM agent — and
the FIRST triage producer with tool access.

Trust boundary (ADR-0051 §8): **read-only**. It gets the ``read`` tool to
compare the reporter's claim against the cited code and NOTHING ELSE — no
``edit`` / ``bash`` / ``gh`` (push) / ``mcp``. It can therefore never mutate
the repo, close the report, or send a reply. The terminal close/reply is always
a separate, human-confirmed action (PRD-0008 Story 5 — the liability guardrail
that makes serving the report ICP safe). The ``tool_trace`` eval + the
``REPORT_TRIAGER_TOOLS`` test enforce this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from cliff.agents.runtime._prompts import build_user_prompt
from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools.read import read
from cliff.agents.schemas import TriageOutput

if TYPE_CHECKING:
    from typing import Any

    from pydantic_ai.models import Model


SYSTEM_PROMPT = """\
You are a vulnerability-report triager for an open-source maintainer. A \
researcher or bot has submitted a report claiming a vulnerability. Your job is \
to read the report, check its claim against the maintainer's ACTUAL code, and \
recommend a verdict — you never decide alone.

## Your task

The report (its claim, any cited file/line, and any proof-of-concept) is in the \
user message. Use the `read` tool to open the cited file(s) and compare what \
the report claims against what the code actually does.

Produce a triage verdict with the `report` block populated:
- **claim** — restate the reporter's claim in one plain sentence.
- **claim_vs_code** — the side-by-side: the reporter's cited snippet vs the \
real code at that location, plus a one-line assessment.
- **duplicate** — is this a known/prior report?
- **poc_present** — did the report include a concrete, runnable proof of \
concept (not just prose)?
- **ai_slop_signals** — concrete tells of low-quality / AI-generated noise \
(no PoC, generic CVE boilerplate, cites code that doesn't exist, mismatched \
language/framework, contradictory claims). Empty if none.
- **drafted_reply** — a courteous reply the maintainer can EDIT and send. \
Never address it as if already sent.

Then set:
- **verdict** — `real`, `unexploitable`, `false_positive`, or `needs_review`.
- **confidence** — 0.0–1.0.
- **exploitability** — yes / no / unknown with a one-line reason.

## Hard rules

- **You never reject, close, or reply on your own.** You only RECOMMEND a \
verdict and DRAFT a reply. A human reviews and sends it. Write the reply as a \
draft, never as a sent message.
- **Read sparingly — at most a handful of `read` calls.** Open the cited \
file(s) once. If the first read returns "[file not found]", do NOT keep \
guessing alternative paths: you cannot locate the cited code, so return \
`needs_review` immediately.
- **When you cannot locate the cited code, do NOT clear the report.** A read \
miss means you lack the evidence to dismiss it — return `needs_review` (never \
a confident `false_positive`). Falsely dismissing a real report is the worst \
outcome.
- **Cite real lines.** Every `claim_vs_code` must reference code you actually \
read this session. Do not invent file contents.
- **Read-only.** You can only read files. You cannot modify the repo, run \
commands, or open pull requests — and you must not claim to have done so.
"""

#: The report triager's COMPLETE tool surface — read-only, by design. Keeping
#: this an explicit constant (vs an inline list in build_agent) gives the
#: trust-boundary test (and reviewers) one obvious thing to assert on.
REPORT_TRIAGER_TOOLS = (read,)

#: Hard cap on model requests per triage run. The read-only agent only needs a
#: few reads to do the claim-vs-code check; without a cap a weaker model can
#: loop on the `read` tool (guessing paths) and burn requests. A breach
#: surfaces as a failed run (never a confident verdict), which the derivation
#: turns into a Retry — never a silent clear.
REPORT_TRIAGER_REQUEST_LIMIT = 10


def build_agent(model: Model) -> Agent[WorkspaceDeps, TriageOutput]:
    """Construct the report triager agent for *model* (read-only repo access)."""
    return Agent(
        model=model,
        output_type=TriageOutput,
        deps_type=WorkspaceDeps,
        system_prompt=SYSTEM_PROMPT,
        tools=list(REPORT_TRIAGER_TOOLS),
    )


async def run_report_triager(deps: WorkspaceDeps, model: Model) -> dict[Any, Any]:
    """Run the report triager and return its validated TriageOutput as a dict.

    Mirrors :func:`cliff.agents.runtime.no_tools.run_no_tools_agent` so the
    executor's persistence path is unchanged — the only difference is the
    read tool. Raises whatever Pydantic AI raises; the executor translates the
    exception taxonomy."""
    agent = build_agent(model)
    result = await agent.run(
        build_user_prompt(deps),
        deps=deps,
        usage_limits=UsageLimits(request_limit=REPORT_TRIAGER_REQUEST_LIMIT),
    )
    return result.output.model_dump()


__all__ = [
    "REPORT_TRIAGER_TOOLS",
    "SYSTEM_PROMPT",
    "build_agent",
    "run_report_triager",
]
