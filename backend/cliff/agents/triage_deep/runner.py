"""DeepDiveRunner — orchestrates the escalation-gated Deep dive (ADR-0052 §2).

Linear backbone with fail-cheap early exits, the two panels at their stages, and
final TriageOutput assembly. The five stages are injected (default: the real
agents), so every exit path is unit-tested without a model. Model tiers (cheap
for gather/rule_out, strong for trace/plan, judge for challenge) come from
``build_tier_models``.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.model_tiers import resolve_tier_model_ids
from cliff.agents.schemas import (
    Challenge,
    ExploitPlan,
    TriageCheck,
    TriageExploitability,
    TriageOutput,
    TriageProvenance,
    TriageReachability,
    TriageReachabilityNode,
)
from cliff.agents.triage_deep.agents import (
    run_gather_facts,
    run_plan_exploit,
    run_rule_out,
    run_trace_path,
)
from cliff.agents.triage_deep.challenge import run_challenge_panel

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from pydantic_ai.models import Model

_STEP_TIER = {
    "gather_facts": "cheap",
    "rule_out": "cheap",
    "trace_path": "strong",
    "plan_exploit": "strong",
    "challenge": "judge",
}

# Confidence anchors (ADR-0052; tuned against the eval, not frozen).
_CONF_KILL = 0.85
_CONF_DISPROOF = 0.8
_CONF_HARDENING = 0.7
_CONF_REAL = 0.85
_CONF_UNKNOWN = 0.5


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _deps(clone_dir: Path | str, finding: dict, prior: dict[str, Any]) -> WorkspaceDeps:
    return WorkspaceDeps(
        workspace_id="triage-deep",
        workspace_dir=str(clone_dir),
        finding=finding,
        prior_context={k: v for k, v in prior.items() if v is not None},
    )


def _map_reach(reach: dict) -> TriageReachability:
    """DeepReachability dict -> the TriageReachability the shipped UI renders."""
    nodes: list[TriageReachabilityNode] = []
    for n in reach.get("path", []) or []:
        loc = n.get("file") or ""
        if n.get("line"):
            loc = f"{loc}:{n['line']}"
        nodes.append(
            TriageReachabilityNode(
                label=n.get("symbol") or n.get("file") or "node",
                detail=loc or None,
                kind=n.get("role"),
            )
        )
    return TriageReachability(reached=reach.get("reached") == "yes", path=nodes)


def _kill_corroborated(ro: dict, facts: dict, repo_knowledge: dict) -> bool:
    """Whether a rule_out kill is backed by a structural signal (ADR-0052).

    Only ``duplicate_of_known`` (a matching prior issue in the threat history)
    and ``root_cause_in_nonship_code`` (a root-cause file matching an excluded
    code-map glob) can terminally clear at the cheap gate. Every other kill class
    requires a code-safety *judgement* — which must come from trace_path's
    disproof, not the cheap gate — so it is not honored here.
    """
    kill_class = ro.get("kill_class")
    if kill_class == "duplicate_of_known":
        return bool((repo_knowledge.get("threat") or {}).get("prior_issues"))
    if kill_class == "root_cause_in_nonship_code":
        excluded = (repo_knowledge.get("code_map") or {}).get("excluded_roots") or []
        files = [c.get("file", "") for c in (facts.get("root_cause_candidates") or [])]
        return any(fnmatch.fnmatch(f, pat) for f in files for pat in excluded)
    return False


@dataclass(frozen=True)
class DeepDiveStages:
    gather: Callable[[WorkspaceDeps, Any], Awaitable[dict]] = run_gather_facts
    rule_out: Callable[[WorkspaceDeps, Any], Awaitable[dict]] = run_rule_out
    trace: Callable[[WorkspaceDeps, Any], Awaitable[dict]] = run_trace_path
    plan: Callable[[WorkspaceDeps, Any], Awaitable[dict]] = run_plan_exploit
    challenge: Callable[[WorkspaceDeps, Any, str], Awaitable[Challenge]] = run_challenge_panel


def build_tier_models(env: dict[str, str], model_full_id: str) -> dict[str, Model]:
    """Build the {cheap, strong, judge} Model map from the canonical AI state."""
    from cliff.agents.runtime.provider import build_model

    return {
        tier: build_model(env, mid) for tier, mid in resolve_tier_model_ids(model_full_id).items()
    }


class DeepDiveRunner:
    def __init__(
        self,
        models: dict[str, Any],
        *,
        stages: DeepDiveStages | None = None,
    ) -> None:
        self._models = models
        self._stages = stages or DeepDiveStages()

    async def run(
        self,
        *,
        finding: dict,
        repo_knowledge: dict,
        clone_dir: Path | str,
        enrichment: dict | None = None,
        exposure: dict | None = None,
        traced_sha: str | None = None,
    ) -> TriageOutput:
        """Run the Deep dive, degrading to ``needs_review`` if a stage exhausts
        its request budget — never crash, never a false clear."""
        def incomplete(reason: str) -> TriageOutput:
            return TriageOutput(
                verdict="needs_review",
                confidence=0.3,
                provenance=TriageProvenance(exit_stage="incomplete", escalated=True),
                checks=[TriageCheck(eyebrow="Incomplete", result=reason, kind="info")],
            )

        try:
            return await self._run(
                finding=finding,
                repo_knowledge=repo_knowledge,
                clone_dir=clone_dir,
                enrichment=enrichment,
                exposure=exposure,
                traced_sha=traced_sha,
            )
        except UsageLimitExceeded:
            return incomplete("Analysis hit the request budget")
        except ModelHTTPError as exc:
            # Degrade rather than crash on two recoverable conditions: a
            # context-window overflow on a large repo, or a sustained transient
            # provider outage (429/503) that survived the per-agent retries.
            # Other HTTP errors (auth, billing) still surface.
            msg = str(exc).lower()
            if (
                exc.status_code in (429, 503)
                or "too long" in msg
                or "context" in msg
            ):
                return incomplete("Analysis could not complete (provider/context)")
            raise

    async def _run(
        self,
        *,
        finding: dict,
        repo_knowledge: dict,
        clone_dir: Path | str,
        enrichment: dict | None = None,
        exposure: dict | None = None,
        traced_sha: str | None = None,
    ) -> TriageOutput:
        steps: list[str] = []
        base = {
            "profile": repo_knowledge.get("profile"),
            "code_map": repo_knowledge.get("code_map"),
            "threat": repo_knowledge.get("threat"),
        }

        def prov(exit_stage: str) -> TriageProvenance:
            return TriageProvenance(
                steps_run=list(steps),
                traced_sha=traced_sha,
                exit_stage=exit_stage,
                escalated=True,
                model_tiers={s: _STEP_TIER[s] for s in steps},
            )

        # 1. Gather the facts (cheap).
        facts = await self._stages.gather(
            _deps(clone_dir, finding, {**base, "enrichment": enrichment, "exposure": exposure}),
            self._models["cheap"],
        )
        steps.append("gather_facts")

        # 2. Rule out false alarms (cheap) — fail-cheap exit.
        ro = await self._stages.rule_out(
            _deps(clone_dir, finding, {**base, "facts": facts}), self._models["cheap"]
        )
        steps.append("rule_out")
        # Only honor a kill that is STRUCTURALLY corroborated (ADR-0052): the
        # code map confirms non-ship code, or the threat history confirms a
        # duplicate. A model's "looks safe" hunch is NOT allowed to terminally
        # clear — it falls through to trace_path, which must produce a real
        # disproof the challenge panel checks. Guarantees no rule-out false-clear.
        if ro.get("killed") and _kill_corroborated(ro, facts, repo_knowledge):
            verdict = ro.get("recommended_verdict_on_kill") or "false_positive"
            return TriageOutput(
                verdict=verdict,
                confidence=_CONF_KILL,
                checks=[
                    TriageCheck(
                        eyebrow="Ruled out",
                        result=ro.get("kill_class") or "false alarm",
                        kind="pass",
                        detail=ro.get("kill_evidence"),
                    )
                ],
                provenance=prov("rule_out"),
            )

        # 3. Trace the path (strong) — fail-cheap exit on a specific disproof.
        reach = await self._stages.trace(
            _deps(clone_dir, finding, {**base, "facts": facts}), self._models["strong"]
        )
        steps.append("trace_path")
        reached = reach.get("reached")
        if reached == "no":
            disproof = reach.get("disproof") or {}
            return TriageOutput(
                verdict="unexploitable",
                confidence=_CONF_DISPROOF,
                reachability=TriageReachability(
                    reached=False,
                    summary=disproof.get("explanation") or "A specific guard blocks this path.",
                ),
                exploitability=TriageExploitability(
                    exploitable="no", reason=disproof.get("explanation")
                ),
                checks=[
                    TriageCheck(
                        eyebrow="Disproof",
                        result="Not reachable",
                        kind="pass",
                        detail=disproof.get("guard_location"),
                    )
                ],
                provenance=prov("trace_path"),
            )
        if reached == "unknown":
            return TriageOutput(
                verdict="needs_review",
                confidence=_CONF_UNKNOWN,
                reachability=_map_reach(reach),
                provenance=prov("trace_path"),
            )

        # 4. Plan the exploit (strong) — reachable-but-no-exploit = hardening.
        plan = await self._stages.plan(
            _deps(clone_dir, finding, {**base, "facts": facts, "reachability": reach}),
            self._models["strong"],
        )
        steps.append("plan_exploit")
        if plan.get("no_credible_exploit"):
            return TriageOutput(
                verdict="unexploitable",
                confidence=_CONF_HARDENING,
                reachability=_map_reach(reach),
                exploitability=TriageExploitability(
                    exploitable="no",
                    reason="Reachable, but no credible exploit (hardening, not a vulnerability).",
                ),
                exploit_plan=ExploitPlan.model_validate(plan),
                provenance=prov("plan_exploit"),
            )

        # 5. Challenge the verdict (judge) — adversarial, deterministic resolution.
        challenge = await self._stages.challenge(
            _deps(
                clone_dir,
                finding,
                {**base, "facts": facts, "reachability": reach, "exploit_plan": plan},
            ),
            self._models["judge"],
            "real",
        )
        steps.append("challenge")

        verdict = (
            "real" if challenge.verdict_holds else (challenge.downgraded_verdict or "needs_review")
        )
        confidence = _clamp(_CONF_REAL + challenge.confidence_adjustment)
        return TriageOutput(
            verdict=verdict,
            confidence=confidence,
            reachability=_map_reach(reach),
            exploitability=TriageExploitability(
                exploitable="yes", reason="Reachable with a credible exploit path."
            ),
            exploit_plan=ExploitPlan.model_validate(plan),
            challenge=challenge,
            checks=[
                TriageCheck(
                    eyebrow="Challenge",
                    result="Held" if challenge.verdict_holds else "Downgraded",
                    kind="pass" if challenge.verdict_holds else "warn",
                    detail=f"{len(challenge.reviewers)} adversarial reviewers",
                )
            ],
            provenance=prov("challenge"),
        )


__all__ = ["DeepDiveRunner", "DeepDiveStages", "build_tier_models"]
