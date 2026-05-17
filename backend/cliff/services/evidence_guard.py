"""Deterministic guards over Evidence Collector output (Q01-B11, B13).

The ``evidence_collector`` agent classifies fix safety and reports the
package's current version as free-text — and both drift under model and
concurrency variance: a 3-major-version upgrade gets labelled
``safe_bump``, ``current_version`` comes back ``null``.

But for a dependency finding Cliff already *knows* the authoritative
versions — the scanner recorded the installed version and the fix version
on the finding's ``raw_payload``. ``guard_evidence_output`` reconciles the
agent's output against those scanner facts:

* **B11** — a major-version jump (e.g. ``4.x -> 7.x``) can never be a
  ``safe_bump``. If the agent labelled it one, force ``breaking_change``
  and explain why in ``fix_safety_reasoning``.
* **B13** — ``current_version`` must not be ``null`` when the scanner
  recorded the installed version; backfill it.

Pure, synchronous, never raises. Returns the corrections made so the
caller can log them. Non-dependency findings (no scanner version data) are
left untouched.
"""

from __future__ import annotations

import re

_INT_RE = re.compile(r"\d+")
# Trivy may list several fix versions in one string.
_SPLIT_RE = re.compile(r"[,;]")


def _major(version: object) -> int | None:
    """Return the leading major-version integer of *version*, or ``None``."""
    if not isinstance(version, str):
        return None
    match = _INT_RE.search(version)
    return int(match.group()) if match else None


def _min_fixed_major(fixed_version: object) -> int | None:
    """The smallest major among Trivy's (possibly multi-valued) fix versions.

    Trivy reports e.g. ``"4.19.2, 5.0.0-beta.3"`` — the lowest major is the
    least-breaking upgrade actually available, so that is the one to
    compare the installed version against.
    """
    if not isinstance(fixed_version, str):
        return None
    majors = [
        m
        for m in (_major(part) for part in _SPLIT_RE.split(fixed_version))
        if m is not None
    ]
    return min(majors) if majors else None


def guard_evidence_output(
    structured_output: object, finding: object
) -> list[str]:
    """Reconcile ``evidence_collector`` output against scanner facts.

    Mutates *structured_output* in place. Returns a human-readable note for
    every correction applied — an empty list means nothing changed.
    """
    if not isinstance(structured_output, dict):
        return []
    raw = {}
    if isinstance(finding, dict) and isinstance(
        finding.get("raw_payload"), dict
    ):
        raw = finding["raw_payload"]
    installed = raw.get("version")
    fixed = raw.get("fixed_version")
    corrections: list[str] = []

    # B13 — backfill current_version from the scanner's installed version.
    if not structured_output.get("current_version") and isinstance(
        installed, str
    ):
        structured_output["current_version"] = installed
        corrections.append(
            f"current_version backfilled from scanner data: {installed}"
        )

    # B11 — a major-version jump is never a safe_bump.
    installed_major = _major(installed)
    fixed_major = _min_fixed_major(fixed)
    if (
        installed_major is not None
        and fixed_major is not None
        and fixed_major > installed_major
        and structured_output.get("fix_safety") == "safe_bump"
    ):
        delta = fixed_major - installed_major
        structured_output["fix_safety"] = "breaking_change"
        note = (
            f"fix_safety corrected safe_bump -> breaking_change: the fix "
            f"requires a {delta}-major version jump ({installed} -> {fixed}), "
            "which is not a drop-in upgrade."
        )
        existing = structured_output.get("fix_safety_reasoning")
        prefixed = f"[Cliff semver guard] {note}"
        structured_output["fix_safety_reasoning"] = (
            f"{existing}\n\n{prefixed}"
            if isinstance(existing, str) and existing.strip()
            else prefixed
        )
        corrections.append(note)

    return corrections


__all__ = ["guard_evidence_output"]
