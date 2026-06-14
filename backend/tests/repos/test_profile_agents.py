"""Profile-builder agents — shape + read-only boundary + end-to-end with TestModel.

Keyless: drives the agents with TestModel (no real LLM). Verdict quality is the
key-gated eval, later. These assert the builders are read-only, satisfy the
ProfileBuilder shape, and return validated artifact dicts.
"""

from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from cliff.agents.runtime.tools import bash, edit, gh, read, webfetch
from cliff.repos.profile_agents import (
    PROFILE_BUILDER_TOOLS,
    make_code_map,
    make_profile_builders,
    make_repo_profiler,
    make_threat_history,
)
from cliff.repos.schemas import CodeMap, RepoProfile, ThreatHistory


def test_profile_builders_are_read_only():
    """The whole profiling tier touches nothing — the only tool is read."""
    assert (read,) == PROFILE_BUILDER_TOOLS
    for forbidden in (bash, edit, gh, webfetch):
        assert forbidden not in PROFILE_BUILDER_TOOLS


@pytest.fixture
def clone(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    (d / "README.md").write_text("# Acme web\nA self-hosted web service.\n")
    (d / "pyproject.toml").write_text("[project]\nname='acme'\n")
    return d


async def test_repo_profiler_returns_valid_profile(clone):
    builder = make_repo_profiler(TestModel(custom_output_args={"kind": "service"}))
    out = await builder(clone)
    # Round-trips through the schema (defaults filled, extra allowed).
    parsed = RepoProfile.model_validate(out)
    assert parsed.kind == "service"


async def test_code_map_returns_valid_map(clone):
    builder = make_code_map(
        TestModel(custom_output_args={"ships_roots": ["src/**"], "excluded_roots": ["tests/**"]})
    )
    out = await builder(clone)
    parsed = CodeMap.model_validate(out)
    assert parsed.ships_roots == ["src/**"]
    assert parsed.excluded_roots == ["tests/**"]


async def test_threat_history_returns_valid_history(clone):
    builder = make_threat_history(TestModel(custom_output_args={"recurring_families": ["ssti"]}))
    out = await builder(clone)
    parsed = ThreatHistory.model_validate(out)
    assert parsed.recurring_families == ["ssti"]


async def test_threat_history_defaults_to_empty(clone):
    builder = make_threat_history(TestModel(custom_output_args={}))
    out = await builder(clone)
    parsed = ThreatHistory.model_validate(out)
    assert parsed.prior_issues == []


def test_make_profile_builders_has_all_three():
    builders = make_profile_builders(TestModel())
    assert set(builders) == {"profile", "code_map", "threat"}
    assert all(callable(b) for b in builders.values())
