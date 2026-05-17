"""Unit tests for RepoAgentRunner — focused on the B16 PR-URL guardrail.

The runner is non-raising by contract: every bad outcome (parse failure, GH
404, hallucinated URL) collapses to a ``RepoAgentStatus(status="failed")``
row persisted to disk. These tests drive a fake OpenCode client + a fake
``verify_pr_url`` (via monkeypatch) to exercise each branch without spinning
up a real process pool.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from cliff.services.pr_verifier import PRVerification
from cliff.workspace import repo_workspace_runner
from cliff.workspace.repo_workspace_runner import (
    RepoAgentRunner,
    read_status,
)
from cliff.workspace.workspace_dir_manager import WorkspaceKind

if TYPE_CHECKING:
    from pathlib import Path


class _FakeClient:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    async def create_session(self) -> Any:  # noqa: D401
        class _S:
            id = "sess-1"

        return _S()

    async def send_message(self, session_id: str, prompt: str) -> None:  # noqa: ARG002
        return None

    async def stream_events(self, session_id: str):  # noqa: ARG002
        yield {"type": "text", "content": self._response_text}
        yield {"type": "done"}


class _FakePool:
    def __init__(self, client: _FakeClient) -> None:
        self._client = client
        self.stopped: list[str] = []

    async def get_or_start(
        self,
        workspace_id: str,  # noqa: ARG002
        workspace_root: Path,  # noqa: ARG002
        env_vars: dict[str, str] | None = None,  # noqa: ARG002
    ) -> _FakeClient:
        return self._client

    async def stop(self, workspace_id: str) -> None:
        self.stopped.append(workspace_id)


def _scaffold_workspace(tmp_path: Path) -> Path:
    """Create the minimal directory layout the runner expects."""
    root = tmp_path / "ws-test"
    (root / "history").mkdir(parents=True)
    return root


def _agent_response(pr_url: str | None) -> str:
    payload = {
        "summary": "wrote SECURITY.md and opened PR",
        "confidence": 0.9,
        "result_card_markdown": "## ok",
        "evidence_sources": [],
        "suggested_next_action": "review_pr",
        "structured_output": {
            "status": "pr_created",
            "pr_url": pr_url,
            "branch_name": "cliff/add-security-md",
            "file_path": "SECURITY.md",
        },
    }
    return "```json\n" + json.dumps(payload) + "\n```"


@pytest.mark.asyncio
async def test_run_verifies_pr_url_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = _scaffold_workspace(tmp_path)
    pool = _FakePool(
        _FakeClient(_agent_response("https://github.com/acme/repo/pull/12"))
    )

    async def _fake_verify(url: str | None, **_: Any) -> PRVerification:
        assert url == "https://github.com/acme/repo/pull/12"
        return PRVerification(
            ok=True,
            reason="verified",
            pr_state="open",
            html_url=url,
        )

    monkeypatch.setattr(repo_workspace_runner, "verify_pr_url", _fake_verify)

    runner = RepoAgentRunner(pool)  # type: ignore[arg-type]
    result = await runner.run(
        workspace_id="ws-test",
        workspace_root=workspace_root,
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/repo",
        gh_token="ghp_x",
    )

    assert result.status == "pr_created"
    assert result.pr_url == "https://github.com/acme/repo/pull/12"
    assert result.error is None
    persisted = read_status(workspace_root)
    assert persisted is not None
    assert persisted.status == "pr_created"


@pytest.mark.asyncio
async def test_run_flags_hallucinated_pr_url_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B16 regression: verifier says 404 -> status=failed, log tail preserved."""
    workspace_root = _scaffold_workspace(tmp_path)
    # The agent's claim — a plausibly-shaped URL that doesn't resolve.
    hallucinated = "https://github.com/acme/repo/pull/999"
    pool = _FakePool(_FakeClient(_agent_response(hallucinated)))

    async def _fake_verify(url: str | None, **_: Any) -> PRVerification:
        assert url == hallucinated
        return PRVerification(
            ok=False,
            reason="not_found: GitHub returned 404 for this pull request",
        )

    monkeypatch.setattr(repo_workspace_runner, "verify_pr_url", _fake_verify)

    runner = RepoAgentRunner(pool)  # type: ignore[arg-type]
    result = await runner.run(
        workspace_id="ws-test",
        workspace_root=workspace_root,
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/repo",
        gh_token="ghp_x",
    )

    assert result.status == "failed"
    assert result.pr_url is None
    assert "PR verification failed" in (result.error or "")
    assert "not_found" in (result.error or "")
    # B16 also requires surfacing the agent's own log so the user can see
    # whether a branch was actually pushed.
    assert result.agent_log_tail is not None
    assert "pr_created" in result.agent_log_tail  # JSON payload preserved.
    # Agent-response file should also be on disk for deeper inspection.
    assert (workspace_root / "history" / "agent-response.txt").is_file()


@pytest.mark.asyncio
async def test_run_flags_compare_page_without_hitting_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed URL never reaches GitHub — the parser rejects it first."""
    workspace_root = _scaffold_workspace(tmp_path)
    # Compare-page URL the agent has emitted in real dogfooding runs.
    fake_url = "https://github.com/acme/repo/pull/new/cliff-fix"
    pool = _FakePool(_FakeClient(_agent_response(fake_url)))

    calls = {"n": 0}

    async def _counting_verify(url: str | None, **_: Any) -> PRVerification:
        calls["n"] += 1
        # The real verifier returns not_a_pull_url without doing I/O for
        # this URL shape — we mimic that behaviour here.
        return PRVerification(ok=False, reason=f"not_a_pull_url: {url!r}")

    monkeypatch.setattr(
        repo_workspace_runner, "verify_pr_url", _counting_verify
    )

    runner = RepoAgentRunner(pool)  # type: ignore[arg-type]
    result = await runner.run(
        workspace_id="ws-test",
        workspace_root=workspace_root,
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/repo",
        gh_token="ghp_x",
    )

    assert result.status == "failed"
    assert "not_a_pull_url" in (result.error or "")
    assert calls["n"] == 1
