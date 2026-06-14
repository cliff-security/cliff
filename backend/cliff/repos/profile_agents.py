"""The three Project-profile builder agents (ADR-0053 §3, Phase 1.6).

Each is an in-process Pydantic AI agent (ADR-0047) that reads the cached clone
(read-only) and emits one typed artifact. They satisfy the ``ProfileBuilder``
shape (``async (clone_dir) -> dict``) so :class:`ProfileRunner` can drive them.

Deps reuse: profile builders run on a *clone*, not a finding workspace, but the
``read`` tool is keyed on ``WorkspaceDeps.workspace_dir`` — so we reuse
``WorkspaceDeps`` with ``workspace_dir`` pointing at the clone and an empty
``finding``. That reuses the entire tool + runtime path with zero duplication
("delete before adding"); the repo metadata is threaded through the task prompt.

Read-only by design (the whole profiling tier touches nothing): the only tool is
``read``. ``PROFILE_BUILDER_TOOLS`` makes that boundary one assertable thing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools.read import read
from cliff.repos.schemas import CodeMap, RepoProfile, ThreatHistory

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.models import Model

    from cliff.repos.profile_runner import ProfileBuilder

#: Read-only — the profiling tier never edits, runs, or pushes anything.
PROFILE_BUILDER_TOOLS = (read,)

#: A profile build reads a handful of files (README, manifests, a tree sample);
#: cap requests so a weak model can't loop on the read tool.
PROFILE_REQUEST_LIMIT = 15

_PROFILER_PROMPT = """\
Profile this repository. Use the `read` tool to open its README, package \
manifest(s) (package.json, pyproject.toml, go.mod, Cargo.toml, etc.), any \
Dockerfile, and the obvious entry points. Determine: what kind of project it is \
(library / service / cli / self_hosted_app / monolith), how it is deployed and \
run, whether it is internet-facing, its main attack-surface entry points (with \
file:line where you can), and how to build and run it. Write a one-paragraph \
plain-English summary. Read sparingly — you do not need every file."""

_CODE_MAP_PROMPT = """\
Map which of this repository's code actually ships in production versus what \
does not. Use the `read` tool to inspect the directory layout and a sample of \
files. Classify path globs into: ships, test, fixture, example, docs, build, \
vendored, dead — each with a short reason. List the top-level ships_roots and \
excluded_roots. This is used to drop findings whose root cause lives only in \
non-shipping code, so be accurate about what is test/fixture/vendored."""

_THREAT_PROMPT = """\
Review this repository's security history. From any CHANGELOG, SECURITY.md, \
advisory references, or security-relevant commit messages you can `read`, list \
prior CVEs/GHSAs with their root-cause family and whether the fix addressed the \
instance or the whole class. Note the weak-spot families that recur and the \
areas of the codebase that have been historically fertile for bugs. If you find \
no history, return empty lists — do not invent issues."""


def _build_agent(model: Model, output_type: type) -> Agent:
    return Agent(
        model=model,
        output_type=output_type,
        deps_type=WorkspaceDeps,
        tools=list(PROFILE_BUILDER_TOOLS),
    )


def _make_builder(model: Model, output_type: type, prompt: str) -> ProfileBuilder:
    agent = _build_agent(model, output_type)

    async def _build(clone_dir: Path) -> dict:
        deps = WorkspaceDeps(
            workspace_id="repo-profile",
            workspace_dir=str(clone_dir),
            finding={},
        )
        result = await agent.run(
            prompt, deps=deps, usage_limits=UsageLimits(request_limit=PROFILE_REQUEST_LIMIT)
        )
        return result.output.model_dump()

    return _build


def make_repo_profiler(model: Model) -> ProfileBuilder:
    return _make_builder(model, RepoProfile, _PROFILER_PROMPT)


def make_code_map(model: Model) -> ProfileBuilder:
    return _make_builder(model, CodeMap, _CODE_MAP_PROMPT)


def make_threat_history(model: Model) -> ProfileBuilder:
    return _make_builder(model, ThreatHistory, _THREAT_PROMPT)


def make_profile_builders(model: Model) -> dict[str, ProfileBuilder]:
    """The full builder set keyed by artifact name, ready for ProfileRunner."""
    return {
        "profile": make_repo_profiler(model),
        "code_map": make_code_map(model),
        "threat": make_threat_history(model),
    }


__all__ = [
    "PROFILE_BUILDER_TOOLS",
    "PROFILE_REQUEST_LIMIT",
    "make_code_map",
    "make_profile_builders",
    "make_repo_profiler",
    "make_threat_history",
]
