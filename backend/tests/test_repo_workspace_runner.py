"""Unit tests for RepoAgentRunner — focused on the B16 PR-URL guardrail.

The runner is non-raising by contract: every bad outcome (model error, GH
404, hallucinated URL) collapses to a ``RepoAgentStatus(status="failed")``
row persisted to disk. These tests drive the repo-action agent with a
``FunctionModel`` (no live LLM, no tool calls) and a fake ``verify_pr_url``
(via monkeypatch) to exercise each branch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from cliff.services.pr_verifier import PRVerification
from cliff.workspace import repo_workspace_runner
from cliff.workspace.repo_workspace_runner import RepoAgentRunner, read_status
from cliff.workspace.workspace_dir_manager import WorkspaceKind

if TYPE_CHECKING:
    from pathlib import Path


def _model_returning(output: dict[str, Any]) -> FunctionModel:
    """A FunctionModel that returns *output* as the agent's structured result
    in one turn (no tool calls)."""

    def _fn(messages, info: AgentInfo) -> ModelResponse:
        tool_name = info.output_tools[0].name  # 'final_result'
        return ModelResponse(parts=[ToolCallPart(tool_name=tool_name, args=output)])

    return FunctionModel(_fn)


def _build_runner() -> RepoAgentRunner:
    return RepoAgentRunner(
        env_resolver=AsyncMock(return_value={"OPENAI_API_KEY": "k"}),
        model_resolver=AsyncMock(return_value="openai/gpt-4o-mini"),
    )


def _patch_model(monkeypatch: pytest.MonkeyPatch, model: FunctionModel) -> None:
    monkeypatch.setattr(
        repo_workspace_runner, "build_model", lambda *_a, **_k: model
    )


def _scaffold_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws-test"
    (root / "history").mkdir(parents=True)
    return root


def _pr_output(pr_url: str | None) -> dict[str, Any]:
    return {
        "status": "pr_created",
        "pr_url": pr_url,
        "branch_name": "cliff/posture/security-md",
        "file_path": "SECURITY.md",
        "summary": "wrote SECURITY.md and opened PR",
        "result_card_markdown": "## SECURITY.md PR\n\nBranch pushed, PR opened.",
    }


@pytest.mark.asyncio
async def test_run_verifies_pr_url_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = _scaffold_workspace(tmp_path)
    _patch_model(
        monkeypatch,
        _model_returning(_pr_output("https://github.com/acme/repo/pull/12")),
    )

    async def _fake_verify(url: str | None, **_: Any) -> PRVerification:
        assert url == "https://github.com/acme/repo/pull/12"
        return PRVerification(ok=True, reason="verified", pr_state="open", html_url=url)

    monkeypatch.setattr(repo_workspace_runner, "verify_pr_url", _fake_verify)

    runner = _build_runner()
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
    """B16 regression: verifier says 404 -> status=failed, diagnostics preserved."""
    workspace_root = _scaffold_workspace(tmp_path)
    hallucinated = "https://github.com/acme/repo/pull/999"
    _patch_model(monkeypatch, _model_returning(_pr_output(hallucinated)))

    async def _fake_verify(url: str | None, **_: Any) -> PRVerification:
        assert url == hallucinated
        return PRVerification(
            ok=False, reason="not_found: GitHub returned 404 for this pull request"
        )

    monkeypatch.setattr(repo_workspace_runner, "verify_pr_url", _fake_verify)

    runner = _build_runner()
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
    # The agent's result card is surfaced as the log tail for the UI.
    assert result.agent_log_tail is not None
    assert "SECURITY.md PR" in result.agent_log_tail
    # Full transcript also persisted for deeper inspection.
    assert (workspace_root / "history" / "agent-response.txt").is_file()


@pytest.mark.asyncio
async def test_run_flags_compare_page_url_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A compare-page URL is rejected by the verifier (status=failed)."""
    workspace_root = _scaffold_workspace(tmp_path)
    fake_url = "https://github.com/acme/repo/pull/new/cliff-fix"
    _patch_model(monkeypatch, _model_returning(_pr_output(fake_url)))

    calls = {"n": 0}

    async def _counting_verify(url: str | None, **_: Any) -> PRVerification:
        calls["n"] += 1
        return PRVerification(ok=False, reason=f"not_a_pull_url: {url!r}")

    monkeypatch.setattr(repo_workspace_runner, "verify_pr_url", _counting_verify)

    runner = _build_runner()
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


@pytest.mark.asyncio
async def test_run_already_present_skips_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ``already_present`` result is terminal and opens no PR."""
    workspace_root = _scaffold_workspace(tmp_path)
    _patch_model(
        monkeypatch,
        _model_returning(
            {"status": "already_present", "file_path": "SECURITY.md"}
        ),
    )

    verify = AsyncMock()
    monkeypatch.setattr(repo_workspace_runner, "verify_pr_url", verify)

    runner = _build_runner()
    result = await runner.run(
        workspace_id="ws-test",
        workspace_root=workspace_root,
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/repo",
        gh_token="ghp_x",
    )

    assert result.status == "already_present"
    verify.assert_not_called()


@pytest.mark.asyncio
async def test_run_unconfigured_model_fails_gracefully(tmp_path: Path) -> None:
    """No active model -> status=failed, never raises."""
    workspace_root = _scaffold_workspace(tmp_path)
    runner = RepoAgentRunner(
        env_resolver=AsyncMock(return_value={}),
        model_resolver=AsyncMock(return_value=None),
    )
    result = await runner.run(
        workspace_id="ws-test",
        workspace_root=workspace_root,
        kind=WorkspaceKind.repo_action_security_md,
        repo_url="https://github.com/acme/repo",
        gh_token="ghp_x",
    )
    assert result.status == "failed"
    assert "AI provider not configured" in (result.error or "")
