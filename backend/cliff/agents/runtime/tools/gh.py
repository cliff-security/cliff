"""``gh`` tool — run the GitHub CLI with the workspace's token.

Thin wrapper over :func:`cliff.agents.runtime.tools.bash.bash`: it builds
``gh <args>`` and delegates, so the same classifier, subprocess
execution, timeout, and output-trimming apply. ``GH_TOKEN`` already lives
on ``ctx.deps.env_vars`` (the executor resolves it from the credential
vault at run time) and ``bash`` passes that env to the subprocess —
giving the agent an explicit ``gh`` affordance keeps the token out of the
model-visible command string instead of asking the model to inline it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cliff.agents.runtime.tools.bash import bash

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from cliff.agents.runtime.deps import WorkspaceDeps


async def gh(ctx: RunContext[WorkspaceDeps], args: str) -> str:
    """Run ``gh <args>`` using ``GH_TOKEN`` from the workspace env."""
    if not ctx.deps.env_vars.get("GH_TOKEN"):
        # ``bash`` would run it unauthenticated and gh would report a
        # confusing auth error; surface the real cause instead.
        return (
            "[gh: GH_TOKEN is not set for this workspace; the command would "
            "run unauthenticated. Resolve GitHub access in Settings before "
            "opening a PR.]"
        )
    return await bash(ctx, f"gh {args}")


__all__ = ["gh"]
