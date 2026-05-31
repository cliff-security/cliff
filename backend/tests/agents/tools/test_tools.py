"""Functional tests for the five remediation_executor tool primitives.

A ``SimpleNamespace`` stands in for ``RunContext`` — the tools only read
``ctx.deps`` and ``ctx.tool_call_approved``, so a full RunContext isn't
needed. ``ctx.deps`` is a real frozen ``WorkspaceDeps`` pointing at a
tmp_path workspace.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ApprovalRequired, ModelRetry

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools import bash, edit, gh, read, webfetch


def _ctx(workspace_dir, *, approved: bool = False, env_vars=None) -> SimpleNamespace:
    deps = WorkspaceDeps(
        workspace_id="ws-1",
        workspace_dir=str(workspace_dir),
        finding={"id": "f-1"},
        env_vars=env_vars or {},
    )
    return SimpleNamespace(deps=deps, tool_call_approved=approved)


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------


class TestBash:
    @pytest.mark.asyncio
    async def test_runs_command_and_returns_output(self, tmp_path):
        result = await bash(_ctx(tmp_path), "echo hello")
        assert "exit_code=0" in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_nonzero_exit_surfaced(self, tmp_path):
        result = await bash(_ctx(tmp_path), "exit 3")
        assert "exit_code=3" in result

    @pytest.mark.asyncio
    async def test_runs_in_workspace_dir(self, tmp_path):
        (tmp_path / "marker.txt").write_text("x")
        result = await bash(_ctx(tmp_path), "ls")
        assert "marker.txt" in result

    @pytest.mark.asyncio
    async def test_deny_command_raises_model_retry(self, tmp_path):
        with pytest.raises(ModelRetry, match="Cliff safety policy"):
            await bash(_ctx(tmp_path), "sudo rm -rf /")

    @pytest.mark.asyncio
    async def test_ask_command_raises_approval_required(self, tmp_path):
        with pytest.raises(ApprovalRequired):
            await bash(_ctx(tmp_path), "rm -rf build/")

    @pytest.mark.asyncio
    async def test_ask_command_runs_when_approved(self, tmp_path):
        (tmp_path / "doomed").mkdir()
        result = await bash(_ctx(tmp_path, approved=True), "rm -rf doomed")
        assert "exit_code=0" in result
        assert not (tmp_path / "doomed").exists()

    @pytest.mark.asyncio
    async def test_output_trimmed_to_last_200_lines(self, tmp_path):
        result = await bash(_ctx(tmp_path), "for i in $(seq 1 500); do echo line$i; done")
        assert "trimmed" in result
        assert "line500" in result  # tail kept
        assert "line1\n" not in result  # head dropped


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


class TestEdit:
    @pytest.mark.asyncio
    async def test_writes_relative_file(self, tmp_path):
        result = await edit(_ctx(tmp_path), "src/foo.py", "print('hi')\n")
        assert (tmp_path / "src" / "foo.py").read_text() == "print('hi')\n"
        assert "Wrote" in result

    @pytest.mark.asyncio
    async def test_absolute_path_requires_approval(self, tmp_path):
        with pytest.raises(ApprovalRequired):
            await edit(_ctx(tmp_path), "/etc/hosts", "x")

    @pytest.mark.asyncio
    async def test_traversal_requires_approval(self, tmp_path):
        with pytest.raises(ApprovalRequired):
            await edit(_ctx(tmp_path), "../../secrets.env", "x")

    @pytest.mark.asyncio
    async def test_escape_blocked_by_containment_check(self, tmp_path):
        """A path that the textual check passes but resolves outside the
        workspace is still gated by the resolved-path containment check."""
        # ``foo/../../x`` contains ``../`` so the textual classifier already
        # gates it; use a symlink to exercise the containment layer.
        outside = tmp_path.parent / "outside_repo"
        outside.mkdir(exist_ok=True)
        (tmp_path / "link").symlink_to(outside)
        with pytest.raises(ApprovalRequired):
            await edit(_ctx(tmp_path), "link/escaped.txt", "x")

    @pytest.mark.asyncio
    async def test_approved_write_outside_proceeds(self, tmp_path):
        result = await edit(_ctx(tmp_path, approved=True), "src/ok.py", "y\n")
        assert "Wrote" in result


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


class TestRead:
    @pytest.mark.asyncio
    async def test_reads_file(self, tmp_path):
        (tmp_path / "a.txt").write_text("contents")
        assert await read(_ctx(tmp_path), "a.txt") == "contents"

    @pytest.mark.asyncio
    async def test_missing_file_returns_marker(self, tmp_path):
        assert "not found" in await read(_ctx(tmp_path), "nope.txt")

    @pytest.mark.asyncio
    async def test_large_file_truncated(self, tmp_path):
        (tmp_path / "big.txt").write_text("x" * (60 * 1024))
        result = await read(_ctx(tmp_path), "big.txt")
        assert "truncated" in result
        assert len(result) < 60 * 1024


# ---------------------------------------------------------------------------
# webfetch
# ---------------------------------------------------------------------------


class TestWebfetch:
    @pytest.mark.asyncio
    async def test_returns_text_body(self, tmp_path, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/advisory",
            text="CVE details here",
            headers={"content-type": "text/plain"},
        )
        result = await webfetch(_ctx(tmp_path), "https://example.com/advisory")
        assert "CVE details here" in result
        assert "HTTP 200" in result

    @pytest.mark.asyncio
    async def test_rejects_non_text_content_type(self, tmp_path, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/blob",
            content=b"\x00\x01\x02",
            headers={"content-type": "application/octet-stream"},
        )
        result = await webfetch(_ctx(tmp_path), "https://example.com/blob")
        assert "unsupported content-type" in result

    @pytest.mark.asyncio
    async def test_json_allowed(self, tmp_path, httpx_mock):
        httpx_mock.add_response(
            url="https://api.example.com/x",
            json={"ok": True},
            headers={"content-type": "application/json"},
        )
        result = await webfetch(_ctx(tmp_path), "https://api.example.com/x")
        assert "ok" in result


# ---------------------------------------------------------------------------
# gh
# ---------------------------------------------------------------------------


class TestGh:
    @pytest.mark.asyncio
    async def test_missing_token_returns_hint(self, tmp_path):
        result = await gh(_ctx(tmp_path, env_vars={}), "pr create")
        assert "GH_TOKEN is not set" in result

    @pytest.mark.asyncio
    async def test_delegates_to_bash_with_gh_prefix(self, tmp_path, monkeypatch):
        captured = {}

        async def _fake_bash(ctx, command):
            captured["command"] = command
            return "exit_code=0\n"

        # The package __init__ re-exports ``gh`` (the function), which
        # shadows the ``gh`` submodule as a package attribute — so both a
        # dotted-string target and ``import ...tools.gh as`` resolve to
        # the function. sys.modules always holds the real module object,
        # so patch through it.
        import sys

        gh_module = sys.modules["cliff.agents.runtime.tools.gh"]
        monkeypatch.setattr(gh_module, "bash", _fake_bash)
        await gh(_ctx(tmp_path, env_vars={"GH_TOKEN": "ghx"}), "pr create --title x")
        assert captured["command"] == "gh pr create --title x"
