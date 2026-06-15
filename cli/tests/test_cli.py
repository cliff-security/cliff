"""Unit tests for the agent CLI.

These mock the Cliff HTTP API via pytest-httpx and assert the JSON shape +
exit codes the skill depends on. The contract surface is tiny on purpose —
the skill cannot tolerate drift here without breaking for every user.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from cliff_cli.cli import main


@pytest.fixture(autouse=True)
def _set_base_url(monkeypatch):
    monkeypatch.setenv("CLIFF_URL", "http://test-server")


@pytest.fixture
def cli():
    return CliRunner()


def _last_json(text: str) -> dict:
    """Extract the last JSON line from output (commands always emit one)."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    assert lines, f"expected JSON output, got: {text!r}"
    return json.loads(lines[-1])


def _stub_ai_integration_status(
    httpx_mock,
    *,
    model: str | None = None,
) -> None:
    """Stub ``GET /api/integrations/ai/status`` for ``cliffsec status``.

    ADR-0037 / architect M9: the live-probe + drift signal were removed.
    The CLI now only reads the canonical ``model`` field; the singleton
    OpenCode is restarted synchronously by ``on_key_change`` on every
    canonical-state write, so there is no separate "what's actually
    loaded" value to surface.
    """
    httpx_mock.add_response(
        url="http://test-server/api/integrations/ai/status",
        json={"model": model},
    )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_ready(cli, httpx_mock):
    httpx_mock.add_response(
        url="http://test-server/health",
        json={
            "cliff": "ok",
            "opencode": "ok",
            "opencode_version": "1.3.2",
            "model": "openai/gpt-4.1",
            "ai_provider_ready": True,
        },
    )
    httpx_mock.add_response(
        url="http://test-server/api/version",
        json={
            "cliff": "0.1.1-alpha",
            "opencode": "1.3.2",
            "schema_version": "1",
            "min_cli": "0.1.0",
        },
    )
    _stub_ai_integration_status(httpx_mock, model="openai/gpt-4.1")
    res = cli.invoke(main, ["status"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert payload["cliff"] == "0.1.1-alpha"
    assert payload["blockers"] == []


def test_status_blocked_when_ai_provider_not_ready(cli, httpx_mock):
    """A connected-but-unusable AI provider must not read as ready.

    The engine is up and a model string is set, but no provider credential
    resolved into the workspace env — health reports ai_provider_ready
    False, and ``status`` must surface that as a blocker.
    """
    httpx_mock.add_response(
        url="http://test-server/health",
        json={
            "cliff": "ok",
            "opencode": "ok",
            "opencode_version": "1.3.2",
            "model": "anthropic/claude-sonnet-4-6",
            "ai_provider_ready": False,
        },
    )
    httpx_mock.add_response(
        url="http://test-server/api/version",
        json={
            "cliff": "0.1.1-alpha",
            "opencode": "1.3.2",
            "schema_version": "1",
            "min_cli": "0.1.0",
        },
    )
    _stub_ai_integration_status(
        httpx_mock, model="anthropic/claude-sonnet-4-6"
    )
    res = cli.invoke(main, ["status"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["ready"] is False
    assert "no_ai_provider_credential" in payload["blockers"]
    assert "no_llm_model_configured" not in payload["blockers"]


def test_status_blockers_when_unconfigured(cli, httpx_mock):
    """No model + no provider credential → both blockers, not ready (ADR-0047:
    there is no engine to be 'down', so readiness rests on AI config)."""
    httpx_mock.add_response(
        url="http://test-server/health",
        json={
            "cliff": "ok",
            "opencode": "ok",
            "opencode_version": "pydantic-ai 1.98.0",
            "model": "",
        },
    )
    httpx_mock.add_response(
        url="http://test-server/api/version",
        json={
            "cliff": "0.1.1-alpha",
            "opencode": "pydantic-ai 1.98.0",
            "schema_version": "1",
            "min_cli": "0.1.0",
        },
    )
    _stub_ai_integration_status(httpx_mock, model=None)
    res = cli.invoke(main, ["status"])
    assert res.exit_code == 0
    payload = _last_json(res.stdout)
    assert payload["ready"] is False
    assert "no_llm_model_configured" in payload["blockers"]
    assert "no_ai_provider_credential" in payload["blockers"]
    # No engine concept anymore.
    assert "opencode_engine_unavailable" not in payload["blockers"]


def test_status_prefers_canonical_model_and_omits_drift_fields(
    cli, httpx_mock
):
    """Post-M9 contract (architect health-check H5):

    * The CLI's ``model`` field is sourced from the canonical
      ``/api/integrations/ai/status`` response, not from ``/health``.
    * The legacy ``drifted`` / ``canonical_model`` / ``opencode_model``
      fields and the ``model_drift`` blocker are GONE — the
      ``on_key_change`` hook makes drift unrepresentable, so the CLI
      doesn't pretend to detect it.
    """
    httpx_mock.add_response(
        url="http://test-server/health",
        json={
            "cliff": "ok",
            "opencode": "ok",
            "opencode_version": "1.3.2",
            # /health still carries the singleton's view; canonical wins.
            "model": "anthropic/claude-haiku-4-5",
            "ai_provider_ready": True,
        },
    )
    httpx_mock.add_response(
        url="http://test-server/api/version",
        json={
            "cliff": "0.1.1-alpha",
            "opencode": "1.3.2",
            "schema_version": "1",
            "min_cli": "0.1.0",
        },
    )
    _stub_ai_integration_status(
        httpx_mock, model="anthropic/claude-sonnet-4-6"
    )

    res = cli.invoke(main, ["status"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)

    # Canonical (sonnet) wins over /health.model (haiku).
    assert payload["model"] == "anthropic/claude-sonnet-4-6"
    # Drift signals are gone.
    assert "drifted" not in payload
    assert "canonical_model" not in payload
    assert "opencode_model" not in payload
    assert "model_drift" not in payload["blockers"]
    # No spurious blockers on the happy path.
    assert payload["blockers"] == []
    assert payload["ready"] is True


def test_status_falls_back_to_health_model_when_status_endpoint_unavailable(
    cli, httpx_mock
):
    """If ``/api/integrations/ai/status`` 4xx/5xx (no vault yet, very
    fresh install), the CLI must still report a model — taken from
    ``/health.model`` — and not falsely report ``no_llm_model_configured``.
    """
    httpx_mock.add_response(
        url="http://test-server/health",
        json={
            "cliff": "ok",
            "opencode": "ok",
            "opencode_version": "1.3.2",
            "model": "anthropic/claude-haiku-4-5",
            "ai_provider_ready": True,
        },
    )
    httpx_mock.add_response(
        url="http://test-server/api/version",
        json={
            "cliff": "0.1.1-alpha",
            "opencode": "1.3.2",
            "schema_version": "1",
            "min_cli": "0.1.0",
        },
    )
    httpx_mock.add_response(
        url="http://test-server/api/integrations/ai/status",
        status_code=500,
    )

    res = cli.invoke(main, ["status"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["model"] == "anthropic/claude-haiku-4-5"
    assert "no_llm_model_configured" not in payload["blockers"]


def test_status_daemon_down(cli, httpx_mock):
    import httpx

    httpx_mock.add_exception(httpx.ConnectError("refused"))
    res = cli.invoke(main, ["status"])
    assert res.exit_code == 3
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "daemon_down"


def test_status_version_mismatch(cli, httpx_mock):
    httpx_mock.add_response(
        url="http://test-server/health",
        json={"cliff": "ok", "opencode": "ok", "opencode_version": "1.3.2", "model": "x"},
    )
    httpx_mock.add_response(
        url="http://test-server/api/version",
        json={
            "cliff": "9.9.9",
            "opencode": "1.3.2",
            "schema_version": "2",
            "min_cli": "9.9.9",
        },
    )
    res = cli.invoke(main, ["status"])
    assert res.exit_code == 4
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert payload["error"]["code"] == "version_mismatch"
    assert payload["min_cli"] == "9.9.9"


# ---------------------------------------------------------------------------
# issues
# ---------------------------------------------------------------------------


def _stub_version(httpx_mock):
    httpx_mock.add_response(
        url="http://test-server/api/version",
        json={
            "cliff": "0.1.1-alpha",
            "opencode": "1.3.2",
            "schema_version": "1",
            "min_cli": "0.1.0",
        },
    )


def test_issues_filters_by_severity(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/findings?scope=current&limit=200&status=new",
        json=[
            {
                "id": "f1",
                "title": "log4j RCE",
                "type": "dependency",
                "status": "new",
                "normalized_priority": "critical",
                "derived": {"workspace_id": None},
            },
            {
                "id": "f2",
                "title": "minor lint",
                "type": "code",
                "status": "new",
                "normalized_priority": "low",
            },
        ],
    )
    res = cli.invoke(main, ["issues", "--severity", "critical,high"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert [i["id"] for i in payload["issues"]] == ["f1"]
    assert payload["next"] == "fix f1"


def test_issues_empty(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/findings?scope=current&limit=200&status=new",
        json=[],
    )
    res = cli.invoke(main, ["issues"])
    assert res.exit_code == 0
    payload = _last_json(res.stdout)
    assert payload["issues"] == []
    assert payload["next"] is None


# ---------------------------------------------------------------------------
# scan — exit 5 when no findings
# ---------------------------------------------------------------------------


def test_scan_exits_5_when_clean(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/assessment/run",
        method="POST",
        json={"assessment_id": "asm-1", "status": "pending"},
    )
    httpx_mock.add_response(
        url="http://test-server/api/assessment/status/asm-1",
        json={"assessment_id": "asm-1", "status": "complete", "progress_pct": 100},
    )
    httpx_mock.add_response(
        url="http://test-server/api/findings?scope=current&limit=1000",
        json=[],
    )
    res = cli.invoke(main, ["scan", "https://github.com/example/repo"])
    assert res.exit_code == 5
    payload = _last_json(res.stdout)
    assert payload["finding_count"] == 0
    assert payload["scan_id"] == "asm-1"


def test_scan_counts_by_severity(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/assessment/run",
        method="POST",
        json={"assessment_id": "asm-2", "status": "pending"},
    )
    httpx_mock.add_response(
        url="http://test-server/api/assessment/status/asm-2",
        json={"assessment_id": "asm-2", "status": "complete", "progress_pct": 100},
    )
    httpx_mock.add_response(
        url="http://test-server/api/findings?scope=current&limit=1000",
        json=[
            {"id": "a", "title": "x", "normalized_priority": "critical"},
            {"id": "b", "title": "y", "normalized_priority": "high"},
            {"id": "c", "title": "z", "normalized_priority": "high"},
        ],
    )
    res = cli.invoke(main, ["scan", "https://github.com/example/repo"])
    assert res.exit_code == 0
    payload = _last_json(res.stdout)
    assert payload["finding_count"] == 3
    assert payload["by_severity"] == {"critical": 1, "high": 2}


# ---------------------------------------------------------------------------
# fix — triage-gated: real -> plan (exit 2); noise -> cleared (exit 0);
#       needs_review -> human review (exit 2). ADR-0051 §6 Plan gate.
# ---------------------------------------------------------------------------


def _stub_triage_start(httpx_mock, workspace_id="ws-1"):
    """``POST /api/findings/{id}/triage`` returns 202 with the workspace id."""
    httpx_mock.add_response(
        url="http://test-server/api/findings/f1/triage",
        method="POST",
        status_code=202,
        json={"workspace_id": workspace_id, "status": "running"},
    )


def test_fix_real_verdict_pauses_at_plan(cli, httpx_mock):
    """A `real` triage verdict proceeds to a remediation plan and stops at the
    approval gate (exit 2) — the existing CLI contract for a true positive."""
    _stub_version(httpx_mock)
    _stub_triage_start(httpx_mock)
    # First poll: triage verdict = real (reachable).
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        json={
            "workspace_id": "ws-1",
            "triage": {
                "verdict": "real",
                "confidence": 0.82,
                "exploitability": {
                    "exploitable": "yes",
                    "reason": "Reachable from an internet-facing entrypoint.",
                },
            },
            "updated_at": "x",
        },
    )
    # The real branch runs the planner pipeline.
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/pipeline/run-all",
        method="POST",
        status_code=202,
        json={"status": "running", "message": "started"},
    )
    # Second poll: plan ready.
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        json={
            "workspace_id": "ws-1",
            "triage": {"verdict": "real", "confidence": 0.82},
            "plan": {
                "plan_steps": ["update pom.xml", "rebuild"],
                "interim_mitigation": "Block log4j on WAF",
                "approved": False,
            },
            "definition_of_done": {"items": ["tests pass", "no log4j <2.17 in lockfile"]},
            "updated_at": "x",
        },
    )
    res = cli.invoke(main, ["fix", "f1"])
    assert res.exit_code == 2, res.stderr
    payload = _last_json(res.stdout)
    assert payload["workspace_id"] == "ws-1"
    assert payload["verdict"] == "real"
    assert payload["awaiting"] == "plan_approval"
    assert payload["plan"]["steps"] == ["update pom.xml", "rebuild"]
    assert payload["plan"]["interim_mitigation"] == "Block log4j on WAF"
    assert payload["plan"]["definition_of_done"] == [
        "tests pass",
        "no log4j <2.17 in lockfile",
    ]
    assert "summary" not in payload["plan"]
    assert payload["next"] == "approve ws-1"


@pytest.mark.parametrize("verdict", ["unexploitable", "false_positive"])
def test_fix_clears_noise_with_reasoning(cli, httpx_mock, verdict):
    """A non-real verdict clears the finding as noise WITH the reasoning on
    record and NEVER produces a remediation plan (the report-tour bright line:
    zero false-positive-shaped alarms). Exits 0 — nothing to fix."""
    _stub_version(httpx_mock)
    _stub_triage_start(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        json={
            "workspace_id": "ws-1",
            "triage": {
                "verdict": verdict,
                "confidence": 0.88,
                "exploitability": {
                    "exploitable": "no",
                    "reason": (
                        "shell-quote is a dev-only dependency, "
                        "never imported by shipped code."
                    ),
                },
                "reachability": {"reached": False, "path": [], "summary": "No path found."},
            },
            "updated_at": "x",
        },
    )
    res = cli.invoke(main, ["fix", "f1"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["workspace_id"] == "ws-1"
    assert payload["verdict"] == verdict
    assert payload["cleared"] is True
    assert "dev-only" in payload["reason"]
    assert payload["confidence"] == 0.88
    assert payload["next"] == "close ws-1"
    assert "plan" not in payload
    # The planner pipeline must never have been invoked for noise.
    assert not any(
        r.url.path.endswith("/pipeline/run-all")
        for r in httpx_mock.get_requests()
    )


def test_fix_needs_review_flags_for_human(cli, httpx_mock):
    """A `needs_review` verdict is flagged for human judgment (exit 2) — not an
    alarmist plan, not a silent clear."""
    _stub_version(httpx_mock)
    _stub_triage_start(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        json={
            "workspace_id": "ws-1",
            "triage": {
                "verdict": "needs_review",
                "confidence": 0.55,
                "exploitability": {
                    "exploitable": "unknown",
                    "reason": "A real advisory, but reachability of the sink is undetermined.",
                },
            },
            "updated_at": "x",
        },
    )
    res = cli.invoke(main, ["fix", "f1"])
    assert res.exit_code == 2, res.stderr
    payload = _last_json(res.stdout)
    assert payload["verdict"] == "needs_review"
    assert payload["cleared"] is False
    assert payload["awaiting"] == "human_review"
    assert payload["next"] is None
    assert "undetermined" in payload["reason"]
    assert not any(
        r.url.path.endswith("/pipeline/run-all")
        for r in httpx_mock.get_requests()
    )


def test_fix_tolerates_initial_404(cli, httpx_mock):
    """The sidebar row is created lazily by the first triage write — a 404 on
    the very first poll is normal and must not crash the CLI."""
    _stub_version(httpx_mock)
    _stub_triage_start(httpx_mock)
    # First sidebar poll: 404 (worker hasn't seeded yet)
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        status_code=404,
        json={"detail": "Sidebar state not found"},
    )
    # Second poll: verdict ready (cleared as noise).
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        json={
            "workspace_id": "ws-1",
            "triage": {
                "verdict": "unexploitable",
                "confidence": 0.88,
                "exploitability": {"exploitable": "no", "reason": "Not reachable."},
            },
            "updated_at": "x",
        },
    )
    res = cli.invoke(main, ["fix", "f1"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["verdict"] == "unexploitable"
    assert payload["cleared"] is True


def test_fix_timeout_emits_json_error(cli, httpx_mock):
    """A polling timeout must surface as a JSON error, not a Python traceback."""
    _stub_version(httpx_mock)
    _stub_triage_start(httpx_mock)
    # Sidebar never gets a triage verdict — is_done never true, poll() times out.
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        is_reusable=True,
        json={"workspace_id": "ws-1", "updated_at": "x"},
    )
    res = cli.invoke(main, ["fix", "f1", "--timeout", "0.05"])
    assert res.exit_code == 1
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "timeout"
    assert "polling" in payload["error"]["hint"].lower()


# ---------------------------------------------------------------------------
# approve — returns PR URL when validation passes
# ---------------------------------------------------------------------------


def test_approve_passes_validation(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/plan/approve",
        method="POST",
        json={"workspace_id": "ws-1", "updated_at": "x"},
    )
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/pipeline/run-all",
        method="POST",
        status_code=202,
        json={"status": "running", "message": "go"},
    )
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        json={
            "workspace_id": "ws-1",
            "validation": {"verdict": "ok", "reason": "tests pass"},
            "pull_request": {
                "pr_url": "https://github.com/x/y/pull/1",
                "branch_name": "fix/log4j",
            },
            "updated_at": "x",
        },
    )
    res = cli.invoke(main, ["approve", "ws-1"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["pr_url"] == "https://github.com/x/y/pull/1"
    assert payload["branch"] == "fix/log4j"
    assert payload["validation"]["verdict"] == "ok"
    assert payload["next"] == "close ws-1"


def test_approve_validation_failed_exits_2(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/plan/approve",
        method="POST",
        json={"workspace_id": "ws-1", "updated_at": "x"},
    )
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/pipeline/run-all",
        method="POST",
        status_code=202,
        json={"status": "running", "message": "go"},
    )
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1/sidebar",
        json={
            "workspace_id": "ws-1",
            "validation": {"verdict": "fail", "reason": "tests broke"},
            "pull_request": {},
            "updated_at": "x",
        },
    )
    res = cli.invoke(main, ["approve", "ws-1"])
    assert res.exit_code == 2
    payload = _last_json(res.stdout)
    assert payload["validation"]["verdict"] == "fail"
    assert payload["next"] is None


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_marks_workspace(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/workspaces/ws-1",
        method="PATCH",
        json={
            "id": "ws-1",
            "finding_id": "f1",
            "state": "closed",
            "created_at": "x",
            "updated_at": "x",
        },
    )
    res = cli.invoke(main, ["close", "ws-1"])
    assert res.exit_code == 0
    payload = _last_json(res.stdout)
    assert payload["closed"] is True
    assert payload["finding_id"] == "f1"


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------


def test_model_get(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/settings/model",
        json={
            "model_full_id": "openai/gpt-5-nano",
            "provider": "openai",
            "model_id": "gpt-5-nano",
        },
    )
    res = cli.invoke(main, ["model", "get"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["model_full_id"] == "openai/gpt-5-nano"
    assert payload["provider"] == "openai"


def test_model_set(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/settings/model",
        method="PUT",
        json={
            "model_full_id": "openai/gpt-5-nano",
            "provider": "openai",
            "model_id": "gpt-5-nano",
        },
    )
    res = cli.invoke(main, ["model", "set", "openai/gpt-5-nano"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["model_full_id"] == "openai/gpt-5-nano"


def test_model_list_projects_locally(cli, httpx_mock):
    """The provider catalog can be huge — `model list` must return only the
    slim id+name slice the agent driving the CLI needs."""
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/settings/providers",
        json=[
            {
                "id": "openai",
                "models": {
                    "gpt-5-nano": {"name": "GPT-5 Nano", "cost": {"input": 0.05}},
                    "gpt-4.1-nano": {"name": "GPT-4.1 Nano"},
                },
            },
            {"id": "anthropic", "models": {"claude-opus-4-7": {"name": "Claude Opus 4.7"}}},
        ],
    )
    res = cli.invoke(main, ["model", "list", "--provider", "openai"])
    assert res.exit_code == 0, res.stderr
    payload = _last_json(res.stdout)
    assert payload["provider"] == "openai"
    assert {"id": "gpt-5-nano", "name": "GPT-5 Nano"} in payload["models"]
    # Cost / capabilities must NOT leak through — projection is lossy on purpose.
    assert all(set(m.keys()) == {"id", "name"} for m in payload["models"])


def test_model_list_unknown_provider(cli, httpx_mock):
    _stub_version(httpx_mock)
    httpx_mock.add_response(
        url="http://test-server/api/settings/providers",
        json=[{"id": "openai", "models": {}}],
    )
    res = cli.invoke(main, ["model", "list", "--provider", "bogus"])
    assert res.exit_code == 1
    payload = json.loads(res.stderr.strip().splitlines()[-1])
    assert payload["error"]["code"] == "provider_not_found"
