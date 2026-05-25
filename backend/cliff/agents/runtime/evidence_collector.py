"""Evidence Collector — Pydantic AI runtime (ADR-0043).

Pre-migration this agent ran through the OpenCode tool-use path and
shelled out to ``git clone`` / ``grep`` to enumerate affected files. In
the Pydantic AI no-tools migration (PR #1) it becomes a knowledge-only
agent: it reads the finding row + prior agent context and infers which
files / lock files / manifests are affected from the scanner output and
its training-data familiarity with the package ecosystem. Real
repo-walking returns later as a tool agent if the gap matters in beta.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.schemas import EvidenceOutput

if TYPE_CHECKING:
    from pydantic_ai.models import Model


SYSTEM_PROMPT = """\
You are a vulnerability evidence collector. Your job is to identify all \
files likely affected by the vulnerability, map the dependency chain, \
and determine the safest fix approach — so the remediation planner and \
executor know exactly what to change.

## Your task

Without browsing the repository, infer the concrete evidence about \
where this vulnerability exists and what impact fixing it will have. \
Combine: the finding row in the user message, any prior enrichment / \
exposure context, and your knowledge of the package ecosystem.

For dependency findings, list every lock file and manifest a project of \
this kind is conventionally expected to carry that pins the affected \
package (e.g. ``package.json`` + ``package-lock.json`` for npm; \
``pyproject.toml`` + ``uv.lock`` for Python; ``go.mod`` + ``go.sum`` \
for Go). For source-code findings, cite the conventional file path \
indicated by the scanner's ``asset_label`` or ``description``.

Assess fix safety:

- **safe_bump** — Version bump with no API changes (most dependency CVEs)
- **breaking_change** — New version has API changes that may break callers
- **needs_migration** — Requires code changes beyond a version bump
- **code_fix** — The vulnerability is in the project's own code, not a \
dependency

## Completeness rules

Every field must be a genuine best-effort answer — an empty \
``affected_files`` or a null ``current_version`` is a worse outcome \
than an imperfect one.

- ``current_version``: the version currently in the repo. The finding's \
asset label already carries it (e.g. ``minimist@1.2.5`` -> ``1.2.5``) — \
never return null for a dependency finding.
- ``affected_files``: for a dependency finding the manifest and lock \
files that pin the package (``package.json``, ``package-lock.json``, \
``yarn.lock``, …) are always affected — list them rather than \
returning an empty array.
- ``fix_safety``: a major-version jump (e.g. 4.x -> 7.x) is \
``breaking_change`` or worse — never ``safe_bump``.
"""


def build_agent(model: Model) -> Agent[WorkspaceDeps, EvidenceOutput]:
    """Construct the evidence collector Pydantic AI agent for *model*."""
    return Agent(
        model=model,
        output_type=EvidenceOutput,
        system_prompt=SYSTEM_PROMPT,
        deps_type=WorkspaceDeps,
    )


__all__ = ["SYSTEM_PROMPT", "build_agent"]
