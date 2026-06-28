"""Deterministic code_map resolver (SP2 / ADR-0052 extension).

Clears a finding as ``false_positive`` BEFORE the LLM Deep dive when its file
path matches a non-ship glob the repo profiler already classified in
``code_map`` (``cliff/repos/schemas.py``). Pure — no LLM, no network, no
filesystem — so it is keyless and CI-testable, and it makes the profile's
repo-aware ship/no-ship knowledge a reliable deterministic check instead of a
per-finding LLM hope.

Safety (never clear a real finding):
* clears ONLY on a ``classified`` glob whose ``category`` is a conservative
  non-ship kind (``ships`` and ``dead`` never clear);
* anchored, segment-aware glob match (never substring);
* default = return ``None`` (the caller falls through to the Deep dive).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from cliff.agents.schemas import TriageCheck, TriageOutput, TriageProvenance

#: Categories the resolver may clear on. ``ships``/``dead`` are deliberately excluded.
NONSHIP_CATEGORIES = frozenset({"test", "fixture", "example", "docs", "build", "vendored"})

_CONF_CODEMAP_CLEAR = 0.9


@lru_cache(maxsize=1024)
def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Anchored, segment-aware glob → regex. ``**`` spans directories, ``*`` stays
    within a path segment, ``?`` is one non-separator char."""
    g = glob.strip("/")
    out: list[str] = []
    i = 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _path_matches(path: str, glob: str) -> bool:
    p = path.strip("/")
    g = glob.strip("/")
    if not p or not g:
        return False
    if _glob_to_regex(g).match(p):
        return True
    # Treat a bare directory glob ("tests", "examples/foo") as a prefix: match
    # any file under it. (A finding path is always a file, never the dir itself.)
    return bool(_glob_to_regex(g.rstrip("/") + "/**").match(p))


def resolve_by_code_map(
    finding: dict[str, Any], code_map: dict[str, Any] | None
) -> TriageOutput | None:
    """Return a ``false_positive`` verdict if *finding*'s path is in non-ship code
    per *code_map*; else ``None`` (fall through to the Deep dive)."""
    if not code_map:
        return None
    path = (finding.get("location") or "").strip()
    if not path:
        return None
    for entry in code_map.get("classified") or []:
        category = entry.get("category")
        glob = entry.get("glob")
        if category in NONSHIP_CATEGORIES and glob and _path_matches(path, glob):
            reason = entry.get("reason") or "non-shipping code"
            return TriageOutput(
                verdict="false_positive",
                confidence=_CONF_CODEMAP_CLEAR,
                checks=[
                    TriageCheck(
                        eyebrow="Out of scope",
                        result=f"{category} code — does not ship to production",
                        kind="pass",
                        detail=f"path {path!r} matches code_map glob {glob!r}: {reason}",
                    )
                ],
                provenance=TriageProvenance(
                    steps_run=["code_map_resolver"],
                    exit_stage="code_map_resolver",
                    escalated=False,
                ),
            )
    return None


__all__ = ["NONSHIP_CATEGORIES", "resolve_by_code_map"]
