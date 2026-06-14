"""Deep dive evaluators (ADR-0052 §Evaluation / ADR-0050).

"Code first, judge last" — every gate here is deterministic. The two
zero-tolerance HARD gates are the whole point of the eval:

* **false-clear** — clearing a finding the golden labels ``real`` is the single
  user-harmful failure (asymmetric, mirrors ADR-0046/0051).
* **citation grounding** — every cited ``file:line`` in the verdict must resolve
  in the repo; a path that points at code that doesn't exist is a fabrication,
  checkable with code, no judge.

Plus the read-only **tool boundary** (static) and the graded **verdict match**.
The fuzzier metrics (path precision, plausibility) are advisory / live-lane only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# A parseable "path/to/file.ext" or "path/to/file.ext:NN" citation. Prose and
# bare symbols don't match (they're skipped — only real file:line refs grade).
_CITATION = re.compile(r"^([\w./\-]+\.\w+)(?::(\d+))?$")

_CLEARED_VERDICTS = frozenset({"false_positive", "unexploitable"})


def check_false_clear(verdict: str, golden: str | None) -> tuple[bool, str]:
    """HARD (zero-tolerance): never clear a finding the golden labels ``real``."""
    if golden == "real" and verdict in _CLEARED_VERDICTS:
        return False, f"FALSE-CLEAR: golden=real but verdict={verdict!r}"
    return True, "no false-clear"


def _iter_citations(triage: dict[str, Any]) -> list[str]:
    """Every ``file:line`` the verdict cites as load-bearing evidence."""
    cites: list[str] = []
    reach = triage.get("reachability") or {}
    for node in reach.get("path") or []:
        if node.get("detail"):
            cites.append(str(node["detail"]))
    plan = triage.get("exploit_plan") or {}
    for hyp in plan.get("hypotheses") or []:
        if hyp.get("reached_sink"):
            cites.append(str(hyp["reached_sink"]))
    for check in triage.get("checks") or []:
        # The disproof guard_location / rule_out kill_evidence (a CLEAR verdict's
        # load-bearing citation) lands here as a bare ``file:line`` — often with no
        # ``/`` (e.g. ``auth.py:10``). Extract every detail and let the file:line
        # regex in check_citation_grounding decide; prose simply won't match.
        if check.get("detail"):
            cites.append(str(check["detail"]))
    return cites


def check_citation_grounding(triage: dict[str, Any], repo_dir: Path) -> tuple[bool, str]:
    """HARD: every cited ``file:line`` must resolve in the staged repo.

    A citation that doesn't parse as a file path is skipped (prose isn't a
    fabrication). A parseable one pointing at a missing file — or a line past the
    file's end — fails.
    """
    repo = Path(repo_dir)
    bad: list[str] = []
    for raw in _iter_citations(triage):
        m = _CITATION.match(raw.strip())
        if not m:
            continue
        rel, line = m.group(1), m.group(2)
        target = repo / rel
        # A citation must point INSIDE the staged repo. An absolute path or `..`
        # traversal that escapes repo_dir is a fabrication, not a resolving file —
        # never let it pass the gate by matching something on the host.
        try:
            target.resolve().relative_to(repo.resolve())
        except ValueError:
            bad.append(f"{raw} (escapes repo)")
            continue
        if not target.is_file():
            bad.append(f"{raw} (file not found)")
            continue
        if line:
            try:
                n_lines = len(target.read_text(errors="replace").splitlines())
            except OSError:
                continue
            if int(line) < 1 or int(line) > n_lines:
                bad.append(f"{raw} (line {line} out of range 1..{n_lines})")
    if bad:
        return False, "fabricated citation(s): " + "; ".join(bad)
    return True, "all cited file:line resolve"


def check_tool_boundary() -> tuple[bool, str]:
    """HARD (static): the Deep dive's tool surface stayed read-only."""
    from cliff.agents.triage_deep.agents import DEEP_DIVE_TOOLS

    names = {getattr(t, "__name__", str(t)) for t in DEEP_DIVE_TOOLS}
    if names != {"read", "grep"}:
        return False, f"deep dive tool surface is not read-only: {sorted(names)}"
    return True, "read-only (read, grep)"


def check_verdict_match(verdict: str, golden: str | None) -> tuple[bool, str]:
    """GRADED: exact verdict match against the golden label."""
    if golden is None:
        return True, "no verdict expectation"
    return verdict == golden, f"verdict {verdict!r} vs golden {golden!r}"


__all__ = [
    "check_citation_grounding",
    "check_false_clear",
    "check_tool_boundary",
    "check_verdict_match",
]
