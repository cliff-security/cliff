"""Unit tests for the RepoKnowledge declared-consumption access layer (ADR-0053 §5)."""

from __future__ import annotations

import pytest

from cliff.repos.knowledge import load_repo_knowledge
from cliff.repos.repo_dir_manager import RepoDirManager

RID = "repo123"


@pytest.fixture
def mgr(tmp_path):
    m = RepoDirManager(tmp_path / "repos")
    m.write_artifact(RID, "profile", {"kind": "service"})
    m.write_artifact(RID, "code_map", {"ships_roots": ["src/**"]})
    m.write_artifact(RID, "threat", {"prior_issues": []})
    return m


def test_loads_only_declared_sections(mgr):
    k = load_repo_knowledge(mgr, RID, ["profile"])
    assert k.profile == {"kind": "service"}
    # Undeclared sections are not loaded — the agent doesn't pay for them.
    assert k.code_map is None
    assert k.threat is None


def test_loads_all_declared(mgr):
    k = load_repo_knowledge(mgr, RID, ["profile", "code_map", "threat"])
    assert k.profile and k.code_map and k.threat


def test_unknown_section_rejected(mgr):
    with pytest.raises(ValueError, match="Unknown profile section"):
        load_repo_knowledge(mgr, RID, ["profile", "bogus"])


def test_declared_but_unbuilt_is_none(tmp_path):
    empty = RepoDirManager(tmp_path / "repos")
    k = load_repo_knowledge(empty, RID, ["profile", "code_map"])
    # Declared but never built → None; agents must degrade, not assume.
    assert k.profile is None
    assert k.code_map is None


def test_clone_dir_opt_in(mgr):
    without = load_repo_knowledge(mgr, RID, ["profile"])
    assert without.clone_dir is None

    with_clone = load_repo_knowledge(mgr, RID, ["profile"], include_clone=True)
    assert with_clone.clone_dir is not None
    assert with_clone.clone_dir.name == "repo"
