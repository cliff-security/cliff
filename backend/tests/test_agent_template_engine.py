"""Tests for Layer 1: AgentTemplateEngine and agent templates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from cliff.agents import AGENT_NAMES, AgentTemplateEngine
from cliff.models import Finding

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_finding_dict() -> dict:
    """A fully-populated Finding as a dict (simulates model_dump(mode='json'))."""
    now = datetime.now(UTC)
    f = Finding(
        id="finding-001",
        source_type="snyk",
        source_id="SNYK-JAVA-ORGAPACHELOGGINGLOG4J-2314720",
        title="Remote Code Execution in log4j (CVE-2021-44228)",
        description=(
            "A critical RCE vulnerability in Apache Log4j 2.x allows "
            "attackers to execute arbitrary code via crafted log messages "
            "using JNDI lookup patterns."
        ),
        raw_severity="critical",
        normalized_priority="P1",
        asset_id="svc-api-gateway",
        asset_label="api-gateway (prod)",
        status="new",
        likely_owner="platform-team",
        why_this_matters=(
            "Public exploit available. Internet-facing service "
            "processing untrusted input."
        ),
        raw_payload={"cve": "CVE-2021-44228", "cvss": 10.0},
        created_at=now,
        updated_at=now,
    )
    return f.model_dump(mode="json")


@pytest.fixture
def minimal_finding_dict() -> dict:
    """A Finding with only required fields as a dict."""
    now = datetime.now(UTC)
    f = Finding(
        id="finding-002",
        source_type="manual",
        source_id="manual-1",
        title="Expired TLS certificate",
        status="new",
        created_at=now,
        updated_at=now,
    )
    return f.model_dump(mode="json")


@pytest.fixture
def sample_enrichment() -> dict:
    return {
        "normalized_title": "Apache Log4j Remote Code Execution (Log4Shell)",
        "cve_ids": ["CVE-2021-44228", "CVE-2021-45046"],
        "cvss_score": 10.0,
        "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
        "description": "Log4Shell allows remote code execution via JNDI lookup.",
        "affected_versions": "< 2.17.1",
        "fixed_version": "2.17.1",
        "known_exploits": True,
        "exploit_details": (
            "Public PoC and Metasploit module available. Active exploitation in the wild."
        ),
        "references": ["https://nvd.nist.gov/vuln/detail/CVE-2021-44228"],
    }


@pytest.fixture
def sample_ownership() -> dict:
    return {
        "candidates": [
            {
                "team": "Platform Engineering",
                "person": "alice@example.com",
                "confidence": 0.92,
                "evidence": "CMDB shows platform-eng as support group for api-gateway",
                "source": "CMDB",
            }
        ],
        "recommended_owner": "Platform Engineering",
        "reasoning": "CMDB support group matches and 3/5 recent commits are from this team.",
    }


@pytest.fixture
def sample_exposure() -> dict:
    return {
        "environment": "production",
        "internet_facing": True,
        "reachable": "confirmed",
        "reachability_evidence": "Import chain: main.py -> auth.py -> log4j",
        "business_criticality": "critical",
        "blast_radius": "User authentication flow serving 50K accounts",
        "compensating_controls": None,
        "recommended_urgency": "immediate",
    }


@pytest.fixture
def sample_plan() -> dict:
    return {
        "plan_steps": [
            "Upgrade log4j-core from 2.14.1 to 2.17.1 in pom.xml",
            "Run existing test suite to verify no regressions",
            "Deploy to staging and run Tenable scan",
            "Deploy to production after staging validation",
        ],
        "interim_mitigation": "Set LOG4J_FORMAT_MSG_NO_LOOKUPS=true in production env vars",
        "dependencies": ["CI pipeline access", "Staging environment availability"],
        "estimated_effort": "small",
        "suggested_due_date": "2026-03-29",
        "definition_of_done": [
            "log4j-core >= 2.17.1 in dependency tree",
            "All tests pass",
            "Tenable scan shows CVE-2021-44228 resolved",
            "No new critical/high findings introduced",
        ],
        "validation_method": "Re-run Tenable scan on api-gateway asset",
    }


@pytest.fixture
def sample_validation() -> dict:
    return {
        "verdict": "fixed",
        "evidence": "Tenable re-scan shows log4j-core 2.17.1, CVE-2021-44228 no longer detected.",
        "definition_of_done_results": [
            {"criterion": "log4j-core >= 2.17.1", "met": True, "evidence": "pom.xml shows 2.17.1"},
        ],
        "remaining_concerns": [],
        "recommendation": "close",
    }


@pytest.fixture
def engine() -> AgentTemplateEngine:
    return AgentTemplateEngine()


# ---------------------------------------------------------------------------
# render_all basics
# ---------------------------------------------------------------------------


def test_render_all_returns_seven_agents(engine: AgentTemplateEngine, sample_finding_dict: dict):
    agents = engine.render_all(finding=sample_finding_dict)
    assert len(agents) == 8
    names = [a.name for a in agents]
    assert names == AGENT_NAMES


def test_render_all_filenames(engine: AgentTemplateEngine, sample_finding_dict: dict):
    agents = engine.render_all(finding=sample_finding_dict)
    for agent in agents:
        assert agent.filename == f"{agent.name}.md"


def test_render_agent_invalid_name_raises(engine: AgentTemplateEngine, sample_finding_dict: dict):
    with pytest.raises(ValueError, match="Unknown agent name"):
        engine.render_agent("nonexistent", finding=sample_finding_dict)


# ---------------------------------------------------------------------------
# Orchestrator template
# ---------------------------------------------------------------------------


def test_orchestrator_contains_finding_data(engine: AgentTemplateEngine, sample_finding_dict: dict):
    agent = engine.render_agent("orchestrator", finding=sample_finding_dict)
    assert "Remote Code Execution in log4j" in agent.content
    assert "snyk" in agent.content
    assert "critical" in agent.content
    assert "api-gateway" in agent.content
    assert "platform-team" in agent.content


def test_orchestrator_minimal_finding_no_none(
    engine: AgentTemplateEngine, minimal_finding_dict: dict
):
    agent = engine.render_agent("orchestrator", finding=minimal_finding_dict)
    assert "Expired TLS certificate" in agent.content
    assert "None" not in agent.content


def test_orchestrator_yaml_frontmatter(engine: AgentTemplateEngine, sample_finding_dict: dict):
    agent = engine.render_agent("orchestrator", finding=sample_finding_dict)
    assert agent.content.startswith("---\n")
    assert "mode: primary" in agent.content


def test_orchestrator_pipeline_state_initial(
    engine: AgentTemplateEngine, sample_finding_dict: dict
):
    """With only finding data, all pipeline items show unchecked."""
    agent = engine.render_agent("orchestrator", finding=sample_finding_dict)
    assert agent.content.count("- [ ]") == 5
    assert "- [x]" not in agent.content


def test_orchestrator_pipeline_state_with_enrichment(
    engine: AgentTemplateEngine,
    sample_finding_dict: dict,
    sample_enrichment: dict,
):
    """With enrichment, enrichment shows checked, others unchecked."""
    agent = engine.render_agent(
        "orchestrator", finding=sample_finding_dict, enrichment=sample_enrichment
    )
    assert "- [x] **Enrichment**" in agent.content
    assert agent.content.count("- [ ]") == 4


def test_orchestrator_pipeline_state_all_complete(
    engine: AgentTemplateEngine,
    sample_finding_dict: dict,
    sample_enrichment: dict,
    sample_ownership: dict,
    sample_exposure: dict,
    sample_plan: dict,
    sample_validation: dict,
):
    """With all sections, all items show checked."""
    agent = engine.render_agent(
        "orchestrator",
        finding=sample_finding_dict,
        enrichment=sample_enrichment,
        ownership=sample_ownership,
        exposure=sample_exposure,
        plan=sample_plan,
        validation=sample_validation,
    )
    assert agent.content.count("- [x]") == 5
    assert "- [ ]" not in agent.content
    # Verify enrichment data is in the body
    assert "CVE-2021-44228" in agent.content
    assert "Platform Engineering" in agent.content
    assert "immediate" in agent.content


# ---------------------------------------------------------------------------
# Sub-agent templates
# ---------------------------------------------------------------------------


def test_subagent_yaml_frontmatter(engine: AgentTemplateEngine, sample_finding_dict: dict):
    """All 6 sub-agents have mode: subagent in frontmatter."""
    agents = engine.render_all(finding=sample_finding_dict)
    for agent in agents:
        if agent.name == "orchestrator":
            continue
        assert "mode: subagent" in agent.content, f"{agent.name} missing mode: subagent"


def test_enricher_contains_finding_context(
    engine: AgentTemplateEngine, sample_finding_dict: dict
):
    agent = engine.render_agent("enricher", finding=sample_finding_dict)
    assert "Remote Code Execution in log4j" in agent.content
    assert "JNDI lookup" in agent.content


def test_enricher_output_contract(engine: AgentTemplateEngine, sample_finding_dict: dict):
    agent = engine.render_agent("enricher", finding=sample_finding_dict)
    assert "normalized_title" in agent.content
    assert "cve_ids" in agent.content
    assert "cvss_score" in agent.content
    assert "known_exploits" in agent.content
    assert "fixed_version" in agent.content


def test_planner_includes_prior_context(
    engine: AgentTemplateEngine,
    sample_finding_dict: dict,
    sample_enrichment: dict,
    sample_ownership: dict,
    sample_exposure: dict,
):
    """Planner template includes enrichment CVE, ownership team, exposure urgency."""
    agent = engine.render_agent(
        "remediation_planner",
        finding=sample_finding_dict,
        enrichment=sample_enrichment,
        ownership=sample_ownership,
        exposure=sample_exposure,
    )
    assert "CVE-2021-44228" in agent.content
    assert "Platform Engineering" in agent.content
    assert "immediate" in agent.content


def test_validation_includes_plan(
    engine: AgentTemplateEngine,
    sample_finding_dict: dict,
    sample_enrichment: dict,
    sample_plan: dict,
):
    """Validation checker includes plan steps and definition of done."""
    agent = engine.render_agent(
        "validation_checker",
        finding=sample_finding_dict,
        enrichment=sample_enrichment,
        plan=sample_plan,
    )
    assert "Upgrade log4j-core" in agent.content
    assert "log4j-core >= 2.17.1" in agent.content
    assert "definition of done" in agent.content.lower()


# ---------------------------------------------------------------------------
# write_agents
# ---------------------------------------------------------------------------


def test_write_agents_creates_files(
    engine: AgentTemplateEngine, sample_finding_dict: dict, tmp_path: Path
):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    paths = engine.write_agents(agents_dir, finding=sample_finding_dict)
    assert len(paths) == 8
    for path in paths:
        assert path.exists()
        assert path.suffix == ".md"
        assert path.read_text().startswith("---\n")


def test_write_agents_overwrites_existing(
    engine: AgentTemplateEngine,
    sample_finding_dict: dict,
    sample_enrichment: dict,
    tmp_path: Path,
):
    """Re-rendering with new context changes file content."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    engine.write_agents(agents_dir, finding=sample_finding_dict)
    initial = (agents_dir / "orchestrator.md").read_text()

    engine.write_agents(agents_dir, finding=sample_finding_dict, enrichment=sample_enrichment)
    updated = (agents_dir / "orchestrator.md").read_text()

    assert initial != updated
    assert "CVE-2021-44228" in updated


# ---------------------------------------------------------------------------
# Idempotency and custom templates
# ---------------------------------------------------------------------------


def test_re_render_idempotent(engine: AgentTemplateEngine, sample_finding_dict: dict):
    """Same inputs produce identical output."""
    a = engine.render_all(finding=sample_finding_dict)
    b = engine.render_all(finding=sample_finding_dict)
    for agent_a, agent_b in zip(a, b, strict=True):
        assert agent_a.content == agent_b.content


def test_custom_templates_dir(tmp_path: Path):
    """Engine loads templates from a custom directory."""
    custom_dir = tmp_path / "custom_templates"
    custom_dir.mkdir()
    (custom_dir / "orchestrator.md.j2").write_text(
        "---\nmode: primary\n---\nCustom: {{ finding.title }}\n"
    )

    # Only orchestrator template exists, so render just that one
    engine = AgentTemplateEngine(templates_dir=custom_dir)
    agent = engine.render_agent("orchestrator", finding={"title": "Test"})
    assert "Custom: Test" in agent.content


# ---------------------------------------------------------------------------
# Remediation executor template
# ---------------------------------------------------------------------------


def test_executor_contains_finding_context(
    engine: AgentTemplateEngine, sample_finding_dict: dict
):
    agent = engine.render_agent("remediation_executor", finding=sample_finding_dict)
    assert "Remote Code Execution in log4j" in agent.content
    assert "snyk" in agent.content


def test_executor_yaml_frontmatter(engine: AgentTemplateEngine, sample_finding_dict: dict):
    agent = engine.render_agent("remediation_executor", finding=sample_finding_dict)
    assert agent.content.startswith("---\n")
    assert "mode: subagent" in agent.content
    assert "Remediate:" in agent.content


def test_executor_includes_plan_steps(
    engine: AgentTemplateEngine,
    sample_finding_dict: dict,
    sample_plan: dict,
):
    """Executor template shows plan steps from the planner."""
    agent = engine.render_agent(
        "remediation_executor",
        finding=sample_finding_dict,
        plan=sample_plan,
    )
    assert "Upgrade log4j-core" in agent.content
    assert "definition of done" in agent.content.lower()
    assert "log4j-core >= 2.17.1" in agent.content


def test_executor_includes_enrichment_context(
    engine: AgentTemplateEngine,
    sample_finding_dict: dict,
    sample_enrichment: dict,
    sample_plan: dict,
):
    """Executor template includes enrichment CVE data."""
    agent = engine.render_agent(
        "remediation_executor",
        finding=sample_finding_dict,
        enrichment=sample_enrichment,
        plan=sample_plan,
    )
    assert "CVE-2021-44228" in agent.content
    assert "2.17.1" in agent.content


def test_executor_includes_repo_instructions(
    engine: AgentTemplateEngine, sample_finding_dict: dict
):
    """Executor template includes git/gh workflow instructions."""
    agent = engine.render_agent("remediation_executor", finding=sample_finding_dict)
    assert "git clone" in agent.content
    assert "git checkout -b cliff/fix/" in agent.content
    assert "gh pr create --draft" in agent.content
    assert "git push" in agent.content


def test_executor_output_contract(engine: AgentTemplateEngine, sample_finding_dict: dict):
    """Executor template includes the structured output contract."""
    agent = engine.render_agent("remediation_executor", finding=sample_finding_dict)
    assert "pr_url" in agent.content
    assert "branch_name" in agent.content
    assert "changes_summary" in agent.content
    assert "test_results" in agent.content
    assert "status" in agent.content


# ---------------------------------------------------------------------------
# Posture-detail surface and hard rules (regression for the agent that opened
# PR #111 — it confabulated a fix because it never saw the structured detail).
# ---------------------------------------------------------------------------


@pytest.fixture
def posture_finding_dict() -> dict:
    """A type='posture' finding with structured detail under raw_payload."""
    now = datetime.now(UTC)
    f = Finding(
        id="finding-posture-001",
        source_type="cliff-posture",
        source_id="https://github.com/cliff-security/cliff:trusted_action_sources",
        title="trusted_action_sources",
        type="posture",
        status="new",
        asset_label="https://github.com/cliff-security/cliff",
        raw_payload={
            "check_name": "trusted_action_sources",
            "scanner_status": "fail",
            "detail": {
                "untrusted_count": 2,
                "untrusted": [
                    {
                        "file": ".github/workflows/release.yml",
                        "action": "aquasecurity/trivy-action",
                        "owner": "aquasecurity",
                    },
                    {
                        "file": ".github/workflows/release.yml",
                        "action": "sigstore/cosign-installer",
                        "owner": "sigstore",
                    },
                ],
            },
        },
        created_at=now,
        updated_at=now,
    )
    return f.model_dump(mode="json")


def test_executor_surfaces_posture_detail(
    engine: AgentTemplateEngine, posture_finding_dict: dict
):
    """The executor must see the structured ``raw_payload.detail`` for posture
    findings — without this section the agent has only the title to reason from
    and confabulates fixes (PR #111 hallucinated a SHA, used a non-action repo,
    and added a workflow without a permissions block — none of which addressed
    the cited rows).
    """
    agent = engine.render_agent(
        "remediation_executor", finding=posture_finding_dict
    )
    assert "Scanner detail (posture)" in agent.content
    # Each cited row's identifying fields must reach the prompt verbatim so
    # the executor can name them in the diff.
    assert "aquasecurity/trivy-action" in agent.content
    assert "sigstore/cosign-installer" in agent.content
    assert ".github/workflows/release.yml" in agent.content


def test_executor_includes_hard_rules(
    engine: AgentTemplateEngine, sample_finding_dict: dict
):
    """The executor's hard-rules block must be present on every render — these
    are the verify-SHA / verify-action / require-permissions / address-cited-rows
    guardrails that PR #111's failure mode taught us to write down.
    """
    agent = engine.render_agent(
        "remediation_executor", finding=sample_finding_dict
    )
    assert "Never invent a SHA" in agent.content
    assert "Verify the action exists" in agent.content
    assert "permissions:" in agent.content
    assert "address the cited rows" in agent.content
    assert "Never claim to have done what you didn't" in agent.content
    # The exact verification command must appear so the agent has a concrete
    # invocation to copy rather than infer.
    assert 'gh api "repos/<owner>/<repo>/commits/<ref>"' in agent.content


def test_planner_surfaces_posture_detail(
    engine: AgentTemplateEngine, posture_finding_dict: dict
):
    """Same surface gap as the executor — the planner needs the cited rows in
    its prompt or its plan defaults to "harden CI" rather than "edit these
    nine specific lines".
    """
    agent = engine.render_agent(
        "remediation_planner", finding=posture_finding_dict
    )
    assert "Scanner detail (posture)" in agent.content
    assert "aquasecurity/trivy-action" in agent.content
    assert "address the cited rows, not the policy" in agent.content
