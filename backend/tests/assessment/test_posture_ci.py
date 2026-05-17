"""CI supply-chain posture checks (Epic 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.assessment.posture.ci_supply_chain import (
    check_actions_pinned_to_sha,
    check_trusted_action_sources,
    check_workflow_trigger_scope,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_workflow(repo: Path, name: str, body: str) -> None:
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(body)


def test_actions_pinned_passes_when_all_full_sha(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        """
name: CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@a12a3943b4bdde767164f792f33f40b04645d846
      - uses: actions/setup-node@1a4442cacd436585916779262731d5b162bc6ec7
""",
    )
    result = check_actions_pinned_to_sha(tmp_path)
    assert result.status == "pass"
    assert result.category == "ci_supply_chain"


def test_actions_pinned_fails_on_tag_reference(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n",
    )
    result = check_actions_pinned_to_sha(tmp_path)
    assert result.status == "fail"
    assert result.detail
    assert result.detail["unpinned_count"] == 1
    assert result.detail["unpinned"][0]["action"] == "actions/checkout"


def test_actions_pinned_no_workflows_passes(tmp_path: Path) -> None:
    result = check_actions_pinned_to_sha(tmp_path)
    assert result.status == "pass"
    assert result.detail == {"reason": "no_workflows"}


def test_trusted_action_sources_passes_for_first_party_publishers(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "deploy.yml",
        (
            "jobs:\n  d:\n    steps:\n"
            "      - uses: actions/checkout@abc\n"
            "      - uses: aws-actions/configure-aws-credentials@def\n"
        ),
    )
    result = check_trusted_action_sources(tmp_path)
    assert result.status == "pass"


def test_trusted_action_sources_fails_for_unknown_publisher(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "ci.yml",
        "jobs:\n  d:\n    steps:\n      - uses: random-vendor/scary-action@v1\n",
    )
    result = check_trusted_action_sources(tmp_path)
    assert result.status == "fail"
    assert result.detail["untrusted"][0]["owner"] == "random-vendor"


def test_workflow_trigger_scope_is_advisory_with_dangerous_pattern(tmp_path: Path) -> None:
    _write_workflow(
        tmp_path,
        "pr.yml",
        """
name: PR
on:
  pull_request_target:
jobs:
  validate:
    steps:
      - uses: actions/checkout@abc
        with:
          ref: ${{ github.event.pull_request.head.sha }}
""",
    )
    result = check_workflow_trigger_scope(tmp_path)
    assert result.status == "advisory"
    assert result.detail["flagged_count"] >= 1


def test_workflow_trigger_scope_passes_when_clean(tmp_path: Path) -> None:
    """Advisory by design, but pass-when-clean so a workflow with nothing to
    advise on doesn't generate a perpetually-open Issues row."""
    _write_workflow(
        tmp_path,
        "ci.yml",
        "name: CI\non: push\njobs: {}\n",
    )
    result = check_workflow_trigger_scope(tmp_path)
    assert result.status == "pass"
    assert result.detail["flagged_count"] == 0
