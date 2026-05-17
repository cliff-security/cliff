"""E2E tests for repo-action agent templates (IMPL-0002 I3).

Each test dogfoods a single-shot repo-action agent against the Cliff
repo itself (resolved from ``git config --get remote.origin.url``). The
flow exercised end-to-end is:

    create_repo_workspace  →  pool.start(env={GH_TOKEN})
                           →  send rendered prompt
                           →  parse JSON output contract
                           →  assert draft PR opened
                           →  close PR + delete branch + stop_on_completion

Prerequisites (auto-skipped by ``tests/e2e/conftest.py`` and the inline
skips in this file):

- OpenCode binary installed
- ``OPENAI_API_KEY`` or ``ANTHROPIC_API_KEY`` set
- ``GH_TOKEN`` set with write access to the Cliff origin repo
- ``gh`` CLI on ``$PATH`` (for teardown)
- The current clone's ``origin`` points to an ``https://github.com/...`` URL

The tests are network- and cost-sensitive and each should complete inside
10 minutes. Teardown MUST run even on failure — we do not leave draft PRs
or branches lying around on the Cliff repo.

**Not xdist-safe.** Both tests push the fixed branch names
``cliff/posture/security-md`` and ``cliff/posture/dependabot``. If run
concurrently (e.g. under ``pytest-xdist``), two workers race on the same
push ref and one fails. Keep this suite single-threaded or make the branch
name unique per run before enabling ``-n auto``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from shutil import which
from typing import TYPE_CHECKING

import pytest

from cliff.agents.output_parser import extract_json_block
from cliff.agents.template_engine import AgentTemplateEngine
from cliff.engine.pool import PortAllocator, WorkspaceProcessPool
from cliff.workspace.workspace_dir_manager import WorkspaceDirManager, WorkspaceKind

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Environment discovery
# ---------------------------------------------------------------------------


def _resolve_origin_url() -> str | None:
    """Resolve the Cliff clone's origin URL, normalised to HTTPS.

    Returns None if the repo isn't a git checkout or origin isn't GitHub.
    """
    try:
        out = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    if not out:
        return None

    # Normalise git@github.com:org/repo.git → https://github.com/org/repo
    m = re.match(r"git@github\.com:(?P<path>[^/]+/.+?)(?:\.git)?$", out)
    if m:
        return f"https://github.com/{m.group('path')}"

    m = re.match(r"https?://github\.com/(?P<path>[^/]+/.+?)(?:\.git)?$", out)
    if m:
        return f"https://github.com/{m.group('path')}"

    return None


_ORIGIN_URL = _resolve_origin_url()
_GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
_GH_CLI = which("gh")

_skip_no_origin = pytest.mark.skipif(
    _ORIGIN_URL is None,
    reason="Could not resolve an https github.com origin for this clone",
)
_skip_no_token = pytest.mark.skipif(
    not _GH_TOKEN,
    reason="GH_TOKEN / GITHUB_TOKEN is not set — refusing to run write-capable E2E",
)
_skip_no_gh_cli = pytest.mark.skipif(
    _GH_CLI is None,
    reason="`gh` CLI not on PATH — teardown cannot close the draft PR",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_structured_output(text: str) -> dict | None:
    """Extract the repo-action agent's output contract, unwrapping structured_output."""
    payload = extract_json_block(text)
    if payload is None:
        return None
    return payload.get("structured_output") or payload


def _close_pr_and_branch(pr_url: str | None, branch: str, repo: str) -> None:
    """Best-effort teardown — close draft PR and delete its branch.

    Failures are logged (not raised) so the surrounding ``finally`` block can
    still call ``stop_on_completion``. Silent swallowing would leave an
    operator staring at a leftover branch with no diagnostic.
    """
    if _GH_CLI is None or _GH_TOKEN is None:
        return
    env = {**os.environ, "GH_TOKEN": _GH_TOKEN}
    if pr_url:
        # `gh pr close --delete-branch` closes and removes the branch in one shot.
        cmd = [
            _GH_CLI, "pr", "close", pr_url, "--delete-branch", "--comment",
            "Automated Cliff E2E run — closing and deleting branch.",
        ]
    else:
        # No PR (agent may have aborted) — best-effort delete of the branch.
        cmd = [_GH_CLI, "api", "-X", "DELETE",
               f"repos/{repo}/git/refs/heads/{branch}"]

    result = subprocess.run(cmd, env=env, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(
            "Teardown command %s failed (rc=%d): stdout=%s stderr=%s",
            cmd[:3], result.returncode, result.stdout.strip(), result.stderr.strip(),
        )


def _repo_slug(url: str) -> str:
    """`https://github.com/acme/widget` → `acme/widget`."""
    return url.removeprefix("https://github.com/").removesuffix(".git")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dir_manager(tmp_path: Path) -> WorkspaceDirManager:
    return WorkspaceDirManager(base_dir=tmp_path / "workspaces")


@pytest.fixture
def template_engine() -> AgentTemplateEngine:
    return AgentTemplateEngine()


@pytest.fixture
async def pool():
    # Ports 4250-4259 — distinct from other E2E suites.
    p = WorkspaceProcessPool(port_allocator=PortAllocator(start=4250, end=4259))
    yield p
    await p.stop_all()


# ---------------------------------------------------------------------------
# Test bodies
# ---------------------------------------------------------------------------


async def _run_repo_action_e2e(
    *,
    kind: WorkspaceKind,
    template_stem: str,
    branch_name: str,
    params: dict,
    dir_manager: WorkspaceDirManager,
    pool: WorkspaceProcessPool,
) -> None:
    """Shared driver: kick off a repo-action agent and verify the PR."""
    assert _ORIGIN_URL is not None  # guarded by module-level skip
    assert _GH_TOKEN is not None
    repo_url = _ORIGIN_URL
    repo_slug = _repo_slug(repo_url)

    workspace_id = dir_manager.create_repo_workspace(
        kind,
        repo_url=repo_url,
        params=params,
        gh_token=_GH_TOKEN,
    )
    ws_dir = dir_manager.base_dir / workspace_id
    agent_prompt = (ws_dir / ".opencode" / "agents" / f"{template_stem}.md").read_text()

    client = await pool.start(
        workspace_id,
        ws_dir,
        env_vars={"GH_TOKEN": _GH_TOKEN},
    )

    structured: dict | None = None
    pr_url: str | None = None
    try:
        session = await client.create_session()
        response = await client.send_and_get_response(
            session.id,
            agent_prompt,
            timeout=600.0,  # 10 minutes for clone + push + PR
            poll_interval=5.0,
        )
        assert response, "Agent returned no response within timeout"

        structured = _extract_structured_output(response)
        assert structured is not None, (
            f"Agent did not emit a parseable JSON output contract. "
            f"Raw response: {response[:400]!r}"
        )

        status = structured.get("status")
        pr_url = structured.get("pr_url")

        assert status in {"pr_created", "already_present"}, (
            f"Unexpected agent status: {status!r}. Full output: {structured!r}"
        )

        if status == "pr_created":
            assert pr_url, "status=pr_created but pr_url is missing"
            assert re.match(
                r"https://github\.com/[^/]+/[^/]+/pull/\d+$", pr_url
            ), f"pr_url does not look like a GitHub PR URL: {pr_url!r}"
            assert structured.get("branch_name") == branch_name

    finally:
        # Always tear down — we cannot leave PRs on the Cliff repo.
        try:
            _close_pr_and_branch(pr_url, branch_name, repo_slug)
        finally:
            archive = await pool.stop_on_completion(workspace_id)
            if archive is not None:
                archive.unlink(missing_ok=True)


@_skip_no_origin
@_skip_no_token
@_skip_no_gh_cli
async def test_security_md_generator_opens_draft_pr(
    dir_manager: WorkspaceDirManager, pool: WorkspaceProcessPool
) -> None:
    """Dogfood the SECURITY.md generator against the Cliff repo."""
    await _run_repo_action_e2e(
        kind=WorkspaceKind.repo_action_security_md,
        template_stem="security_md_generator",
        branch_name="cliff/posture/security-md",
        params={"contact_email": "security@cliff.example"},
        dir_manager=dir_manager,
        pool=pool,
    )


@_skip_no_origin
@_skip_no_token
@_skip_no_gh_cli
async def test_dependabot_config_generator_opens_draft_pr(
    dir_manager: WorkspaceDirManager, pool: WorkspaceProcessPool
) -> None:
    """Dogfood the dependabot.yml generator against the Cliff repo."""
    await _run_repo_action_e2e(
        kind=WorkspaceKind.repo_action_dependabot,
        template_stem="dependabot_config_generator",
        branch_name="cliff/posture/dependabot",
        params={},
        dir_manager=dir_manager,
        pool=pool,
    )
