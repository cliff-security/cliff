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
* only categories **proven noise-only** against the 2,229-finding gold corpus
  are auto-cleared — ``test``, ``fixture``, ``example``, ``docs``.  ``build``
  and ``vendored`` are intentionally excluded: CI/CD workflow files
  (``.github/workflows/``) are a real security surface (workflow injection,
  secret theft) and the gold dataset labels them ``your-call``, not noise;
  vendored third-party code often ships and a vulnerability there can be real.
  Both categories are left to the LLM Deep dive;
* matching is segment/boundary-anchored — loose globs (``*test*``) and
  match-everything globs (``**``, ``*``, ``**/*``) are SKIPPED, never cleared
  on; the finding falls through to the Deep dive (safe);
* bare directory names (no separator, no wildcard) match that segment anywhere
  in the path (``"tests"`` matches ``app/tests/x.py``), segment-anchored;
  explicit globs are honored as written;
* default = return ``None`` (the caller falls through to the Deep dive).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from cliff.agents.schemas import TriageCheck, TriageOutput, TriageProvenance

#: Categories the resolver may clear on. ``ships``/``dead`` are deliberately excluded.
#: ``build`` and ``vendored`` are also excluded — see module docstring for rationale.
NONSHIP_CATEGORIES = frozenset({"test", "fixture", "example", "docs"})

_CONF_CODEMAP_CLEAR = 0.9

_BOUNDARY = set("/._-")

#: Universal non-ship DIRECTORY segments — gold-validated noise-only over the 2,229
#: corpus (tests/=824, examples/=77, e2e/=11, fixtures/=9, docs/=4, benchmarks/=3 …).
#: Matched as exact path segments (never substring): "tests" matches app/tests/x.py,
#: not app/latest/x.py.
_BUILTIN_DIR_SEGMENTS = frozenset({
    "tests", "test", "__tests__", "spec", "specs", "e2e", "examples", "example",
    "samples", "sample", "fixtures", "fixture", "testdata", "docs", "doc",
    "benchmarks", "bench", "__mocks__", "mocks",
})

#: Universal non-ship BASENAME globs — matched on the :line-stripped basename. Each
#: is boundary-anchored (no within-word substring match): test_*.py matches
#: test_login.py, not testimony.py.
_BUILTIN_BASENAME_GLOBS = (
    "*.test.js", "*.test.ts", "*.test.jsx", "*.test.tsx", "*.spec.js", "*.spec.ts",
    "*_test.py", "*_test.go", "*_test.js", "*_test.ts", "test_*.py", "conftest.py",
    "*.stories.js", "*.stories.ts", "test.py",
)

_LINE_SUFFIX = re.compile(r":\d+(?::\d+)?$")


def _strip_line_suffix(path: str) -> str:
    """Strip a trailing scanner ``:line`` / ``:line:col`` (e.g. ``x.test.ts:671`` →
    ``x.test.ts``) so basename matching works on Snyk/semgrep locations."""
    return _LINE_SUFFIX.sub("", path)


def _match_builtin(path: str) -> str | None:
    """If *path* (already :line-stripped) is a universal non-ship location, return a
    short receipt label; else ``None``. Dir segments matched exactly; basenames via
    the anchored glob matcher."""
    parts = path.strip("/").split("/")
    for seg in parts[:-1]:  # directory components only — never the file itself
        if seg in _BUILTIN_DIR_SEGMENTS:
            return f"{seg}/ (non-ship directory)"
    base = parts[-1]
    for glob in _BUILTIN_BASENAME_GLOBS:
        if _glob_to_regex(glob).match(base):
            return f"{glob} (non-ship file)"
    return None


def _code_map_says_ships(path: str, code_map: dict[str, Any] | None) -> bool:
    """Whether the repo profile classifies *path* as SHIPPING code — vetoes a
    built-in clear (the rare repo that packages examples/ etc.). Defensive against
    a corrupt code_map (non-list / non-dict / non-str)."""
    if not code_map:
        return False
    for root in code_map.get("ships_roots") or []:
        if isinstance(root, str) and root and _path_matches(path, root):
            return True
    classified = code_map.get("classified")
    if isinstance(classified, list):
        for entry in classified:
            if not isinstance(entry, dict) or entry.get("category") != "ships":
                continue
            glob = entry.get("glob")
            if isinstance(glob, str) and glob and _glob_is_safe(glob) and _path_matches(path, glob):
                return True
    return False


def _glob_is_safe(glob: str) -> bool:
    """Reject loose globs that could substring-match inside a path segment.

    A single ``*``/``?`` directly against an alphanumeric char (e.g. ``*test*``)
    lets the wildcard absorb part of a word, so ``*test*`` matches ``latest.py``.
    We only honor wildcards bounded by a separator (``/ . _ -``), a segment edge,
    or another wildcard. A glob with no literal alphanumeric token (``**``, ``*``)
    is match-everything and is also rejected. An unsafe glob is skipped, never
    cleared on — the finding falls through to the Deep dive (safe)."""
    g = glob.strip("/")
    if not any(c.isalnum() for c in g):
        return False
    for i, ch in enumerate(g):
        if ch in "*?":
            prev = g[i - 1] if i > 0 else ""
            nxt = g[i + 1] if i + 1 < len(g) else ""
            left_ok = prev == "" or prev in _BOUNDARY or prev in "*?"
            right_ok = nxt == "" or nxt in _BOUNDARY or nxt in "*?"
            if not (left_ok and right_ok):
                return False
    return True


@lru_cache(maxsize=1024)
def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Anchored, segment-aware glob → regex. ``**`` spans directories, ``*`` stays
    within a path segment, ``?`` is one non-separator char.

    Consecutive directory-spanning segments (``**/**/*.py``) are collapsed to a
    single ``**/`` before compilation to avoid stacked ``(?:[^/]+/)*`` groups
    that can backtrack catastrophically on deep non-matching paths.
    """
    g = glob.strip("/")
    # Collapse repeated **/ (e.g. **/**/ → **/) — safe because repeating
    # "match any number of segments" has no extra effect; matching is unchanged.
    g = re.sub(r"(?:\*\*/){2,}", "**/", g)
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
    # A bare directory name (no separator, no wildcard) → match that segment
    # anywhere in the path (so "tests" covers "app/tests/x.py"), segment-anchored.
    if "/" not in g and "*" not in g and "?" not in g:
        return bool(_glob_to_regex(f"**/{g}/**").match(p))
    return False


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
    classified = code_map.get("classified")
    if not isinstance(classified, list):
        return None
    for entry in classified:
        if not isinstance(entry, dict):
            continue
        category = entry.get("category")
        if not isinstance(category, str):
            # A non-str category can't match any NONSHIP_CATEGORIES member; a
            # non-hashable value (list/dict) would raise TypeError on `in` — skip it.
            continue
        glob = entry.get("glob")
        safe = (
            category in NONSHIP_CATEGORIES
            and isinstance(glob, str)
            and glob
            and _glob_is_safe(glob)
        )
        if safe and _path_matches(path, glob):
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


__all__ = ["NONSHIP_CATEGORIES", "_glob_is_safe", "resolve_by_code_map"]
