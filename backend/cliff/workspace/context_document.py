"""ContextDocument — generates CONTEXT.md from structured workspace data."""

from __future__ import annotations

from typing import Any


class ContextDocument:
    """Generates CONTEXT.md content from structured workspace data.

    Uses plain Python string formatting — no template engine required.
    """

    @staticmethod
    def generate(
        finding: dict[str, Any],
        *,
        enrichment: dict[str, Any] | None = None,
        ownership: dict[str, Any] | None = None,
        exposure: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
        remediation: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
    ) -> str:
        """Generate the full CONTEXT.md content.

        Args:
            finding: The finding dict (from finding.json).
            enrichment: Enrichment data, if available.
            ownership: Ownership data, if available.
            exposure: Exposure analysis data, if available.
            plan: Remediation plan data, if available.
            remediation: Remediation executor results, if available.
            validation: Validation results, if available.

        Returns:
            Markdown string for CONTEXT.md.
        """
        sections = [
            "# Workspace context\n",
            ContextDocument.finding_section(finding),
            ContextDocument.knowledge_section(enrichment, ownership, exposure),
            ContextDocument._evidence_section(evidence),
            ContextDocument._plan_section(plan),
            ContextDocument._remediation_section(remediation),
            ContextDocument._validation_section(validation),
            ContextDocument._next_steps_section(
                enrichment, ownership, exposure, evidence, plan,
                remediation, validation,
            ),
            ContextDocument._files_section(
                enrichment, ownership, exposure, evidence, plan,
                remediation, validation,
            ),
        ]
        return "\n".join(s for s in sections if s)

    @staticmethod
    def finding_section(finding: dict[str, Any]) -> str:
        lines = ["## Finding", ""]
        title = finding.get("title", "Unknown finding")
        lines.append(f"- **Title:** {title}")

        status = finding.get("status")
        if status:
            lines.append(f"- **Status:** {status}")

        severity = finding.get("raw_severity")
        if severity:
            lines.append(f"- **Severity:** {severity}")

        priority = finding.get("normalized_priority")
        if priority:
            lines.append(f"- **Priority:** {priority}")

        asset = finding.get("asset_label") or finding.get("asset_id")
        if asset:
            lines.append(f"- **Asset:** {asset}")

        source = finding.get("source_type")
        if source:
            source_id = finding.get("source_id", "")
            label = f"{source} / {source_id}" if source_id else source
            lines.append(f"- **Source:** {label}")

        owner = finding.get("likely_owner")
        if owner:
            lines.append(f"- **Likely owner:** {owner}")

        lines.append("")
        description = finding.get("description")
        if description:
            lines.append(description)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def knowledge_section(
        enrichment: dict[str, Any] | None,
        ownership: dict[str, Any] | None,
        exposure: dict[str, Any] | None,
    ) -> str:
        if not any([enrichment, ownership, exposure]):
            return ""

        lines = ["## What we know so far", ""]

        if enrichment:
            lines.append("### Enrichment")
            summary = enrichment.get("summary") or enrichment.get("normalized_title")
            if summary:
                lines.append(f"- {summary}")
            cve_ids = enrichment.get("cve_ids")
            if cve_ids:
                lines.append(f"- **CVEs:** {', '.join(cve_ids)}")
            cvss = enrichment.get("cvss_score")
            if cvss is not None:
                lines.append(f"- **CVSS:** {cvss}")
            exploits = enrichment.get("known_exploits")
            if exploits:
                lines.append("- **Known exploits:** yes")
            fixed = enrichment.get("fixed_version")
            if fixed:
                lines.append(f"- **Fix version:** {fixed}")
            lines.append("")

        if ownership:
            lines.append("### Ownership")
            recommended = ownership.get("recommended_owner")
            if recommended:
                confidence = ownership.get("confidence")
                conf_str = f" ({confidence}% confidence)" if confidence else ""
                lines.append(f"- **Recommended owner:** {recommended}{conf_str}")
            reasoning = ownership.get("reasoning")
            if reasoning:
                lines.append(f"- {reasoning}")
            lines.append("")

        if exposure:
            lines.append("### Exposure")
            env = exposure.get("environment")
            if env:
                lines.append(f"- **Environment:** {env}")
            facing = exposure.get("internet_facing")
            if facing is not None:
                lines.append(f"- **Internet facing:** {'yes' if facing else 'no'}")
            reachable = exposure.get("reachable")
            if reachable:
                lines.append(f"- **Reachable:** {reachable}")
            blast = exposure.get("blast_radius")
            if blast:
                lines.append(f"- **Blast radius:** {blast}")
            urgency = exposure.get("recommended_urgency")
            if urgency:
                lines.append(f"- **Urgency:** {urgency}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _evidence_section(evidence: dict[str, Any] | None) -> str:
        if not evidence:
            return ""

        lines = ["## Evidence", ""]
        affected = evidence.get("affected_files")
        if affected:
            lines.append("### Affected files")
            for f in affected:
                path = f.get("path", "unknown")
                ctx = f.get("context", "")
                line_num = f.get("line")
                loc = f":{line_num}" if line_num else ""
                lines.append(f"- `{path}{loc}` — {ctx}")
            lines.append("")

        chain = evidence.get("dependency_chain")
        if chain:
            lines.append("### Dependency chain")
            for item in chain:
                lines.append(f"- {item}")
            lines.append("")

        safety = evidence.get("fix_safety")
        if safety:
            lines.append(f"- **Fix safety:** {safety}")
        reasoning = evidence.get("fix_safety_reasoning")
        if reasoning:
            lines.append(f"- **Reasoning:** {reasoning}")

        approach = evidence.get("recommended_approach")
        if approach:
            lines.append(f"- **Recommended approach:** {approach}")

        impact = evidence.get("impact_assessment")
        if impact:
            lines.append(f"- **Impact:** {impact}")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _plan_section(plan: dict[str, Any] | None) -> str:
        if not plan:
            return ""

        lines = ["## Current plan", ""]
        steps = plan.get("plan_steps") or plan.get("steps")
        if steps:
            for i, step in enumerate(steps, 1):
                lines.append(f"{i}. {step}")
            lines.append("")

        mitigation = plan.get("interim_mitigation")
        if mitigation:
            lines.append(f"**Interim mitigation:** {mitigation}")
            lines.append("")

        effort = plan.get("estimated_effort")
        if effort:
            lines.append(f"**Estimated effort:** {effort}")

        due = plan.get("suggested_due_date")
        if due:
            lines.append(f"**Suggested due date:** {due}")

        dod = plan.get("definition_of_done")
        if dod:
            lines.append("")
            lines.append("**Definition of done:**")
            for item in dod:
                lines.append(f"- [ ] {item}")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _remediation_section(remediation: dict[str, Any] | None) -> str:
        if not remediation:
            return ""

        lines = ["## Remediation", ""]
        status = remediation.get("status")
        if status:
            lines.append(f"- **Status:** {status}")
        pr_url = remediation.get("pr_url")
        if pr_url:
            lines.append(f"- **Pull request:** {pr_url}")
        branch = remediation.get("branch_name")
        if branch:
            lines.append(f"- **Branch:** {branch}")
        summary = remediation.get("changes_summary")
        if summary:
            lines.append(f"- **Changes:** {summary}")
        tests = remediation.get("test_results")
        if tests:
            lines.append(f"- **Tests:** {tests}")
        error = remediation.get("error_details")
        if error:
            lines.append(f"- **Error:** {error}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _validation_section(validation: dict[str, Any] | None) -> str:
        if not validation:
            return ""

        lines = ["## Validation", ""]
        verdict = validation.get("verdict") or validation.get("state")
        if verdict:
            lines.append(f"- **Verdict:** {verdict}")
        evidence = validation.get("evidence")
        if evidence and isinstance(evidence, str):
            lines.append(f"- **Evidence:** {evidence}")
        recommendation = validation.get("recommendation")
        if recommendation:
            lines.append(f"- **Recommendation:** {recommendation}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _next_steps_section(
        enrichment: dict[str, Any] | None,
        ownership: dict[str, Any] | None,
        exposure: dict[str, Any] | None,
        evidence: dict[str, Any] | None,
        plan: dict[str, Any] | None,
        remediation: dict[str, Any] | None,
        validation: dict[str, Any] | None,
    ) -> str:
        missing: list[str] = []
        if not enrichment:
            missing.append(
                "Run **finding enricher** to get CVE details, severity context, "
                "and exploit information"
            )
        if not ownership:
            missing.append(
                "Run **owner resolver** to identify the responsible team"
            )
        if not exposure:
            missing.append(
                "Run **exposure analyzer** to assess reachability and blast radius"
            )
        if not evidence:
            missing.append(
                "Run **evidence collector** to locate affected files and assess fix impact"
            )
        if not plan:
            missing.append(
                "Run **remediation planner** to generate a fix plan"
            )
        if not remediation:
            missing.append(
                "Run **remediation executor** to apply the fix and create a PR"
            )
        if not validation:
            missing.append(
                "Run **validation checker** to confirm the fix"
            )

        if not missing:
            return "## Status\n\nAll agents have run. Ready for review and closure.\n"

        lines = ["## What needs to happen next", ""]
        for item in missing:
            lines.append(f"- {item}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _files_section(
        enrichment: dict[str, Any] | None,
        ownership: dict[str, Any] | None,
        exposure: dict[str, Any] | None,
        evidence: dict[str, Any] | None,
        plan: dict[str, Any] | None,
        remediation: dict[str, Any] | None,
        validation: dict[str, Any] | None,
    ) -> str:
        lines = ["## Files in this workspace", ""]
        lines.append("- `context/finding.json` — raw finding payload from scanner")
        lines.append("- `context/finding.md` — human-readable finding summary")
        if enrichment:
            lines.append(
                "- `context/enrichment.json` — CVE details, exploit info, affected versions"
            )
        if ownership:
            lines.append(
                "- `context/ownership.json` — team/person ownership with evidence"
            )
        if exposure:
            lines.append(
                "- `context/exposure.json` — reachability, environment, blast radius"
            )
        if evidence:
            lines.append(
                "- `context/evidence.json` — affected files, dependency chain, fix impact"
            )
        if plan:
            lines.append(
                "- `context/plan.json` — remediation steps, mitigations, definition of done"
            )
        if remediation:
            lines.append(
                "- `context/remediation.json` — executor results, PR link, changes summary"
            )
        if validation:
            lines.append(
                "- `context/validation.json` — fix verification results"
            )
        lines.append("")
        return "\n".join(lines)
