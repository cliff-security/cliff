"""Unit tests for repo-action agent templates (IMPL-0002 E1, E2).

These are template-rendering tests — no LLM calls, no OpenCode binary, no
subprocess. They verify the Jinja2 templates for ``security_md_generator``
and ``dependabot_config_generator`` render the expected prompt shape so
the downstream single-shot agent (ADR-0024) knows what to do.
"""

from __future__ import annotations

import re

import pytest

from cliff.agents.template_engine import AgentTemplateEngine
from cliff.workspace.workspace_dir_manager import WorkspaceKind


@pytest.fixture
def engine() -> AgentTemplateEngine:
    return AgentTemplateEngine()


def _assert_never_writes_host_git_config(content: str) -> None:
    """Templates must NEVER run ``git config --global`` (or ``--system``).

    Those scopes always write the operator's host config and cannot fail
    closed, so a dropped env var or a reordered/retried step would silently
    pollute ``~/.gitconfig`` — injecting an expired ``x-access-token`` rewrite
    and the ``Cliff Posture Bot`` identity, which then breaks the operator's
    own ``git push``. Instead, clone auth is carried by a token-embedded clone
    URL (confined to the throwaway ``repo/.git/config``) and commit identity is
    set with ``git config --local`` (which errors out when not inside a repo).

    Regression guard for the host-gitconfig-pollution bug.
    """
    assert "git config --global" not in content, (
        "templates must not run `git config --global` — it always writes the "
        "operator's host ~/.gitconfig and cannot fail closed"
    )
    assert "git config --system" not in content, (
        "templates must not run `git config --system`"
    )


class TestSecurityMdGenerator:
    """Rendering contract for the SECURITY.md generator template."""

    def test_renders_template_with_repo_url(self, engine: AgentTemplateEngine) -> None:
        rendered = engine.render_repo_action(
            WorkspaceKind.repo_action_security_md,
            repo_url="https://github.com/acme/widget",
            params={"contact_email": "security@acme.example"},
            gh_token="ghp_fake_token_for_render_test",
        )

        assert rendered.name == "security_md_generator"
        assert rendered.filename == "security_md_generator.md"
        content = rendered.content

        # Repo URL is substituted so the agent knows what to clone.
        assert "https://github.com/acme/widget" in content

        # Branch name convention for zero-to-secure posture PRs.
        assert "cliff/posture/security-md" in content

        # Draft-PR-only per ADR-0024.
        assert "gh pr create --draft" in content

        # When gh_token is provided, the git-config line referencing $GH_TOKEN
        # from the workspace env is emitted — but the literal token value must
        # never appear in the rendered prompt (it would otherwise reach the LLM).
        assert "x-access-token:${GH_TOKEN}" in content
        assert "ghp_fake_token_for_render_test" not in content

        # Must never touch the operator's host ~/.gitconfig.
        _assert_never_writes_host_git_config(content)
        assert "git config --local user.name" in content

        # Must include the SECURITY.md target path instruction.
        assert "SECURITY.md" in content

        # Must tell the agent how to handle an existing SECURITY.md.
        assert re.search(r"already\s+exists|if\s+SECURITY\.md", content, re.IGNORECASE), (
            "Template must instruct agent on handling an existing SECURITY.md"
        )

        # The structured JSON output contract is present.
        assert "structured_output" in content
        assert '"pr_url"' in content
        assert '"status"' in content

    def test_contact_email_substituted(self, engine: AgentTemplateEngine) -> None:
        rendered = engine.render_repo_action(
            WorkspaceKind.repo_action_security_md,
            repo_url="https://github.com/acme/widget",
            params={"contact_email": "ciso@example.org"},
        )
        assert "ciso@example.org" in rendered.content

    def test_renders_without_gh_token(self, engine: AgentTemplateEngine) -> None:
        """When no token is supplied, the whole git-config block is elided."""
        rendered = engine.render_repo_action(
            WorkspaceKind.repo_action_security_md,
            repo_url="https://github.com/acme/widget",
            params={},
        )
        assert "x-access-token" not in rendered.content
        assert "GH_TOKEN" not in rendered.content


class TestDependabotConfigGenerator:
    """Rendering contract for the dependabot.yml generator template."""

    def test_renders_template_with_repo_url(self, engine: AgentTemplateEngine) -> None:
        rendered = engine.render_repo_action(
            WorkspaceKind.repo_action_dependabot,
            repo_url="https://github.com/acme/widget",
            params={},
            gh_token="ghp_dependabot_token",
        )

        assert rendered.name == "dependabot_config_generator"
        content = rendered.content

        assert "https://github.com/acme/widget" in content
        assert "cliff/posture/dependabot" in content
        assert "gh pr create --draft" in content
        assert ".github/dependabot.yml" in content

        # Token value must never appear in the rendered prompt.
        assert "ghp_dependabot_token" not in content
        assert "x-access-token:${GH_TOKEN}" in content

        # Must never touch the operator's host ~/.gitconfig.
        _assert_never_writes_host_git_config(content)
        assert "git config --local user.name" in content

        # Ecosystem detection instruction is the distinctive part of this template.
        for manifest in [
            "package-lock.json",
            "requirements.txt",
            "go.mod",
            "Gemfile.lock",
            "Cargo.toml",
            "pom.xml",
            "composer.json",
        ]:
            assert manifest in content, f"Ecosystem manifest {manifest} missing"

        # Weekly schedule + PR limit are part of the rendered config shape.
        assert re.search(r"schedule.*weekly", content, re.IGNORECASE | re.DOTALL)
        assert re.search(r"open-pull-requests-limit", content)

        # Handle existing config gracefully.
        assert re.search(
            r"already\s+exists|if\s+\.github/dependabot\.yml|existing\s+dependabot",
            content,
            re.IGNORECASE,
        ), "Template must instruct agent on handling an existing dependabot.yml"

        assert "structured_output" in content

    def test_invalid_kind_raises(
        self, engine: AgentTemplateEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``WorkspaceKind`` value without a registered template is rejected."""
        from cliff.agents import template_engine as te

        monkeypatch.setattr(te, "REPO_ACTION_TEMPLATES", {})
        with pytest.raises(ValueError, match="not a repo-action"):
            engine.render_repo_action(
                WorkspaceKind.repo_action_security_md,
                repo_url="https://github.com/acme/widget",
                params={},
            )


class TestCloningAgentsNeverWriteHostGitConfig:
    """The other two cloning templates aren't repo-actions (they go through
    ``render_agent``), but they run git just the same — the executor even
    pushes commits. Guard them against host-gitconfig writes too, so a
    regression in either one fails the suite.
    """

    @pytest.mark.parametrize("agent_name", ["remediation_executor", "evidence_collector"])
    def test_no_host_git_config_writes(
        self, engine: AgentTemplateEngine, agent_name: str
    ) -> None:
        rendered = engine.render_agent(
            agent_name,
            finding={"title": "Test finding", "source_id": "CVE-2024-0001"},
            gh_token="ghp_fake_token_for_render_test",
            repo_url="https://github.com/acme/widget",
        )
        _assert_never_writes_host_git_config(rendered.content)
        # Authenticated clone is carried by a token-embedded URL, not a config write.
        assert "x-access-token:${GH_TOKEN}@" in rendered.content
