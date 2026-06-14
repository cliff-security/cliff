"""`cliffsec` — agent-friendly CLI for Cliff.

Six commands, JSON-by-default, exit codes that encode workflow state.
See :mod:`cliff_cli.output` for the exit-code contract.

Workflow (driven by the `/secure-repo` skill):

    cliffsec status                  # daemon up?
    cliffsec scan <repo_url>         # run posture-assessment, ingest findings
    cliffsec issues --severity high  # list what to fix
    cliffsec fix <id>                # plan, exit 2 → human approves
    cliffsec approve <id>            # executor + validator, returns PR
    cliffsec close <id>              # mark closed after PR merges
"""

from __future__ import annotations

from typing import Any

import click

from cliff_cli import __version__
from cliff_cli.client import (
    Client,
    DaemonDownError,
    HTTPError,
    VersionMismatchError,
    poll,
)
from cliff_cli.daemon import (
    config_group,
    doctor_cmd,
    logs_cmd,
    restart_cmd,
    start_cmd,
    stop_cmd,
    uninstall_cmd,
)
from cliff_cli.output import (
    EXIT_AWAITING_HUMAN,
    EXIT_DAEMON_DOWN,
    EXIT_ERROR,
    EXIT_NO_FINDINGS,
    EXIT_OK,
    EXIT_VERSION_MISMATCH,
    emit,
    emit_error,
)
from cliff_cli.updater import update_cmd

# ---------------------------------------------------------------------------
# Shared decorators
# ---------------------------------------------------------------------------


def _with_client(fn):
    """Open a Client and translate transport-level errors into emit_error.

    Commands that need the version handshake call ``client.version_handshake()``
    explicitly; ``status`` does the handshake itself so it can report the
    mismatch as data rather than as an error.
    """

    def wrapper(*args, **kwargs):
        try:
            with Client() as c:
                fn(c, *args, **kwargs)
        except DaemonDownError as exc:
            emit_error(
                "Cliff daemon is not reachable.",
                code="daemon_down",
                hint="Run the Cliff installer or `docker compose up -d` from your install dir.",
                exit_code=EXIT_DAEMON_DOWN,
                extra={"detail": str(exc)},
            )
        except VersionMismatchError as exc:
            emit_error(
                str(exc),
                code="version_mismatch",
                hint="Re-run the install one-liner from the README to upgrade the CLI.",
                exit_code=EXIT_VERSION_MISMATCH,
                extra={"min_cli": exc.min_cli, "cli_version": exc.our_version},
            )
        except HTTPError as exc:
            emit_error(
                str(exc.detail) if exc.detail else f"HTTP {exc.status}",
                code=f"http_{exc.status}",
                exit_code=EXIT_ERROR,
            )
        except TimeoutError as exc:
            emit_error(
                str(exc),
                code="timeout",
                hint=(
                    "Pipeline didn't produce a result within the polling window. "
                    "Re-run, or check the daemon logs."
                ),
                exit_code=EXIT_ERROR,
            )

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# Click app
# ---------------------------------------------------------------------------


@click.group(
    help=(
        "Agent-friendly CLI for Cliff. "
        "JSON output by default; exit codes encode workflow state."
    ),
)
@click.version_option(__version__, prog_name="cliffsec")
def main() -> None:
    pass


# Register the daemon-management commands. These run on the local install
# and don't need a running daemon (`start`, `stop`, `restart`, `logs`,
# `doctor`, `config`, `uninstall`).
main.add_command(start_cmd)
main.add_command(stop_cmd)
main.add_command(restart_cmd)
main.add_command(logs_cmd)
main.add_command(doctor_cmd)
main.add_command(config_group)
main.add_command(uninstall_cmd)
main.add_command(update_cmd)


# ---- 1. status ------------------------------------------------------------


@main.command()
@_with_client
def status(client: Client) -> None:
    """Health + version handshake. Exits 0 if ready, 3 if daemon down, 4 on version mismatch."""
    health = client.get("/health")
    try:
        version = client.version_handshake()
    except VersionMismatchError:
        # Re-raise so the wrapper handles it as a structured error.
        raise

    # ADR-0037 / ADR-0047: report the canonical active model. With the
    # substrate in-process there is no engine probe and no drift signal —
    # ``/api/integrations/ai/status`` is the canonical model (DB-backed),
    # with ``/health.model`` as the fallback when that endpoint isn't yet
    # available (no vault).
    canonical_model: str | None = None
    try:
        ai_status = client.get("/api/integrations/ai/status")
        canonical_model = ai_status.get("model")
    except HTTPError:
        pass
    model = canonical_model or health.get("model") or ""

    blockers: list[str] = []
    if not model:
        blockers.append("no_llm_model_configured")
    # A model string alone is not enough — the agent runtime also needs a
    # provider credential that actually resolves. ``ai_provider_ready`` is
    # False when no credential resolved (e.g. a connected-but-broken BYOK
    # key), so guard against that false-positive.
    if not health.get("ai_provider_ready", False):
        blockers.append("no_ai_provider_credential")

    next_action: str | None = "scan <repo_url>" if not blockers else None

    emit(
        {
            "ready": not blockers,
            "cliff": version["cliff"],
            "opencode": version["opencode"],
            "schema_version": version["schema_version"],
            "min_cli": version["min_cli"],
            "cli_version": __version__,
            "model": model,
            "blockers": blockers,
            "next": next_action,
        }
    )


# ---- 2. scan --------------------------------------------------------------


@main.command()
@click.argument("repo_url")
@click.option("--timeout", default=900.0, help="Max seconds to wait for the assessment to finish.")
@_with_client
def scan(client: Client, repo_url: str, timeout: float) -> None:
    """Run a posture-assessment scan on a repo URL. Polls until complete.

    Exits 0 on success, 5 if the scan completed with zero findings.
    """
    client.version_handshake()

    started = client.post("/api/assessment/run", json={"repo_url": repo_url})
    assessment_id = started["assessment_id"]

    final = poll(
        client,
        f"/api/assessment/status/{assessment_id}",
        is_done=lambda p: p.get("status") == "complete",
        is_failed=lambda p: p.get("status") == "failed",
        interval=2.0,
        timeout=timeout,
    )

    findings = client.get(
        "/api/findings",
        params={"scope": "current", "limit": 1000},
    )
    by_severity: dict[str, int] = {}
    for f in findings:
        sev = (f.get("normalized_priority") or "unknown").lower()
        by_severity[sev] = by_severity.get(sev, 0) + 1

    total = len(findings)
    payload: dict[str, Any] = {
        "scan_id": assessment_id,
        "finding_count": total,
        "by_severity": by_severity,
        "progress_pct": final.get("progress_pct", 100),
        "next": "issues --severity critical,high" if total else None,
    }
    emit(payload, exit_code=EXIT_OK if total else EXIT_NO_FINDINGS)


# ---- 3. issues ------------------------------------------------------------


@main.command()
@click.option(
    "--severity",
    default="",
    help="Comma-separated list (critical,high,medium,low,info). Empty = all.",
)
@click.option("--status", "status_filter", default="new", help="Finding status filter.")
@click.option("--limit", default=20, type=int, help="Max issues to return (default 20).")
@_with_client
def issues(client: Client, severity: str, status_filter: str, limit: int) -> None:
    """List findings, filtered. Default scope is the latest assessment."""
    client.version_handshake()

    params: dict[str, Any] = {"scope": "current", "limit": 200}
    if status_filter and status_filter != "any":
        params["status"] = status_filter

    rows = client.get("/api/findings", params=params)
    wanted = {s.strip().lower() for s in severity.split(",") if s.strip()}

    out: list[dict[str, Any]] = []
    for f in rows:
        sev = (f.get("normalized_priority") or "unknown").lower()
        if wanted and sev not in wanted:
            continue
        out.append(
            {
                "id": f["id"],
                "severity": sev,
                "title": f["title"],
                "type": f.get("type", "dependency"),
                "status": f.get("status", "new"),
                "workspace_id": (f.get("derived") or {}).get("workspace_id"),
            }
        )
        if len(out) >= limit:
            break

    emit(
        {
            "issues": out,
            "total": len(out),
            "truncated": len(out) >= limit,
            "next": f"fix {out[0]['id']}" if out else None,
        }
    )


# ---- 4. fix ---------------------------------------------------------------


def _triage_reason(triage: dict[str, Any]) -> str | None:
    """One-line reasoning behind a triage verdict (mirrors the chat-card line).

    Prefers the exploitability reason, then the reachability summary, then the
    first proof-check detail — whichever the synthesizer/Deep dive populated.
    """
    exploit = triage.get("exploitability") or {}
    if exploit.get("reason"):
        return exploit["reason"]
    reach = triage.get("reachability") or {}
    if reach.get("summary"):
        return reach["summary"]
    checks = triage.get("checks") or []
    if checks and isinstance(checks[0], dict) and checks[0].get("detail"):
        return checks[0]["detail"]
    return None


@main.command()
@click.argument("issue_id")
@click.option("--timeout", default=900.0, help="Max seconds to wait for triage + planner.")
@_with_client
def fix(client: Client, issue_id: str, timeout: float) -> None:
    """Triage a finding (resolve reachability), then plan only if it's real.

    Runs the agentic triage Deep dive to decide whether the flagged code is
    actually reachable in your repo, then gates on the verdict (ADR-0051 §6 —
    the Plan gate; the planner never fires until reachability is established):

    \b
      * real           -> builds a remediation plan, exits 2 (awaiting approval).
      * unexploitable /
        false_positive -> cleared as noise with the reasoning on record, exits 0.
      * needs_review   -> flagged for your judgment, exits 2.

    After a `real` plan is ready, run ``cliffsec approve <workspace_id>``.
    """
    client.version_handshake()

    # 1. Triage first. The endpoint creates/reuses a workspace WITHOUT advancing
    #    the finding's status (it stays ``new`` until a `real` verdict is
    #    confirmed — ADR-0051 §6) and runs the agentic triage in the background.
    started = client.post(f"/api/findings/{issue_id}/triage")
    workspace_id = started["workspace_id"]

    # 2. Poll for the triage verdict. Tolerate 404: the sidebar row is created
    #    lazily by the first triage write.
    sidebar = poll(
        client,
        f"/api/workspaces/{workspace_id}/sidebar",
        is_done=lambda s: bool(s.get("triage")),
        interval=2.0,
        timeout=timeout,
        tolerate_status=(404,),
    )
    triage = sidebar.get("triage") or {}
    verdict = (triage.get("verdict") or "").lower()
    reason = _triage_reason(triage)
    confidence = triage.get("confidence")

    # 3a. Cleared as noise — the dismiss-with-reasoning verdict IS the output.
    #     No remediation plan is produced (the report-tour bright line).
    if verdict in ("unexploitable", "false_positive"):
        emit(
            {
                "workspace_id": workspace_id,
                "finding_id": issue_id,
                "verdict": verdict,
                "cleared": True,
                "reason": reason,
                "confidence": confidence,
                "awaiting": None,
                "next": f"close {workspace_id}",
            }
        )
        return

    # 3b. Low-signal — flag for human judgment. Never an alarmist plan.
    if verdict != "real":
        emit(
            {
                "workspace_id": workspace_id,
                "finding_id": issue_id,
                "verdict": verdict or "needs_review",
                "cleared": False,
                "reason": reason,
                "confidence": confidence,
                "awaiting": "human_review",
                "next": None,
            },
            exit_code=EXIT_AWAITING_HUMAN,
        )
        return

    # 4. Real — build the remediation plan, stop at the approval gate. The
    #    pipeline runs its agents in-process via Pydantic AI (ADR-0047); the
    #    triaged workspace already has enricher + exposure, so run-all advances
    #    straight to evidence + planner.
    client.post(f"/api/workspaces/{workspace_id}/pipeline/run-all")

    # Poll until a plan exists (awaiting approval) or a validation result is
    # already present (auto-resolved short-circuit).
    def _done(s: dict[str, Any]) -> bool:
        plan = s.get("plan") or {}
        validation = s.get("validation") or {}
        return bool(plan.get("plan_steps") or validation)

    sidebar = poll(
        client,
        f"/api/workspaces/{workspace_id}/sidebar",
        is_done=_done,
        interval=2.0,
        timeout=timeout,
        tolerate_status=(404,),
    )

    plan = sidebar.get("plan") or {}
    dod = sidebar.get("definition_of_done") or {}
    validation = sidebar.get("validation") or {}

    if validation and not plan.get("plan_steps"):
        # Pipeline ran end-to-end without a plan gate (e.g. the planner
        # decided no work was needed). Treat as auto-resolved.
        emit(
            {
                "workspace_id": workspace_id,
                "verdict": "real",
                "plan": plan,
                "validation": validation,
                "awaiting": None,
                "next": f"close {workspace_id}",
            }
        )
        return

    emit(
        {
            "workspace_id": workspace_id,
            "finding_id": issue_id,
            "verdict": "real",
            "plan": {
                "steps": plan.get("plan_steps") or [],
                "interim_mitigation": plan.get("interim_mitigation"),
                "definition_of_done": dod.get("items") or [],
                "approved": bool(plan.get("approved")),
            },
            "awaiting": "plan_approval",
            "next": f"approve {workspace_id}",
        },
        exit_code=EXIT_AWAITING_HUMAN,
    )


# ---- 5. approve -----------------------------------------------------------


@main.command()
@click.argument("workspace_id")
@click.option("--timeout", default=1800.0, help="Max seconds to wait for executor + validator.")
@_with_client
def approve(client: Client, workspace_id: str, timeout: float) -> None:
    """Approve the plan for a workspace and resume the pipeline through executor + validator.

    Returns ``{pr_url, branch, validation}``. Exits 2 if validation does not
    pass — the user should inspect before closing.
    """
    client.version_handshake()

    client.post(f"/api/workspaces/{workspace_id}/plan/approve")
    # Resume the pipeline so the executor + validator actually run.
    client.post(f"/api/workspaces/{workspace_id}/pipeline/run-all")

    def _done(s: dict[str, Any]) -> bool:
        return bool(s.get("validation"))

    sidebar = poll(
        client,
        f"/api/workspaces/{workspace_id}/sidebar",
        is_done=_done,
        interval=3.0,
        timeout=timeout,
        tolerate_status=(404,),
    )

    validation = sidebar.get("validation") or {}
    pull_request = sidebar.get("pull_request") or {}
    verdict = (validation.get("verdict") or validation.get("status") or "").lower()

    pr_url = pull_request.get("url") or pull_request.get("pr_url")
    branch = pull_request.get("branch_name") or pull_request.get("branch")

    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "pr_url": pr_url,
        "branch": branch,
        "validation": {
            "verdict": verdict or "unknown",
            "reason": validation.get("reason") or validation.get("message"),
        },
    }

    if verdict in ("ok", "pass", "passed", "validated"):
        payload["next"] = f"close {workspace_id}"
        emit(payload)
    else:
        payload["next"] = None
        emit(payload, exit_code=EXIT_AWAITING_HUMAN)


# ---- 6. close -------------------------------------------------------------


@main.command()
@click.argument("workspace_id")
@_with_client
def close(client: Client, workspace_id: str) -> None:
    """Mark a workspace closed. Auto-resolves the linked finding."""
    client.version_handshake()

    ws = client.patch(
        f"/api/workspaces/{workspace_id}",
        json={"state": "closed"},
    )
    emit(
        {
            "workspace_id": workspace_id,
            "finding_id": ws.get("finding_id"),
            "state": ws.get("state"),
            "closed": ws.get("state") == "closed",
            "next": None,
        }
    )


# ---- 7. model -------------------------------------------------------------


@main.group()
def model() -> None:
    """Get, set, or list the LLM model Cliff uses to drive agents."""


@model.command("get")
@_with_client
def model_get(client: Client) -> None:
    """Show the currently configured model."""
    client.version_handshake()
    info = client.get("/api/settings/model")
    emit({**info, "next": None})


@model.command("set")
@click.argument("model_full_id")
@_with_client
def model_set(client: Client, model_full_id: str) -> None:
    """Set the active model. Pass a slash-joined ID (e.g. ``openai/gpt-5-nano``)."""
    client.version_handshake()
    info = client.put(
        "/api/settings/model",
        json={"model_full_id": model_full_id},
    )
    emit({**info, "next": None})


@model.command("list")
@click.option(
    "--provider",
    default="openai",
    help="Provider ID to list models for (default: openai).",
)
@_with_client
def model_list(client: Client, provider: str) -> None:
    """List available models for a provider as ``[{id, name}]``.

    The full provider catalog is large; this command projects it locally
    so the agent driving the CLI receives only the slim id+name slice.
    """
    client.version_handshake()
    catalog = client.get("/api/settings/providers")
    match = next((p for p in catalog if p.get("id") == provider), None)
    if match is None:
        emit_error(
            f"Provider not found: {provider}",
            code="provider_not_found",
            hint="Run `cliffsec model list --provider <id>` with a valid provider ID.",
            exit_code=EXIT_ERROR,
        )
        return
    models = [
        {"id": m_id, "name": (m or {}).get("name", m_id)}
        for m_id, m in (match.get("models") or {}).items()
    ]
    emit({"provider": provider, "models": models, "next": None})


# ---- selftest -------------------------------------------------------------


@main.command()
@click.option(
    "--repo-url",
    default="https://github.com/cliff-security/cliff",
    help="Repo URL to scan as part of the selftest.",
)
def selftest(repo_url: str) -> None:
    """End-to-end smoke: scan, list issues, fix the first one, stop at the plan gate.

    Does NOT auto-approve — the gate is the whole point. The skill (and
    humans) take it from there.
    """
    # Implemented as a wrapper around the regular commands so it exercises
    # exactly the same code paths the agent will hit. Each step prints its
    # own JSON envelope to stdout; selftest just chains them.
    import subprocess
    import sys

    def _run(args: list[str]) -> dict[str, Any]:
        proc = subprocess.run([sys.argv[0], *args], capture_output=True, text=True, check=False)
        sys.stdout.write(proc.stdout)
        if proc.returncode not in (0, 2, 5):
            sys.stderr.write(proc.stderr)
            raise SystemExit(proc.returncode)
        import json as _json

        try:
            return _json.loads(proc.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            return {}

    _run(["status"])
    scan_payload = _run(["scan", repo_url])
    if not scan_payload.get("finding_count"):
        return
    issues_payload = _run(["issues", "--severity", "critical,high", "--limit", "1"])
    rows = issues_payload.get("issues") or []
    if not rows:
        return
    _run(["fix", rows[0]["id"]])


if __name__ == "__main__":
    main()
