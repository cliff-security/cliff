"""AgentExecutor — runs a single sub-agent end-to-end.

The executor is the bridge between "user wants to run an agent" and
"agent results are persisted everywhere." It sends a prompt to the
workspace's OpenCode process, collects the response, parses it, and
persists results to context files, sidebar state, and the DB.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx

from opensec.agents.errors import (
    AgentBusyError,
    AgentProcessError,
    AgentRateLimitError,
    AgentTimeoutError,
)
from opensec.agents.output_parser import ParseResult, parse_agent_response
from opensec.agents.sidebar_mapper import map_and_upsert
from opensec.agents.template_engine import AgentTemplateEngine
from opensec.db.repo_agent_run import (
    create_agent_run,
    list_agent_runs,
    update_agent_run,
)
from opensec.db.repo_finding import get_finding, update_finding
from opensec.db.repo_workspace import get_workspace
from opensec.models import AgentRunCreate, AgentRunUpdate, FindingUpdate
from opensec.services.evidence_guard import guard_evidence_output
from opensec.services.pr_verifier import verify_pr_url
from opensec.services.reference_verifier import clean_references
from opensec.workspace.context_document import ContextDocument
from opensec.workspace.workspace_dir import AGENT_TYPE_TO_SECTION, CONTEXT_SECTIONS

if TYPE_CHECKING:
    from collections.abc import Callable

    import aiosqlite

    from opensec.engine.pool import WorkspaceProcessPool
    from opensec.workspace.context_builder import WorkspaceContextBuilder

logger = logging.getLogger(__name__)

# Overall ceiling for a non-tool agent run — a generous backstop, not the
# primary failure mechanism. Under low concurrency a structured-output
# completion finishes in well under 20 s, but under ~6-way concurrency the
# provider serialises/rate-limits and a *still-progressing* run can take
# 80-120 s (Q01-B12 — a tighter 75 s ceiling killed those mid-stream). The
# real fast-fail for a genuinely *hung* agent is the no-output stall in
# ``_collect_response`` (Q01-B10), which fires long before this. Tool
# agents (remediation_executor) override this — see ``execute`` — to 600 s.
DEFAULT_TIMEOUT: float = 150.0
# Extra buffer for asyncio.wait_for when permission waits are possible.
# The real timeout is enforced by stall detection, which accounts for
# time spent waiting for user permission decisions.
PERMISSION_WAIT_BUFFER: float = 600.0

# ---------------------------------------------------------------------------
# Provider rate-limit backoff (EF-B17)
# ---------------------------------------------------------------------------
# Upstream LLM providers (Anthropic, OpenRouter, OpenAI) start returning 429
# when the workspace pool runs more than one concurrent agent. OpenCode wraps
# the upstream 429 into a ``session.error`` SSE event that surfaces to the
# executor as an ``AgentRateLimitError``. Under pool>=2 (the Wave-2 cap)
# this used to fail the run on the first throttle; we now retry with
# exponential backoff + jitter up to ``RATE_LIMIT_MAX_ATTEMPTS`` before
# terminating the run with status ``rate_limited``.
#
# Tests monkey-patch these to 0.0 to avoid sleeping in unit suites.
RATE_LIMIT_MAX_ATTEMPTS: int = 3
RATE_LIMIT_BASE_DELAY_SECONDS: float = 2.0
RATE_LIMIT_MAX_DELAY_SECONDS: float = 16.0

# Substring signals that an OpenCode error message wraps an upstream
# provider rate-limit. Single source of truth — ``_humanize_process_error``
# below uses the same set to render the user-facing copy.
_RATE_LIMIT_SUBSTRINGS: tuple[str, ...] = (
    "rate limit",
    "429",
    "too many requests",
)


def _looks_like_rate_limit(message: str) -> bool:
    """Return True if ``message`` carries any of the rate-limit signals."""
    lowered = message.lower()
    return any(s in lowered for s in _RATE_LIMIT_SUBSTRINGS)


def _rate_limit_backoff_delay(attempt: int) -> float:
    """Exponential backoff with full jitter for retry ``attempt`` (1-based).

    attempt=1 -> base, attempt=2 -> 2*base, attempt=3 -> 4*base, capped at
    ``RATE_LIMIT_MAX_DELAY_SECONDS``. Adds up to one base-delay of jitter
    so concurrent workspaces don't all wake at the same instant.
    """
    base = RATE_LIMIT_BASE_DELAY_SECONDS
    exp = base * (2 ** max(attempt - 1, 0))
    jitter = random.uniform(0.0, base) if base > 0 else 0.0
    return min(exp + jitter, RATE_LIMIT_MAX_DELAY_SECONDS)

# ---------------------------------------------------------------------------
# Permission tier classification for tool-use approval.
# Keys are the "permission" field from OpenCode's permission.asked events.
# "auto" = grant immediately, "user" = surface to user for approval.
# Unknown tools default to "user" (safe default).
# ---------------------------------------------------------------------------

TOOL_TIERS: dict[str, str] = {
    "read": "auto",
    "webfetch": "auto",
    "bash": "user",
    "edit": "user",
    "mcp": "user",
}

# Agents that need tool access to do their job (e.g. git, gh CLI).
# Their bash/edit requests are classified per-command (see
# ``_classify_tool_request``) rather than blanket-approved.
_TOOL_AGENT_TYPES: set[str] = {"remediation_executor"}

# Tool-request classification for the remediation_executor. Three tiers:
#   "auto"  — grant immediately (routine git/gh/build commands)
#   "ask"   — escalate to the user for approval (destructive-but-conceivable,
#             or reaching outside the workspace)
#   "deny"  — reject immediately without asking (never legitimate for a
#             remediation agent; denying gives the agent fast feedback
#             instead of stalling on an approval that will never come)
#
# This is a denylist — defense-in-depth against a *confused* agent, layered
# on top of GIT_CEILING_DIRECTORIES and the hardened agent prompt. It is NOT
# a security boundary against a malicious agent; that needs process
# sandboxing (separate ADR). The remediation_executor's normal workflow
# (git clone/checkout/add/commit/push, gh pr create, build/test runners)
# matches none of these patterns and stays on the "auto" path.

# Never legitimate — hard-deny, don't even ask.
_CATASTROPHIC_BASH: tuple[str, ...] = (
    ":(){",          # fork bomb
    "mkfs",
    " dd ",
    "sudo ",
    "> /etc",
    ">/etc",
    "> /usr",
    ">/usr",
    "> /bin",
    ">/bin",
    "/etc/shadow",
    "/etc/passwd",
)

# Destructive or workspace-escaping, but conceivably part of a real fix —
# escalate to the user rather than hard-deny. (Per CEO: "removing a file
# requires asking for permission.")
_GATED_BASH: tuple[str, ...] = (
    "rm -",          # rm -rf, rm -f, …
    "rmdir",
    "git reset --hard",
    "git clean",
    "git push --force",
    "git push -f",
    "chmod ",
    "chown ",
    "cd /",
    "cd ~",
    "$home",
    "~/.ssh",
    "~/.aws",
    "~/.config",
)


def _is_pipe_to_shell(cmd: str) -> bool:
    """``curl …`` / ``wget …`` are fine on their own; piped into a shell
    they're remote code execution. Only the piped shape is dangerous."""
    fetches = ("curl ", "wget ")
    shells = ("| sh", "|sh", "| bash", "|bash", "|sh ", "| sh ")
    return any(f in cmd for f in fetches) and any(s in cmd for s in shells)


def _classify_tool_request(tool: str, patterns: list[str]) -> str:
    """Return ``"auto"``, ``"ask"``, or ``"deny"`` for an executor tool call.

    - ``bash`` — ``deny`` for catastrophic commands, ``ask`` for
      destructive-but-conceivable ones (rm, git reset --hard, …),
      ``auto`` for everything else.
    - ``edit`` — ``ask`` if the target path is absolute or climbs out of
      the workspace via ``..``; otherwise ``auto``.
    - ``external_directory`` — ``ask``. OpenCode raises this permission
      precisely when a tool reaches *outside* the workspace cwd, so it is
      the literal "the agent tried to leave the directory" signal.
    - anything else / unparseable — ``ask`` (safe default).
    """
    if tool == "external_directory":
        return "ask"

    if tool == "bash":
        cmd = " ".join(patterns).lower() if patterns else ""
        if not cmd:
            return "ask"  # can't inspect it → don't blanket-approve
        if _is_pipe_to_shell(cmd):
            return "deny"
        if any(bad in cmd for bad in _CATASTROPHIC_BASH):
            return "deny"
        if any(bad in cmd for bad in _GATED_BASH):
            return "ask"
        return "auto"

    if tool == "edit":
        for path in patterns:
            p = path.strip()
            if p.startswith("/") or p.startswith("~") or "../" in p:
                return "ask"
        return "auto"

    # mcp, unknown tools
    return "ask"


@dataclass
class _PendingApproval:
    """Tracks a permission request waiting for user approval."""

    permission_id: str
    tool: str
    patterns: list[str]
    event: asyncio.Event
    approved: bool | None = None

# ---------------------------------------------------------------------------
# Per-agent output contracts (inlined in the prompt so the LLM always sees
# the exact schema, regardless of workspace state or session history).
# ---------------------------------------------------------------------------

_STRUCTURED_OUTPUT_CONTRACTS: dict[str, str] = {
    "finding_enricher": """\
"structured_output": {
    "normalized_title": "string — clear, jargon-free title",
    "cve_ids": ["CVE-YYYY-NNNNN"] or [],
    "cvss_score": 0.0-10.0 or null,
    "cvss_vector": "CVSS:3.1/AV:N/AC:L/..." or null,
    "description": "what the vulnerability is and how it works",
    "affected_versions": "version range, e.g. '< 2.3.1'" or null,
    "fixed_version": "minimum fixed version" or null,
    "known_exploits": true/false,
    "exploit_details": "exploit maturity info" or null,
    "references": ["https://..."] or []
}""",
    "owner_resolver": """\
"structured_output": {
    "recommended_owner": "string — team or person name",
    "candidates": [{"name": "...", "confidence": 0.0-1.0, "reason": "..."}],
    "reasoning": "why this owner was chosen"
}""",
    "exposure_analyzer": """\
"structured_output": {
    "recommended_urgency": "critical/high/medium/low",
    "environment": "production/staging/development" or null,
    "internet_facing": true/false or null,
    "reachable": "description of reachability" or null,
    "reachability_evidence": "evidence for reachability assessment" or null,
    "business_criticality": "description" or null,
    "blast_radius": "description of impact scope" or null
}""",
    "remediation_planner": """\
"structured_output": {
    "plan_steps": ["step 1", "step 2", ...],
    "definition_of_done": ["criterion 1", ...],
    "interim_mitigation": "immediate mitigation" or null,
    "dependencies": ["dependency 1", ...],
    "estimated_effort": "e.g. 2-4 hours" or null,
    "validation_method": "how to verify the fix" or null
}""",
    "validation_checker": """\
"structured_output": {
    "verdict": "fixed/not_fixed/partially_fixed/inconclusive",
    "recommendation": "close/reopen/needs_more_info",
    "evidence": "what evidence supports the verdict" or null,
    "remaining_concerns": ["concern 1", ...]
}""",
    "evidence_collector": """\
"structured_output": {
    "affected_files": [
        {"path": "relative/path", "line": null,
         "context": "what was found",
         "file_type": "lock_file|manifest|source|config|test"}
    ],
    "dependency_chain": ["pkg_a depends on pkg_b depends on vulnerable_pkg"],
    "dependency_type": "direct|transitive",
    "current_version": "version string likely in repo" or null,
    "fix_safety": "safe_bump|breaking_change|needs_migration|code_fix",
    "fix_safety_reasoning": "why this classification was chosen",
    "test_coverage": {
        "relevant_tests": [],
        "has_coverage": true/false,
        "notes": "observations"
    },
    "recommended_approach": "concise description of safest fix approach",
    "impact_assessment": "what will change and what risks exist"
}""",
    "remediation_executor": """\
"structured_output": {
    "status": "pr_created/changes_made/failed/needs_approval",
    "pr_url": "https://github.com/.../pull/N" or null,
    "branch_name": "opensec/fix/..." or null,
    "changes_summary": "what files were changed and why",
    "test_results": "pass/fail/skipped" or null,
    "error_details": "description of failure" or null
}""",
}

_AGENT_TYPE_LABELS: dict[str, str] = {
    "finding_enricher": "vulnerability enrichment",
    "owner_resolver": "ownership resolution",
    "exposure_analyzer": "exposure and context analysis",
    "evidence_collector": "evidence collection",
    "remediation_planner": "remediation planning",
    "remediation_executor": "remediation execution",
    "validation_checker": "validation checking",
}

# Per-agent guidance appended to the prompt. Currently only the enricher,
# whose ``references`` array is shipped verbatim into the evidence sidebar
# as authoritative citations — weaker models fabricate specific identifiers
# (404ing GHSA IDs, commit URLs with garbled SHAs). The verifier in the
# executor is the deterministic safety net; this just lowers the rate at
# the source. (Q01-B08.)
_AGENT_GUIDANCE: dict[str, str] = {
    "finding_enricher": (
        "## Reference rules (strict)\n\n"
        "The \"references\" array is shown to a security engineer as "
        "authoritative citations. A fabricated citation is worse than a "
        "missing one.\n\n"
        "- ONLY include a URL you are confident resolves. When unsure, "
        "omit it — a short all-real list beats a long list with one "
        "fabricated entry.\n"
        "- Prefer the NVD page for a CVE you cite "
        "(https://nvd.nist.gov/vuln/detail/<CVE>) and generic "
        "authoritative docs (OWASP, CWE/MITRE, the vendor advisory index).\n"
        "- NEVER invent a GitHub advisory (GHSA-...) ID or a commit SHA. "
        "If you have not actually seen a specific identifier, do not "
        "construct one — omit the reference entirely.\n"
    ),
    "evidence_collector": (
        "## Completeness rules\n\n"
        "Every field must be a genuine best-effort answer — an empty "
        "``affected_files`` or a null ``current_version`` is a worse "
        "outcome than an imperfect one.\n\n"
        "- ``current_version``: the version currently in the repo. The "
        "finding's asset label already carries it (e.g. ``minimist@1.2.5`` "
        "-> ``1.2.5``) — never return null for a dependency finding.\n"
        "- ``affected_files``: for a dependency finding the manifest and "
        "lock files that pin the package (``package.json``, "
        "``package-lock.json``, ``yarn.lock``, …) are always affected — "
        "list them rather than returning an empty array.\n"
        "- ``fix_safety``: a major-version jump (e.g. 4.x -> 7.x) is "
        "``breaking_change`` or worse — never ``safe_bump``.\n"
    ),
}


def _load_workspace_data(
    workspace_dir: str, agent_type: str
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Read finding data and prior agent results from the workspace directory.

    Returns (finding_dict, prior_context_dict). Prior context only includes
    sections from agents earlier in the pipeline than the current one.
    """
    import json

    ctx_dir = Path(workspace_dir) / "context"

    # Read finding — must exist
    finding_path = ctx_dir / "finding.json"
    if not finding_path.exists():
        raise AgentProcessError(
            f"finding.json missing from workspace: {workspace_dir}"
        )
    finding = json.loads(finding_path.read_text())

    # Read prior context — only sections before this agent in the pipeline
    current_section = AGENT_TYPE_TO_SECTION.get(agent_type)
    if current_section:
        cutoff = CONTEXT_SECTIONS.index(current_section)
        prior_sections = CONTEXT_SECTIONS[:cutoff]
    else:
        prior_sections = CONTEXT_SECTIONS

    prior_context: dict[str, dict[str, Any]] = {}
    for section in prior_sections:
        section_path = ctx_dir / f"{section}.json"
        if section_path.exists():
            prior_context[section] = json.loads(section_path.read_text())

    return finding, prior_context


def build_agent_prompt(
    agent_type: str,
    *,
    finding: dict[str, Any],
    prior_context: dict[str, dict[str, Any]] | None = None,
    user_note: str | None = None,
) -> str:
    """Build the execution prompt for a specific agent type.

    Includes the actual finding data and any prior agent results inline,
    so the LLM has everything it needs without reading files.

    ``user_note`` (PRD-0006 Phase 2 / IMPL-0007 §B4) — only meaningful for
    ``agent_type == 'remediation_planner'``. When set, the planner is asked
    to treat it as authoritative refinement input on a re-run.
    """
    label = _AGENT_TYPE_LABELS.get(agent_type, agent_type)
    contract = _STRUCTURED_OUTPUT_CONTRACTS.get(agent_type, "")
    structured_block = f",\n    {contract}" if contract else ""

    # Format finding data using the same renderer as CONTEXT.md
    finding_text = ContextDocument.finding_section(finding)

    # Format prior context if available
    prior_text = ""
    if prior_context:
        knowledge = ContextDocument.knowledge_section(
            prior_context.get("enrichment"),
            prior_context.get("ownership"),
            prior_context.get("exposure"),
        )
        if knowledge:
            prior_text = f"\n{knowledge}\n"

    refinement_text = ""
    if agent_type == "remediation_planner" and user_note:
        refinement_text = (
            "\n## User refinement\n\n"
            "The user reviewed an earlier plan and asked you to revise it "
            "with the following note. Treat this as authoritative — adjust "
            "the plan steps, dependencies, and validation method to honor "
            "this guidance without losing safety.\n\n"
            f"> {user_note}\n"
        )

    guidance = _AGENT_GUIDANCE.get(agent_type, "")
    guidance_text = f"\n{guidance}\n" if guidance else ""

    return f"""\
IMPORTANT: This is a programmatic agent execution request. Respond with ONLY \
a JSON code block — no tool calls, no file reads, no conversation.

{finding_text}{prior_text}{refinement_text}{guidance_text}
Run {label} on the finding above. Respond with a single \
```json code block matching this exact schema:

```json
{{
    "summary": "one-line summary of your analysis",
    "result_card_markdown": "## Heading\\n\\nMarkdown-formatted detailed results",
    "confidence": 0.0-1.0,
    "evidence_sources": ["source1", "source2"],
    "suggested_next_action": "next agent type or action to take"{structured_block}
}}
```

Respond with ONLY the JSON block above. No preamble, no explanation, no tool use."""


_RETRY_PROMPT = """\
Your previous response could not be parsed as valid JSON. This is a \
programmatic execution — the output MUST be a single ```json code block and \
nothing else. Do not use tools, do not read files, do not add explanation \
text. Respond now with ONLY the JSON block in the exact schema requested."""


# ---------------------------------------------------------------------------
# Finding status auto-advance after agent completions (WP6 / T6.1).
# Status only moves forward — never regresses.
# ---------------------------------------------------------------------------

_STATUS_ORDINAL: dict[str, int] = {
    "new": 0,
    "triaged": 1,
    "in_progress": 2,
    "remediated": 3,
    "validated": 4,
    "closed": 5,
    "exception": 5,
}

# Agents that unconditionally advance status (forward-only check still applies).
_AGENT_STATUS_ADVANCE: dict[str, str] = {
    "finding_enricher": "triaged",
    "remediation_planner": "in_progress",
}


async def _advance_finding_status(
    db: aiosqlite.Connection,
    workspace_id: str,
    agent_type: str,
    structured_output: dict[str, Any],
) -> str | None:
    """Advance the finding status if appropriate after an agent completion.

    Returns the new status string if advanced, or None if no change.
    Status only moves forward (higher ordinal) — never regresses.
    """
    # 1. Determine target status
    target = _AGENT_STATUS_ADVANCE.get(agent_type)

    if agent_type == "remediation_executor" and structured_output.get("status") == "pr_created":
        target = "remediated"
    elif agent_type == "validation_checker" and structured_output.get("verdict") == "fixed":
        target = "validated"

    if not target:
        return None

    # 2. Resolve workspace -> finding
    workspace = await get_workspace(db, workspace_id)
    if not workspace:
        return None
    finding = await get_finding(db, workspace.finding_id)
    if not finding:
        return None

    # 3. Forward-only check
    current_ord = _STATUS_ORDINAL.get(finding.status, 0)
    target_ord = _STATUS_ORDINAL.get(target, 0)
    if target_ord <= current_ord:
        return None

    # 4. Update — also persist pr_url when the executor successfully opened a
    # PR (EF-B14). The pr_url has already been verified live on GitHub by
    # the verification step earlier in run(), so we know it's real. Skip the
    # write when the Finding already has a pr_url so an explicit user-supplied
    # value (PATCH /findings/{id}) is never clobbered.
    update_fields: dict[str, Any] = {"status": target}
    if (
        agent_type == "remediation_executor"
        and structured_output.get("status") == "pr_created"
        and structured_output.get("pr_url")
        and not finding.pr_url
    ):
        update_fields["pr_url"] = structured_output["pr_url"]
    await update_finding(db, finding.id, FindingUpdate(**update_fields))
    logger.info(
        "Finding %s status advanced: %s -> %s (agent: %s)",
        finding.id, finding.status, target, agent_type,
    )
    return target


def _humanize_process_error(raw: str) -> str:
    """Map opaque ``AgentProcessError`` strings to actionable user-facing text.

    Most agent failures actually originate at the AI provider (OpenRouter,
    Anthropic, OpenAI) and reach us through OpenCode as opaque "OpenCode
    error: …" wrappers. We unwrap the common ones — insufficient credits,
    rate limits, unauthorized — into short markdown the sidebar can render
    verbatim, with a remediation link where one exists. Falling back on the
    raw string is fine for unknown cases since it still surfaces in
    ``evidence_json`` for debugging.
    """
    lowered = raw.lower()
    if "more credits" in lowered or (
        "insufficient" in lowered and "credit" in lowered
    ):
        return (
            "**Out of AI provider credits.** OpenRouter rejected the request "
            "because your account balance can't fund this agent run. "
            "[Add credits](https://openrouter.ai/settings/credits) or switch "
            "to a cheaper model in Settings → AI provider, then click "
            "Approve to retry."
        )
    if "rate limit" in lowered or "429" in lowered or "too many requests" in lowered:
        return (
            "**AI provider rate limit hit.** The provider asked us to slow "
            "down. Wait a minute and click Approve to retry, or switch to a "
            "different model in Settings → AI provider."
        )
    if (
        "unauthorized" in lowered
        or "401" in lowered
        or "invalid api key" in lowered
        # Anthropic/OpenAI return this verbatim when the outbound request
        # carries no credential at all — the BYOK auth-propagation failure
        # mode. It is deterministic, so surface the actionable message
        # immediately rather than letting it read as a generic engine error.
        or "missing authentication" in lowered
        or "authentication header" in lowered
    ):
        return (
            "**AI provider rejected the credentials.** The configured API "
            "key is missing, revoked, or wrong for this model. Re-connect "
            "the provider in Settings → AI provider."
        )
    if "context length" in lowered or "context_length_exceeded" in lowered:
        return (
            "**Request exceeded the model's context window.** The finding "
            "or workspace context is too large for the configured model. "
            "Try a higher-context model in Settings → AI provider."
        )
    # Unknown — surface the raw text so the user has *something* to act on,
    # rather than the previous generic "Workspace AI engine unavailable."
    return f"**Workspace AI engine error.** {raw}"


@dataclass
class AgentExecutionResult:
    """Result returned by the executor after running an agent."""

    agent_run_id: str
    agent_type: str
    # EF-B17 — ``rate_limited`` joins ``failed`` as a non-success terminal
    # state. Callers that key off ``status == 'failed'`` should also treat
    # ``rate_limited`` as terminal-non-success; see ``pipeline.run_pipeline``.
    status: Literal["completed", "failed", "rate_limited"]
    parse_result: ParseResult
    sidebar_updated: bool = False
    context_version: int | None = None
    error: str | None = None
    duration_seconds: float = 0.0


class AgentExecutor:
    """Executes a single sub-agent within a workspace.

    Lifecycle:
        1. Check no other agent is running (→ AgentBusyError)
        2. Create AgentRun DB row (status=running)
        3. Get/start workspace OpenCode process
        4. Create fresh session, send prompt, collect response
        5. Parse response, persist to context + sidebar + DB
        6. Return AgentExecutionResult
    """

    def __init__(
        self,
        pool: WorkspaceProcessPool,
        context_builder: WorkspaceContextBuilder,
    ) -> None:
        self._pool = pool
        self._context_builder = context_builder
        self._pending_approvals: dict[str, _PendingApproval] = {}
        self._permission_queues: dict[str, asyncio.Queue] = {}  # workspace_id -> SSE queue
        self._active_runs: dict[str, str] = {}  # workspace_id -> agent_run_id
        self._permission_pending: dict[str, bool] = {}  # agent_run_id -> pauses stall detection

    def approve_tool(self, run_id: str) -> bool:
        """Approve a pending tool-use permission request.

        Returns True if a pending approval was found and resolved.
        """
        pending = self._pending_approvals.get(run_id)
        if not pending:
            return False
        pending.approved = True
        pending.event.set()
        return True

    def deny_tool(self, run_id: str) -> bool:
        """Deny a pending tool-use permission request.

        Returns True if a pending approval was found and resolved.
        """
        pending = self._pending_approvals.get(run_id)
        if not pending:
            return False
        pending.approved = False
        pending.event.set()
        return True

    def push_permission_event(self, workspace_id: str, event: dict) -> None:
        """Push a permission event to the workspace's SSE queue."""
        queue = self._permission_queues.get(workspace_id)
        if queue:
            queue.put_nowait(event)

    def get_permission_queue(self, workspace_id: str) -> asyncio.Queue | None:
        """Get the permission event queue for a workspace (for SSE streaming)."""
        return self._permission_queues.get(workspace_id)

    def get_active_run_id(self, workspace_id: str) -> str | None:
        """Get the currently active agent run ID for a workspace."""
        return self._active_runs.get(workspace_id)

    def _cleanup_workspace_state(
        self, workspace_id: str, agent_run_id: str
    ) -> None:
        """Clean up per-workspace state after execution completes."""
        self._pending_approvals.pop(agent_run_id, None)
        self._permission_pending.pop(agent_run_id, None)
        self._active_runs.pop(workspace_id, None)
        queue = self._permission_queues.pop(workspace_id, None)
        if queue:
            # Signal completion to any SSE listener
            queue.put_nowait({"type": "done"})

    async def _patch_permission_marker(
        self,
        db: aiosqlite.Connection,
        agent_run_id: str,
        permission_id: str,
        *,
        pending: bool,
        request: dict[str, Any] | None,
    ) -> None:
        """Set or clear the agent-permission marker. Never raises.

        A DB hiccup here must not strand the agent — the SSE callback
        still fires and reconcile-on-startup cleans up if everything
        falls over.
        """
        if not agent_run_id:
            return
        try:
            await update_agent_run(
                db,
                agent_run_id,
                AgentRunUpdate(
                    permission_pending=pending,
                    permission_request=request,
                ),
            )
        except Exception:  # noqa: BLE001
            verb = "persist" if pending else "clear"
            logger.exception(
                "Failed to %s permission_pending marker "
                "(agent_run=%s, permission=%s)",
                verb, agent_run_id, permission_id,
            )

    async def execute(
        self,
        workspace_id: str,
        agent_type: str,
        db: aiosqlite.Connection,
        *,
        workspace_dir: str,
        timeout: float = DEFAULT_TIMEOUT,
        on_progress: Callable[[str], None] | None = None,
        on_permission: Callable[[dict], None] | None = None,
        env_vars: dict[str, str] | None = None,
        user_note: str | None = None,
    ) -> AgentExecutionResult:
        """Execute a single agent run.

        Args:
            workspace_id: The workspace to run in.
            agent_type: One of the AgentType literals.
            db: Database connection.
            workspace_dir: Path to the workspace directory on disk.
            timeout: Maximum seconds to wait for the agent.
            on_progress: Optional callback for streaming text chunks.
            on_permission: Optional callback when a tool needs user approval.
                Called with {id, tool, patterns} dict.
            user_note: PRD-0006 Phase 2 — user refinement note. Only honored
                when ``agent_type == 'remediation_planner'``; ignored for
                other agents. Re-runs replace ``SidebarState.plan`` per the
                existing executor semantics.

        Returns:
            AgentExecutionResult with status and parsed output.

        Raises:
            AgentBusyError: If another agent is already running.
            AgentProcessError: If the workspace process can't start.
        """
        start_time = time.monotonic()

        # 1. Check no other agent is running
        await self.check_not_busy(db, workspace_id)

        # 2. Create AgentRun record
        agent_run = await create_agent_run(
            db,
            workspace_id,
            AgentRunCreate(agent_type=agent_type, status="running"),
        )

        # Set up per-workspace state for permission event streaming
        self._permission_queues[workspace_id] = asyncio.Queue()
        self._active_runs[workspace_id] = agent_run.id

        try:
            # 3. Get or start workspace OpenCode process
            try:
                client = await self._pool.get_or_start(
                    workspace_id, Path(workspace_dir), env_vars=env_vars
                )
            except (RuntimeError, TimeoutError) as exc:
                raise AgentProcessError(str(exc)) from exc

            # 4. Create fresh session
            session = await client.create_session()

            finding_data, prior_ctx = _load_workspace_data(
                workspace_dir, agent_type
            )

            # Tool agents (remediation_executor) use Jinja2 templates with
            # tool access. Other agents use the no-tools JSON-only prompt
            # for fast, reliable structured output.
            if agent_type in _TOOL_AGENT_TYPES:
                engine = AgentTemplateEngine()
                # Pass repo_url and gh_token directly into the template
                # so the agent doesn't rely on shell env var expansion.
                extra_vars: dict[str, Any] = {}
                if env_vars:
                    if env_vars.get("OPENSEC_REPO_URL"):
                        extra_vars["repo_url"] = env_vars["OPENSEC_REPO_URL"]
                    if env_vars.get("GH_TOKEN"):
                        extra_vars["gh_token"] = env_vars["GH_TOKEN"]
                if user_note and agent_type == "remediation_planner":
                    extra_vars["user_note"] = user_note
                rendered = engine.render_agent(
                    agent_type,
                    finding=finding_data,
                    enrichment=prior_ctx.get("enrichment"),
                    ownership=prior_ctx.get("ownership"),
                    exposure=prior_ctx.get("exposure"),
                    evidence=prior_ctx.get("evidence"),
                    plan=prior_ctx.get("plan"),
                    remediation=prior_ctx.get("remediation"),
                    validation=prior_ctx.get("validation"),
                    **extra_vars,
                )
                prompt = rendered.content
            else:
                prompt = build_agent_prompt(
                    agent_type,
                    finding=finding_data,
                    prior_context=prior_ctx,
                    user_note=user_note,
                )

            # Tool agents (e.g. remediation_executor) need more time for
            # git clone, push, and PR creation.
            effective_timeout = (
                max(timeout, 600.0)
                if agent_type in _TOOL_AGENT_TYPES
                else timeout
            )

            # EF-B17 — provider rate-limit retry with exponential backoff.
            # Each attempt uses a fresh OpenCode session because the previous
            # one already consumed the prompt that triggered the throttle.
            # ``session`` is reassigned so downstream code (parse-failure
            # retry below) keeps targeting the session that produced the
            # eventually-successful response.
            response_text = ""
            for attempt in range(1, RATE_LIMIT_MAX_ATTEMPTS + 1):
                try:
                    response_text = await self._send_and_collect(
                        client, session.id, prompt,
                        timeout=effective_timeout, on_progress=on_progress,
                        on_permission=on_permission,
                        agent_run_id=agent_run.id,
                        agent_type=agent_type,
                        db=db,
                    )
                    break
                except AgentRateLimitError as exc:
                    if attempt >= RATE_LIMIT_MAX_ATTEMPTS:
                        # Out of budget — let the outer handler convert to
                        # status=rate_limited with last_error populated.
                        raise
                    delay = _rate_limit_backoff_delay(attempt)
                    logger.warning(
                        "Agent %s rate-limited on attempt %d/%d; "
                        "sleeping %.1fs before retry: %s",
                        agent_type, attempt, RATE_LIMIT_MAX_ATTEMPTS,
                        delay, exc,
                    )
                    await asyncio.sleep(delay)
                    # Best-effort tear-down of the throttled session before
                    # the next attempt. Without this we'd leak up to
                    # RATE_LIMIT_MAX_ATTEMPTS-1 sessions per failed run in
                    # the per-workspace OpenCode process.
                    with contextlib.suppress(httpx.HTTPError, AttributeError):
                        await client.delete_session(session.id)
                    # Fresh session for the next try.
                    session = await client.create_session()

            # 7. Parse response
            parse_result = parse_agent_response(
                response_text, agent_type=agent_type
            )

            # 7b. Retry once if parse failed — send a corrective follow-up
            # on the same session so the LLM sees its own bad output.
            if not parse_result.success and response_text.strip():
                logger.info(
                    "Agent %s parse failed (error=%s), retrying with corrective prompt",
                    agent_type,
                    parse_result.error,
                )
                retry_text = await self._send_and_collect(
                    client, session.id, _RETRY_PROMPT,
                    timeout=effective_timeout, on_progress=on_progress,
                    on_permission=on_permission,
                    agent_run_id=agent_run.id,
                    agent_type=agent_type,
                    send_delay=0.0,
                    db=db,
                )
                retry_result = parse_agent_response(
                    retry_text, agent_type=agent_type
                )
                if retry_result.success:
                    parse_result = retry_result

            # 7b-ref. Reference verification (Q01-B08). The finding_enricher
            # emits ``references`` as free-text and weaker models fabricate
            # specific identifiers — GHSA IDs that 404, commit URLs with
            # garbled SHAs — which then ship into the evidence sidebar with
            # the same authority as a real NVD link. Drop the ones we can
            # structurally disprove or that the host 404s. Best-effort: a
            # verifier failure must never fail the run.
            if (
                parse_result.success
                and agent_type == "finding_enricher"
                and parse_result.structured_output
            ):
                try:
                    ref_check = await clean_references(
                        parse_result.structured_output.get("references")
                    )
                    if ref_check.dropped:
                        logger.warning(
                            "finding_enricher references dropped "
                            "(workspace=%s run=%s): %s",
                            workspace_id,
                            agent_run.id,
                            ref_check.dropped,
                        )
                        parse_result.structured_output["references"] = (
                            ref_check.kept
                        )
                except (httpx.HTTPError, ValueError, TypeError):
                    # Networking, bad URLs, or upstream shape surprises —
                    # log but never fail the run on reference verification.
                    logger.warning(
                        "Reference verification raised for workspace %s",
                        workspace_id,
                        exc_info=True,
                    )

            # 7b-ev. Evidence guards (Q01-B11, B13). The evidence_collector
            # classifies fix safety and reports the current version as
            # free-text — both drift under model/concurrency variance. For a
            # dependency finding OpenSec already knows the authoritative
            # versions from the scanner, so reconcile the agent's output
            # against them (a major-version jump is never a ``safe_bump``;
            # ``current_version`` is backfilled). Best-effort.
            if (
                parse_result.success
                and agent_type == "evidence_collector"
                and parse_result.structured_output
            ):
                try:
                    corrections = guard_evidence_output(
                        parse_result.structured_output, finding_data
                    )
                    if corrections:
                        logger.info(
                            "evidence_collector output corrected "
                            "(workspace=%s run=%s): %s",
                            workspace_id,
                            agent_run.id,
                            corrections,
                        )
                except (ValueError, TypeError, KeyError):
                    # Evidence guard is pure data manipulation; the only
                    # realistic raise surface is malformed structured
                    # output. Log but never fail the run on it.
                    logger.warning(
                        "Evidence guard raised for workspace %s",
                        workspace_id,
                        exc_info=True,
                    )

            # 7c. PR URL verification (B16). The remediation_executor is the
            # only agent that claims to have opened a PR. If the emitted
            # ``pr_url`` can't be fetched from GitHub we flip the parse
            # result to a failure BEFORE anything is persisted — otherwise
            # we'd advance the finding to ``remediated`` with a hallucinated
            # URL and the user would later click a dead link.
            verification_error: str | None = None
            if (
                parse_result.success
                and agent_type == "remediation_executor"
                and (parse_result.structured_output or {}).get("status")
                == "pr_created"
            ):
                gh_token = (env_vars or {}).get("GH_TOKEN") or (
                    env_vars or {}
                ).get("GITHUB_TOKEN")
                claimed = (parse_result.structured_output or {}).get("pr_url")
                verification = await verify_pr_url(claimed, token=gh_token)
                if not verification.ok:
                    verification_error = (
                        "PR verification failed: "
                        f"{verification.reason}. Agent claimed "
                        f"pr_url={claimed!r}."
                    )
                    logger.warning(
                        "remediation_executor emitted unverifiable pr_url "
                        "(workspace=%s run=%s): %s",
                        workspace_id,
                        agent_run.id,
                        verification_error,
                    )
                    # Strip the false claim so downstream persistence doesn't
                    # store a dead link in the sidebar.
                    cleaned = dict(parse_result.structured_output or {})
                    cleaned["status"] = "failed"
                    cleaned["pr_url"] = None
                    cleaned["error_details"] = verification_error
                    parse_result = ParseResult(
                        success=False,
                        raw_text=parse_result.raw_text,
                        error=verification_error,
                        structured_output=cleaned,
                        summary=parse_result.summary,
                        confidence=parse_result.confidence,
                        suggested_next_action=parse_result.suggested_next_action,
                    )

            # 8. Persist results
            sidebar_updated = False
            context_version = None

            if parse_result.success and parse_result.structured_output:
                # 8a. Update context files + re-render templates
                context_version = await self._context_builder.update_context(
                    db,
                    workspace_id,
                    agent_type,
                    parse_result.structured_output,
                    summary=parse_result.summary,
                )

                # 8b. Update sidebar state (read-merge-write)
                await map_and_upsert(
                    db,
                    workspace_id,
                    agent_type,
                    parse_result.structured_output,
                )
                sidebar_updated = True

                # 8c. Auto-advance finding status (forward-only)
                await _advance_finding_status(
                    db,
                    workspace_id,
                    agent_type,
                    parse_result.structured_output,
                )

            # 9. Update AgentRun in DB
            duration = time.monotonic() - start_time
            # An agent run is only "completed" when parse succeeded AND
            # the PR (if any) verified. Without parse_result.success the
            # sidebar/context were never written (block 8a-c was skipped),
            # so rendering the row green would mis-signal a silent failure
            # — caught by the architect review of EF-B17 (more rate-limit
            # retries → more parse-failure-after-retry paths).
            parse_failed = not parse_result.success
            run_status: Literal["completed", "failed"] = (
                "failed"
                if verification_error or parse_failed
                else "completed"
            )
            failure_message = (
                verification_error
                or (parse_result.error if parse_failed else None)
            )
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status=run_status,
                    summary_markdown=(
                        failure_message
                        if failure_message
                        else parse_result.summary
                    ),
                    confidence=parse_result.confidence,
                    structured_output=parse_result.structured_output,
                    next_action_hint=parse_result.suggested_next_action,
                    last_error=failure_message,
                ),
            )

            self._cleanup_workspace_state(workspace_id, agent_run.id)
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status=run_status,
                parse_result=parse_result,
                sidebar_updated=sidebar_updated,
                context_version=context_version,
                duration_seconds=duration,
                error=verification_error,
            )

        except AgentTimeoutError:
            self._cleanup_workspace_state(workspace_id, agent_run.id)
            duration = time.monotonic() - start_time
            timeout_error = f"Agent timed out after {timeout:.0f}s"
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="failed",
                    summary_markdown="Agent timed out. Partial response may be available.",
                    last_error=timeout_error,
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="failed",
                parse_result=ParseResult(
                    success=False, raw_text="", error="timeout"
                ),
                error=timeout_error,
                duration_seconds=duration,
            )

        # EF-B17 — must precede ``AgentProcessError`` because
        # ``AgentRateLimitError`` is a subclass of it.
        except AgentRateLimitError as exc:
            self._cleanup_workspace_state(workspace_id, agent_run.id)
            duration = time.monotonic() - start_time
            next_delay = _rate_limit_backoff_delay(RATE_LIMIT_MAX_ATTEMPTS)
            last_error = (
                f"Provider rate limit reached after "
                f"{RATE_LIMIT_MAX_ATTEMPTS} attempts; retry in "
                f"~{next_delay:.0f}s. Upstream: {exc}"
            )
            logger.warning(
                "Agent %s terminated rate_limited after %d attempts: %s",
                agent_type, RATE_LIMIT_MAX_ATTEMPTS, exc,
            )
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="rate_limited",
                    summary_markdown=_humanize_process_error(str(exc)),
                    last_error=last_error,
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="rate_limited",
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=last_error,
                duration_seconds=duration,
            )

        except AgentProcessError as exc:
            self._cleanup_workspace_state(workspace_id, agent_run.id)
            duration = time.monotonic() - start_time
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="failed",
                    summary_markdown=_humanize_process_error(str(exc)),
                    last_error=str(exc),
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="failed",
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=str(exc),
                duration_seconds=duration,
            )

        except Exception as exc:
            self._cleanup_workspace_state(workspace_id, agent_run.id)
            duration = time.monotonic() - start_time
            logger.exception("Unexpected error during agent execution")
            await update_agent_run(
                db,
                agent_run.id,
                AgentRunUpdate(
                    status="failed",
                    summary_markdown=f"Unexpected error: {exc}",
                    last_error=str(exc),
                ),
            )
            return AgentExecutionResult(
                agent_run_id=agent_run.id,
                agent_type=agent_type,
                status="failed",
                parse_result=ParseResult(
                    success=False, raw_text="", error=str(exc)
                ),
                error=str(exc),
                duration_seconds=duration,
            )

    async def _send_and_collect(
        self,
        client: Any,
        session_id: str,
        prompt: str,
        *,
        timeout: float,
        on_progress: Callable[[str], None] | None = None,
        on_permission: Callable[[dict], None] | None = None,
        agent_run_id: str = "",
        agent_type: str = "",
        send_delay: float = 0.5,
        db: aiosqlite.Connection,
    ) -> str:
        """Send a prompt and collect the streamed response.

        The send_delay gives the SSE stream time to connect before the
        message is sent. Set to 0 for follow-up messages on an already-
        connected session.
        """

        async def _send() -> None:
            if send_delay > 0:
                await asyncio.sleep(send_delay)
            with contextlib.suppress(httpx.ReadTimeout):
                await client.send_message(session_id, prompt)

        send_task = asyncio.create_task(_send())
        try:
            return await self._collect_response(
                client, session_id,
                timeout=timeout,
                on_progress=on_progress,
                on_permission=on_permission,
                agent_run_id=agent_run_id,
                agent_type=agent_type,
                db=db,
            )
        finally:
            if not send_task.done():
                send_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await send_task

    async def check_not_busy(
        self, db: aiosqlite.Connection, workspace_id: str
    ) -> None:
        """Raise AgentBusyError if another agent is already running."""
        runs = await list_agent_runs(db, workspace_id, limit=10)
        for run in runs:
            if run.status == "running":
                raise AgentBusyError(
                    f"Agent '{run.agent_type}' is already running "
                    f"in workspace {workspace_id}"
                )

    async def _collect_response(
        self,
        client: Any,
        session_id: str,
        *,
        timeout: float,
        on_progress: Callable[[str], None] | None = None,
        on_permission: Callable[[dict], None] | None = None,
        agent_run_id: str = "",
        agent_type: str = "",
        stall_timeout: float = 60.0,
        db: aiosqlite.Connection,
    ) -> str:
        """Collect the full response from OpenCode via SSE stream.

        Accumulates text events until ``done`` or until no new events
        arrive for ``stall_timeout`` seconds (stall detection — OpenCode
        may not emit ``session.idle`` if the agent uses tools).

        Handles permission.asked events: auto-approves safe tools,
        waits for user approval on risky ones.

        Raises AgentTimeoutError if the overall timeout is exceeded.
        """
        collected_text = ""
        last_event_time = time.monotonic()
        permission_wait_total = 0.0  # Total seconds spent waiting for user approval

        # Tool agents need longer stall timeout for git/build operations
        if agent_type in _TOOL_AGENT_TYPES:
            stall_timeout = max(stall_timeout, 180.0)

        # A genuinely hung agent emits no events of any kind. Catch that fast
        # (Q01-B10) rather than dead-waiting the full overall ceiling — but
        # use a wider window than the with-content stall so a slow first
        # token under heavy concurrency (Q01-B12) is not mistaken for a hang.
        no_output_stall = max(90.0, stall_timeout)

        async def _handle_permission(event: dict) -> None:
            """Handle a permission request based on tool tier."""
            tool = event.get("tool", "unknown")
            permission_id = event.get("id", "")
            patterns = event.get("patterns", [])
            tier = TOOL_TIERS.get(tool, "user")

            # Tool agents (e.g. remediation_executor) no longer blanket-
            # approve bash/edit/external_directory. Each request is
            # classified by command/path: routine git/gh/build commands
            # auto-approve, but destructive commands (rm, git reset --hard,
            # …), pipe-to-shell, and any attempt to reach outside the
            # workspace escalate to the user. Denylist-based — a
            # defense-in-depth layer on top of GIT_CEILING_DIRECTORIES and
            # the agent prompt, not a substitute for process sandboxing.
            if agent_type in _TOOL_AGENT_TYPES:
                tier = _classify_tool_request(tool, patterns)

            if tier == "auto":
                logger.info(
                    "Auto-approving %s tool (permission %s)",
                    tool, permission_id,
                )
                await client.grant_permission(
                    permission_id, session_id=session_id,
                )
                return

            if tier == "deny":
                # Catastrophic command — reject immediately. Denying (vs.
                # escalating) gives the agent fast feedback to recover or
                # report, instead of stalling on an approval prompt the
                # frontend doesn't surface yet.
                logger.warning(
                    "Auto-denying %s tool (permission %s) — command "
                    "classified catastrophic: %s",
                    tool, permission_id, event.get("patterns", []),
                )
                await client.deny_permission(
                    permission_id, session_id=session_id,
                )
                return

            # User-tier: store pending approval and wait
            logger.info(
                "Permission requested for %s tool (permission %s), "
                "waiting for user approval",
                tool, permission_id,
            )
            patterns_list = event.get("patterns", [])
            pending = _PendingApproval(
                permission_id=permission_id,
                tool=tool,
                patterns=patterns_list,
                event=asyncio.Event(),
            )
            self._pending_approvals[agent_run_id] = pending

            # Persist the marker so issue_derivation.derive() can route the
            # finding to Review / awaiting_permission. Without this, the
            # only signal is the in-memory dict + SSE event — which means
            # a page reload, or a user not looking at this workspace,
            # would never see the prompt.
            await self._patch_permission_marker(
                db,
                agent_run_id,
                permission_id,
                pending=True,
                request={
                    "id": permission_id,
                    "tool": tool,
                    "patterns": patterns_list,
                },
            )

            if on_permission:
                on_permission({
                    "id": permission_id,
                    "tool": tool,
                    "patterns": patterns_list,
                    "run_id": agent_run_id,
                })

            # Pause stall detection while waiting for user decision
            self._permission_pending[agent_run_id] = True
            wait_start = time.monotonic()
            await pending.event.wait()
            wait_elapsed = time.monotonic() - wait_start
            self._permission_pending.pop(agent_run_id, None)
            nonlocal permission_wait_total
            permission_wait_total += wait_elapsed
            # Extend the stall timer to exclude user decision time
            nonlocal last_event_time
            last_event_time = time.monotonic()

            # Clear the persisted marker. Covers approve, deny, AND the
            # disconnect-auto-deny path (the SSE stream endpoint calls
            # deny_tool on client disconnect, which sets pending.event).
            await self._patch_permission_marker(
                db, agent_run_id, permission_id, pending=False, request=None,
            )

            if pending.approved:
                await client.grant_permission(
                    permission_id, session_id=session_id,
                )
            else:
                await client.deny_permission(
                    permission_id, session_id=session_id,
                )

            self._pending_approvals.pop(agent_run_id, None)

        async def _stream() -> str:
            nonlocal collected_text, last_event_time
            async for event in client.stream_events(session_id):
                last_event_time = time.monotonic()
                if event["type"] == "text":
                    collected_text = event["content"]
                    if on_progress:
                        on_progress(event["content"])
                elif event["type"] == "error":
                    message = event.get("message", "unknown")
                    wrapped = f"OpenCode error: {message}"
                    # EF-B17 — classify provider rate-limit early so the
                    # executor retry loop can apply exponential backoff
                    # instead of treating it as a fatal process error.
                    if _looks_like_rate_limit(message):
                        raise AgentRateLimitError(wrapped)
                    raise AgentProcessError(wrapped)
                elif event["type"] == "done":
                    return collected_text
                elif event["type"] == "permission_request":
                    await _handle_permission(event)
                # "activity" events (tool calls, etc.) also reset the timer
                # via last_event_time update above.
            return collected_text

        async def _stream_with_stall_detection() -> str:
            """Wrap stream with stall detection.

            The overall timeout excludes time spent waiting for user
            permission decisions (tracked via permission_wait_total).
            """
            stream_start = time.monotonic()
            stream_task = asyncio.create_task(_stream())
            try:
                while not stream_task.done():
                    await asyncio.sleep(2.0)
                    # Skip stall detection while waiting for user permission
                    if self._permission_pending.get(agent_run_id):
                        continue
                    idle = time.monotonic() - last_event_time
                    if idle > stall_timeout and collected_text:
                        # Stream stalled with content — treat as complete
                        stream_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await stream_task
                        return collected_text
                    if idle > no_output_stall and not collected_text:
                        # No events of any kind for a long stretch and
                        # nothing collected — the agent is hung. Fail fast
                        # (Q01-B10); the run-all loop re-runs it next pass.
                        stream_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await stream_task
                        raise AgentTimeoutError(
                            f"Agent produced no output for "
                            f"{no_output_stall:.0f}s — treating as hung."
                        )
                    # Check effective timeout (wall clock minus permission wait)
                    effective_elapsed = (
                        time.monotonic() - stream_start - permission_wait_total
                    )
                    if effective_elapsed > timeout:
                        stream_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await stream_task
                        raise AgentTimeoutError(
                            f"Agent did not complete within {timeout:.0f}s "
                            f"(excludes {permission_wait_total:.0f}s user approval time)."
                        )
                return stream_task.result()
            except asyncio.CancelledError:
                stream_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_task
                raise

        max_wall_clock = timeout + PERMISSION_WAIT_BUFFER
        try:
            return await asyncio.wait_for(
                _stream_with_stall_detection(), timeout=max_wall_clock
            )
        except TimeoutError as exc:
            effective_timeout = timeout + permission_wait_total
            raise AgentTimeoutError(
                f"Agent did not complete within {effective_timeout:.0f}s "
                f"(includes {permission_wait_total:.0f}s user approval time). "
                f"Collected {len(collected_text)} chars before timeout."
            ) from exc
