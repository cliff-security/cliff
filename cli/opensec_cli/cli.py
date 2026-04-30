"""`opensec` — agent-friendly CLI for OpenSec.

Six commands, JSON-by-default, exit codes that encode workflow state.
See :mod:`opensec_cli.output` for the exit-code contract.

Workflow (driven by the `/secure-repo` skill):

    opensec status                  # daemon up?
    opensec scan <repo_url>         # run posture-assessment, ingest findings
    opensec issues --severity high  # list what to fix
    opensec fix <id>                # plan, exit 2 → human approves
    opensec approve <id>            # executor + validator, returns PR
    opensec close <id>              # mark closed after PR merges
"""

from __future__ import annotations

from typing import Any

import click

from opensec_cli import __version__
from opensec_cli.client import (
    Client,
    DaemonDownError,
    HTTPError,
    VersionMismatchError,
    poll,
)
from opensec_cli.output import (
    EXIT_AWAITING_HUMAN,
    EXIT_DAEMON_DOWN,
    EXIT_ERROR,
    EXIT_NO_FINDINGS,
    EXIT_OK,
    EXIT_VERSION_MISMATCH,
    emit,
    emit_error,
)

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
                "OpenSec daemon is not reachable.",
                code="daemon_down",
                hint="Run the OpenSec installer or `docker compose up -d` from your install dir.",
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
        "Agent-friendly CLI for OpenSec. "
        "JSON output by default; exit codes encode workflow state."
    ),
)
@click.version_option(__version__, prog_name="opensec")
def main() -> None:
    pass


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

    blockers: list[str] = []
    if health.get("opencode") != "ok":
        blockers.append("opencode_engine_unavailable")
    if not health.get("model"):
        blockers.append("no_llm_model_configured")

    emit(
        {
            "ready": not blockers,
            "opensec": version["opensec"],
            "opencode": version["opencode"],
            "schema_version": version["schema_version"],
            "min_cli": version["min_cli"],
            "cli_version": __version__,
            "model": health.get("model", ""),
            "blockers": blockers,
            "next": "scan <repo_url>" if not blockers else None,
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


@main.command()
@click.argument("issue_id")
@click.option("--timeout", default=900.0, help="Max seconds to wait for the planner.")
@_with_client
def fix(client: Client, issue_id: str, timeout: float) -> None:
    """Open a workspace, run the pipeline through the planner, stop at the plan gate.

    Exits 2 (awaiting human) when the plan is ready for review. Run
    ``opensec approve <workspace_id>`` after the user confirms.
    """
    client.version_handshake()

    finding = client.get(f"/api/findings/{issue_id}")

    existing_ws = (finding.get("derived") or {}).get("workspace_id")
    if existing_ws:
        workspace_id = existing_ws
    else:
        ws = client.post(
            "/api/workspaces",
            json={"finding_id": issue_id, "current_focus": "remediation"},
        )
        workspace_id = ws["id"]

    # Make sure a session exists for the workspace before running the
    # pipeline. The session endpoint is idempotent enough for our purposes.
    import contextlib

    with contextlib.suppress(HTTPError):
        client.post(f"/api/workspaces/{workspace_id}/sessions", json={})

    client.post(f"/api/workspaces/{workspace_id}/pipeline/run-all")

    # Poll the sidebar until either:
    #   * a plan exists (awaiting approval),
    #   * or a validation result already exists (auto-resolved short-circuit).
    # Tolerate 404: the sidebar row is created lazily by the first agent
    # write, so a 404 right after run-all is normal.
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

    if validation:
        # Pipeline ran end-to-end without a plan gate (e.g. the planner
        # decided no work was needed). Treat as auto-resolved.
        emit(
            {
                "workspace_id": workspace_id,
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
    """Get, set, or list the LLM model OpenSec uses to drive agents."""


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
            hint="Run `opensec model list --provider <id>` with a valid provider ID.",
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
    default="https://github.com/galanko/OpenSec",
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
