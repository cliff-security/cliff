"""Scanner triage synthesizer (ADR-0051 §3) — a pure function, no LLM.

The verdict for a *scanner* finding is a deterministic projection of work the
finding enricher (ADR-0040) and exposure analyzer (ADR-0042) already did. This
keeps scanner triage explainable (the proof IS the exposure evidence), $0, and
testable without a model (ADR-0050 Lane 1).

Mapping (ADR-0051 §3), evaluated **reachability-first** so a finding the
exposure analyzer reports as reachable is never closed as ``false_positive``
even when the enricher abstained — false-clearing a real finding is the
load-bearing failure (ADR-0051 §10):

    missing exposure                         → needs_review  (never a confident clear)
    not reachable / no path                  → unexploitable
    reachable + internet-facing              → real
    reachable + internal/unknown facing      → needs_review  (deployment-dependent)
    reachability undetermined, real advisory → needs_review
    reachability undetermined, no advisory   → false_positive (enricher abstention)

``needs_review`` is produced whenever confidence would fall below the
``NEEDS_REVIEW_CONFIDENCE`` threshold or exploitability is ``unknown``
(ADR-0051 §9). The threshold is a tunable constant, not a magic number frozen
in the branches.

Two fail-safes guard against shipping a confident verdict the quick read hasn't
earned (the Plan-gate bright line — a report must never carry a false positive):

1. **Speculative reachability never confirms.** The exposure analyzer's
   free-text ``reachable`` is classified hedge-aware: phrasing like "likely …
   needs verification to confirm" is *speculation*, not a confirmed reachable,
   so it maps to ``unknown`` (→ needs_review), never a confident ``real``.

2. **No-advisory-model findings defer.** ``code`` and ``secret`` findings have
   no CVE/advisory (the enricher always abstains), and for code the exposure
   analyzer reasons from the file PATH, never the file's code — so the quick
   read can't responsibly clear OR confirm them. They defer to ``needs_review``,
   which auto-escalates to the file-reading Deep dive (ADR-0052), where the
   flagged ``file:line`` is opened before any verdict. The dependency-shaped
   projection below (abstention → false_positive, reachable+facing → real)
   assumes a CVE/advisory model: applying it to code shipped fake CRITICAL
   SQL-injection ``real`` verdicts, and to a secret it would false-clear a real
   leaked credential as ``false_positive``. ``dependency`` (CVE model) and
   ``posture`` (deterministic Cliff check, real by definition) keep the
   projection.
"""

from __future__ import annotations

from typing import Any

from cliff.agents.schemas import TriageOutput, TriageVerdict

#: Below this confidence (or when exploitability is unknown) the synthesizer
#: routes to ``needs_review`` rather than a terminal verdict (ADR-0051 §9).
#: Tuned against the eval harness — see backend/tests/agents/eval.
NEEDS_REVIEW_CONFIDENCE = 0.70

#: Scanner finding types the quick read must NOT confidently judge — first-party
#: findings with no CVE/advisory model, where the dependency projection's
#: abstention + reachability semantics don't hold. They defer to the Deep dive.
#: (`dependency` keeps the projection; `posture` is a deterministic Cliff check.)
_DEFER_TYPES = frozenset({"code", "secret"})

# Confidence anchors per verdict (all confident verdicts sit at/above the
# threshold; every needs_review sits below it — see the §9 invariant test).
_CONF_REAL = 0.82
_CONF_REAL_KNOWN_EXPLOIT = 0.92
_CONF_UNEXPLOITABLE_FACING_KNOWN = 0.88
_CONF_UNEXPLOITABLE_FACING_UNKNOWN = 0.78
_CONF_FALSE_POSITIVE = 0.74
_CONF_NEEDS_REVIEW = 0.55
_CONF_MISSING_EXPOSURE = 0.40

# Free-text ``ExposureOutput.reachable`` classification. Order matters:
# negatives, then uncertainty, then affirmatives, then a conservative default.
_REACH_NEGATIVE = (
    "no path",
    "not reachable",
    "unreachable",
    "not exploitable",
    "cannot be reached",
    "no reachable path",
)
_REACH_UNCERTAIN = (
    "unlikely",
    "unknown",
    "unclear",
    "depends",
    "maybe",
    "possibl",  # possible / possibly
    "indeterminate",
    "uncertain",
)
#: Hedge / speculation markers. The exposure analyzer flagging a sink "likely
#: reachable … needs verification to confirm" has NOT confirmed reachability —
#: it has guessed. Treat such phrasing as ``unknown`` (→ needs_review), never a
#: confident reachable. ``likely`` lives here, NOT in affirmatives: "likely
#: reachable" is a probability, not a confirmation, and promoting it to a
#: confident ``real`` is exactly the false positive this guards against.
_REACH_HEDGE = (
    "likely",
    "probabl",  # probable / probably
    "suggest",  # suggests / suggesting
    "appears",
    "seems",
    "may ",  # "may be reachable" — trailing space avoids matching e.g. "mayhem"
    "might",
    "could",
    "would ",  # "would need to trace"
    "potential",
    "presum",  # presumably
    "assume",
    "needs verification",
    "need to verify",
    "needs confirmation",
    "to confirm",
    "not confirmed",
    "unverified",
    "needs analysis",
    "need to trace",
    "needs further",
    "requires verification",
    "cannot confirm",
    "unable to confirm",
)
_REACH_AFFIRMATIVE = (
    "reachable",
    "yes",
    "true",
    "confirmed",
    "direct",
    "exploitable",
)
#: Anything uncertain OR hedged is undetermined. One set, one membership pass —
#: the two source tuples stay separate only for their distinct doc-comments.
_REACH_UNKNOWN = _REACH_UNCERTAIN + _REACH_HEDGE


def _classify_reachable(reachable: str | None) -> str:
    """Map the analyzer's free-text ``reachable`` to ``yes`` / ``no`` /
    ``unknown``. An empty value means the analyzer ran but couldn't determine
    reachability → ``unknown`` (the *missing exposure* case is handled by the
    caller before this is reached).

    Uncertainty/hedging is checked FIRST — it dominates any negative or
    affirmative keyword the same text also contains. So a hedged NEGATIVE
    ("cannot confirm it is not reachable", "appears unreachable but unverified")
    is NOT confidently cleared as a no-path, and a hedged AFFIRMATIVE ("likely
    reachable … needs verification") is NOT confirmed as reachable. Only a clean,
    un-hedged statement reaches the negative/affirmative checks (the Plan-gate
    bright line: speculation never becomes a confident verdict)."""
    if not reachable:
        return "unknown"
    s = reachable.strip().lower()
    if any(k in s for k in _REACH_UNKNOWN):
        return "unknown"
    if any(k in s for k in _REACH_NEGATIVE) or s in ("no", "false", "none"):
        return "no"
    if any(k in s for k in _REACH_AFFIRMATIVE):
        return "yes"
    return "unknown"


def _enricher_abstained(enrichment: dict[str, Any] | None) -> bool:
    """True when the enricher found no public advisory substantiating a real
    vulnerability — no CVE and no CVSS score (ADR-0051 §3 abstention signal)."""
    if not enrichment:
        return True
    return not (enrichment.get("cve_ids") or []) and enrichment.get("cvss_score") is None


def synthesize_triage(
    enrichment: dict[str, Any] | None,
    exposure: dict[str, Any] | None,
    finding_type: str = "dependency",
) -> TriageOutput:
    """Project a triage verdict from recorded enricher + exposure output.

    ``finding_type`` is the scanner finding's class (``dependency`` / ``code`` /
    ``secret`` / ``posture``). ``code`` and ``secret`` findings defer to the Deep
    dive — see ``_deferred_quick_verdict`` — because they have no advisory model
    the projection can rest on; ``dependency`` and ``posture`` use the
    dependency-shaped projection below."""
    known_exploits = bool((enrichment or {}).get("known_exploits"))

    # Missing exposure entirely → never a confident clear (ADR-0051 §10).
    if exposure is None:
        return TriageOutput(
            verdict="needs_review",
            confidence=_CONF_MISSING_EXPOSURE,
            exploitability={
                "exploitable": "unknown",
                "reason": "Exposure analysis hasn't run yet — reachability is undetermined.",
            },
            checks=[
                {
                    "eyebrow": "REACHABILITY",
                    "result": "Not yet analyzed",
                    "kind": "warn",
                    "detail": "Run the exposure analyzer to determine reachability.",
                }
            ],
        )

    # First-party findings with no advisory model (`code`, `secret`) can't be
    # confidently cleared OR confirmed by the dependency-shaped projection below:
    # the enricher always abstains (no CVE), and the quick read reasons from the
    # file path, not the file's code. Defer to needs_review (→ auto-escalates to
    # the file-reading Deep dive / a human). Never a confident verdict from
    # speculation. `dependency` (CVE model) and `posture` (deterministic Cliff
    # check) keep the projection.
    if finding_type in _DEFER_TYPES:
        return _deferred_quick_verdict(finding_type, exposure)

    reachable_raw = exposure.get("reachable")
    reached = _classify_reachable(reachable_raw if isinstance(reachable_raw, str) else None)
    internet_facing = exposure.get("internet_facing")
    evidence = exposure.get("reachability_evidence")

    verdict: TriageVerdict
    confidence: float
    exploitability: dict[str, Any]

    if reached == "no":
        verdict = "unexploitable"
        confidence = (
            _CONF_UNEXPLOITABLE_FACING_KNOWN
            if internet_facing is not None
            else _CONF_UNEXPLOITABLE_FACING_UNKNOWN
        )
        exploitability = {
            "exploitable": "no",
            "reason": evidence or "The vulnerable code path is not reachable here.",
        }
    elif reached == "yes" and internet_facing is True:
        verdict = "real"
        confidence = _CONF_REAL_KNOWN_EXPLOIT if known_exploits else _CONF_REAL
        exploitability = {
            "exploitable": "yes",
            "reason": evidence
            or "Reachable from an internet-facing entrypoint by untrusted input.",
        }
    elif reached == "yes":
        # Reachable but the facing is internal/unknown — depends on deployment.
        verdict = "needs_review"
        confidence = _CONF_NEEDS_REVIEW
        exploitability = {
            "exploitable": "unknown",
            "reason": "Reachable, but whether untrusted input reaches it depends on "
            "the deployment (not internet-facing / facing unknown).",
        }
    elif _enricher_abstained(enrichment):
        # No advisory + reachability undetermined → not a real issue.
        verdict = "false_positive"
        confidence = _CONF_FALSE_POSITIVE
        exploitability = {
            "exploitable": "no",
            "reason": "No public advisory substantiates this finding.",
        }
    else:
        # A real advisory exists but reachability can't be determined → abstain.
        verdict = "needs_review"
        confidence = _CONF_NEEDS_REVIEW
        exploitability = {
            "exploitable": "unknown",
            "reason": "A real advisory, but reachability of the sink is undetermined.",
        }

    # ADR-0051 §9 — defensive override: a terminal verdict that somehow falls
    # below the threshold (or has unknown exploitability) becomes needs_review.
    if verdict in ("real", "unexploitable") and (
        confidence < NEEDS_REVIEW_CONFIDENCE
        or exploitability.get("exploitable") == "unknown"
    ):
        verdict = "needs_review"

    reachability = _build_reachability(reached, evidence)
    checks = _build_checks(reached, internet_facing, known_exploits, enrichment, evidence)

    return TriageOutput(
        verdict=verdict,
        confidence=confidence,
        reachability=reachability,
        exploitability=exploitability,
        checks=checks,
    )


def _deferred_quick_verdict(finding_type: str, exposure: dict[str, Any]) -> TriageOutput:
    """Verdict for a finding the quick read can't responsibly judge (``code`` /
    ``secret``): defer to the Deep dive.

    These are first-party findings with no advisory model, so the
    dependency-shaped projection (abstention → false_positive, reachable+facing
    → real) doesn't fit — applying it false-clears real secrets and fake-confirms
    speculative code reachability. Return ``needs_review``, which auto-escalates
    to the file-reading Deep dive (ADR-0052 / ``decide_escalation``); when no Deep
    dive can run, the honest "needs your review" stands rather than a fabricated
    verdict. The analyzer's hunch is preserved as context, never promoted.
    """
    if finding_type == "secret":
        reason = (
            "A flagged secret needs review to confirm it's a true exposure — not a "
            "placeholder, test fixture, or already-rotated value. The quick read "
            "can't clear it."
        )
        check_result = "Needs your review"
        detail_default = "A potential secret was flagged — escalated for review."
    else:  # code / SAST
        reason = (
            "Confirming whether untrusted input reaches this code requires reading "
            "the flagged line — deferred to deep analysis (the quick read reasons "
            "from the file path, not the code)."
        )
        check_result = "Needs a code read"
        detail_default = (
            "The flagged line wasn't opened — escalated for a file-level trace "
            "before any verdict."
        )
    evidence = exposure.get("reachability_evidence")
    reachable_raw = exposure.get("reachable")
    hint = evidence or (reachable_raw if isinstance(reachable_raw, str) else None)
    return TriageOutput(
        verdict="needs_review",
        confidence=_CONF_NEEDS_REVIEW,
        exploitability={"exploitable": "unknown", "reason": reason},
        checks=[
            {
                "eyebrow": "REACHABILITY",
                "result": check_result,
                "kind": "warn",
                "detail": hint or detail_default,
            }
        ],
    )


def _build_reachability(reached: str, evidence: str | None) -> dict[str, Any] | None:
    if reached == "no":
        return {"reached": False, "path": [], "summary": evidence or "No path found."}
    if reached == "yes":
        return {"reached": True, "path": [], "summary": evidence}
    return None  # undetermined — no reachability block to render


def _build_checks(
    reached: str,
    internet_facing: bool | None,
    known_exploits: bool,
    enrichment: dict[str, Any] | None,
    evidence: str | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if reached == "no":
        checks.append({
            "eyebrow": "REACHABILITY", "result": "No path found", "kind": "pass",
            "detail": evidence or "The vulnerable function is never called from your code.",
        })
    elif reached == "yes":
        checks.append({
            "eyebrow": "REACHABILITY", "result": "Reachable", "kind": "fail",
            "detail": evidence or "Your code reaches the vulnerable function.",
        })
    else:
        checks.append({
            "eyebrow": "REACHABILITY", "result": "Undetermined", "kind": "warn",
            "detail": evidence or "Reachability could not be determined.",
        })

    if internet_facing is True:
        checks.append({
            "eyebrow": "NETWORK EXPOSURE", "result": "Internet-facing", "kind": "fail",
            "detail": "Untrusted input can reach this component.",
        })
    elif internet_facing is False:
        checks.append({
            "eyebrow": "NETWORK EXPOSURE", "result": "Internal only", "kind": "pass",
            "detail": "Not exposed to the public internet.",
        })
    else:
        checks.append({
            "eyebrow": "NETWORK EXPOSURE", "result": "Unknown", "kind": "warn",
            "detail": "Network exposure depends on the deployment.",
        })

    if known_exploits:
        checks.append({
            "eyebrow": "EXPLOIT MATURITY", "result": "Known exploit", "kind": "fail",
            "detail": (enrichment or {}).get("exploit_details")
            or "A public exploit exists for this advisory.",
        })

    if _enricher_abstained(enrichment):
        checks.append({
            "eyebrow": "ADVISORY", "result": "No matching advisory", "kind": "info",
            "detail": "No CVE/CVSS was found to substantiate this finding.",
        })

    return checks


__all__ = ["NEEDS_REVIEW_CONFIDENCE", "synthesize_triage"]
