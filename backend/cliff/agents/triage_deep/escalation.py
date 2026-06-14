"""The escalation gate + deep-dive budget (ADR-0052 §1).

Decides whether a Quick-read verdict is worth a Deep dive. The load-bearing cost
control: severity *alone* never escalates — it needs uncertainty
(``needs_review``) or stakes-plus-remaining-budget — so a flood of high-severity
dependency CVEs can't quietly turn the cheap default into an all-deep-dive run.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Deep dives allowed per assessment before high-stakes findings queue for an
#: explicit user-triggered dive (eval-tuned, not frozen).
DEFAULT_DEEP_DIVE_BUDGET = 10


@dataclass(frozen=True)
class EscalationDecision:
    escalate: bool
    reason: str


def is_high_stakes(finding: dict) -> bool:
    """High/critical severity, internet-facing, or a crown-jewel asset."""
    severity = str(finding.get("raw_severity") or finding.get("severity") or "").lower()
    if severity in ("critical", "high"):
        return True
    if finding.get("internet_facing") is True:
        return True
    return bool(finding.get("crown_jewel"))


def decide_escalation(
    verdict: str,
    finding: dict,
    *,
    budget_remaining: int,
    source: str = "scanner",
) -> EscalationDecision:
    """Whether to run the Deep dive after the Quick read.

    Reports always escalate (no cheap projection to trust). Otherwise: escalate
    on uncertainty always; on stakes only while deep-dive budget remains.
    """
    if source == "report":
        return EscalationDecision(True, "report — always deep dive")
    if verdict == "needs_review":
        return EscalationDecision(True, "uncertain (needs_review)")
    if is_high_stakes(finding):
        if budget_remaining > 0:
            return EscalationDecision(True, "high-stakes — produce evidence")
        return EscalationDecision(
            False, "high-stakes but deep-dive budget exhausted — queue for manual"
        )
    return EscalationDecision(False, "clear and low-stakes — cheap verdict stands")


__all__ = [
    "DEFAULT_DEEP_DIVE_BUDGET",
    "EscalationDecision",
    "decide_escalation",
    "is_high_stakes",
]
