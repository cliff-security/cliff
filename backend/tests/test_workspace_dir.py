"""Tests for Layer 0: WorkspaceDirManager, ContextDocument, AgentRunLog."""

from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from cliff.models import Finding
from cliff.workspace import (
    AgentRunLog,
    ContextDocument,
    WorkspaceDirManager,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_finding() -> Finding:
    """A fully-populated Finding for testing."""
    now = datetime.now(UTC)
    return Finding(
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


@pytest.fixture
def minimal_finding() -> Finding:
    """A Finding with only required fields."""
    now = datetime.now(UTC)
    return Finding(
        id="finding-002",
        source_type="manual",
        source_id="manual-1",
        title="Expired TLS certificate",
        status="new",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def manager(tmp_path: Path) -> WorkspaceDirManager:
    return WorkspaceDirManager(base_dir=tmp_path / "workspaces")


# ---------------------------------------------------------------------------
# WorkspaceDirManager — create
# ---------------------------------------------------------------------------


def test_create_full_structure(manager: WorkspaceDirManager, sample_finding: Finding):
    """Create workspace dir from Finding -> verify full structure exists."""
    ws = manager.create("ws-001", sample_finding)
    assert ws.exists()
    assert ws.root.is_dir()
    assert ws.context_dir.is_dir()
    assert ws.history_dir.is_dir()
    assert ws.code_snippets_dir.is_dir()
    assert ws.references_dir.is_dir()
    assert ws.finding_json.is_file()
    assert ws.finding_md.is_file()
    assert ws.context_md.is_file()
    assert ws.agent_runs_log.is_file()


def test_create_duplicate_raises(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Creating the same workspace ID twice raises FileExistsError."""
    manager.create("ws-dup", sample_finding)
    with pytest.raises(FileExistsError):
        manager.create("ws-dup", sample_finding)


def test_create_path_traversal_raises(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Workspace IDs with path traversal characters are rejected."""
    with pytest.raises(ValueError, match="path separator"):
        manager.create("../escape", sample_finding)
    with pytest.raises(ValueError, match="path separator"):
        manager.create("sub/dir", sample_finding)
    with pytest.raises(ValueError, match="relative path"):
        manager.create("..", sample_finding)
    with pytest.raises(ValueError, match="empty"):
        manager.create("", sample_finding)


# ---------------------------------------------------------------------------
# WorkspaceDirManager — read context
# ---------------------------------------------------------------------------


def test_write_read_context_section(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Write a context section -> read it back -> verify match."""
    manager.create("ws-rw", sample_finding)
    enrichment = {"summary": "Log4j RCE", "cvss_score": 10.0, "known_exploits": True}
    manager.write_context_section("ws-rw", "enrichment", enrichment)
    result = manager.read_context_section("ws-rw", "enrichment")
    assert result == enrichment


def test_read_missing_section_returns_none(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Reading a section that doesn't exist returns None."""
    manager.create("ws-miss", sample_finding)
    assert manager.read_context_section("ws-miss", "enrichment") is None


def test_read_all_context(manager: WorkspaceDirManager, sample_finding: Finding):
    """read_all_context returns all sections, None for missing ones."""
    manager.create("ws-all", sample_finding)
    manager.write_context_section("ws-all", "enrichment", {"summary": "test"})
    ctx = manager.read_all_context("ws-all")
    assert ctx["enrichment"] == {"summary": "test"}
    assert ctx["ownership"] is None
    assert ctx["exposure"] is None
    assert ctx["plan"] is None
    assert ctx["validation"] is None


def test_write_context_nonexistent_workspace(manager: WorkspaceDirManager):
    """Writing to a nonexistent workspace raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        manager.write_context_section("ws-ghost", "enrichment", {"x": 1})


# ---------------------------------------------------------------------------
# CONTEXT.md generation and updates
# ---------------------------------------------------------------------------


def test_context_md_initial_generation(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """CONTEXT.md with initial finding contains key info."""
    ws = manager.create("ws-ctx", sample_finding)
    content = ws.context_md.read_text()
    assert "Remote Code Execution" in content
    assert "critical" in content
    assert "api-gateway" in content
    assert "What needs to happen next" in content


def test_context_md_updates_after_write(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Updating a context section regenerates CONTEXT.md."""
    ws = manager.create("ws-upd", sample_finding)
    initial = ws.context_md.read_text()

    manager.write_context_section(
        "ws-upd", "enrichment", {"summary": "CVE-2021-44228 is a Log4Shell RCE."}
    )
    updated = ws.context_md.read_text()
    assert updated != initial
    assert "What we know so far" in updated


def test_context_md_minimal_finding(
    manager: WorkspaceDirManager, minimal_finding: Finding
):
    """CONTEXT.md with minimal finding data doesn't render 'None'."""
    ws = manager.create("ws-min", minimal_finding)
    content = ws.context_md.read_text()
    assert "Expired TLS certificate" in content
    assert "None" not in content


def test_context_md_full_context(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """CONTEXT.md with all sections populated shows complete picture."""
    manager.create("ws-full", sample_finding)
    manager.write_context_section(
        "ws-full", "enrichment", {"summary": "Log4Shell", "cvss_score": 10.0}
    )
    manager.write_context_section(
        "ws-full", "ownership", {"recommended_owner": "platform-team", "confidence": 95}
    )
    manager.write_context_section(
        "ws-full", "exposure", {"reachable": "likely", "blast_radius": "high"}
    )
    manager.write_context_section(
        "ws-full",
        "evidence",
        {
            "affected_files": [{"path": "pom.xml", "line": 10, "context": "log4j 2.14"}],
            "fix_safety": "safe_bump",
        },
    )
    manager.write_context_section(
        "ws-full",
        "plan",
        {"plan_steps": ["Upgrade log4j", "Deploy", "Verify"], "estimated_effort": "small"},
    )
    manager.write_context_section(
        "ws-full",
        "remediation",
        {"status": "pr_created", "pr_url": "https://github.com/org/repo/pull/1"},
    )
    manager.write_context_section(
        "ws-full", "validation", {"verdict": "fixed", "recommendation": "close"}
    )

    ws = manager.get("ws-full")
    assert ws is not None
    content = ws.context_md.read_text()
    assert "What we know so far" in content
    assert "Evidence" in content
    assert "Current plan" in content
    assert "Remediation" in content
    assert "Validation" in content
    assert "All agents have run" in content


# ---------------------------------------------------------------------------
# WorkspaceDirManager — archive
# ---------------------------------------------------------------------------


def test_archive_creates_tarball(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Archive workspace -> verify tar.gz created and contains key files."""
    manager.create("ws-arch", sample_finding)
    archive_path = manager.archive("ws-arch")
    assert archive_path.exists()
    assert str(archive_path).endswith(".tar.gz")
    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        assert any("finding.json" in n for n in names)
        assert any("CONTEXT.md" in n for n in names)


def test_archive_nonexistent_raises(manager: WorkspaceDirManager):
    """Archiving a nonexistent workspace raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        manager.archive("ws-nope")


# ---------------------------------------------------------------------------
# WorkspaceDirManager — list, get, delete
# ---------------------------------------------------------------------------


def test_list_workspaces(
    manager: WorkspaceDirManager,
    sample_finding: Finding,
    minimal_finding: Finding,
):
    """Create multiple workspaces -> list them -> verify all returned."""
    manager.create("ws-a", sample_finding)
    manager.create("ws-b", minimal_finding)
    workspaces = manager.list()
    ids = [ws.workspace_id for ws in workspaces]
    assert "ws-a" in ids
    assert "ws-b" in ids
    assert len(workspaces) == 2


def test_list_empty(manager: WorkspaceDirManager):
    """Listing when no workspaces exist returns empty list."""
    assert manager.list() == []


def test_get_existing(manager: WorkspaceDirManager, sample_finding: Finding):
    """get() returns WorkspaceDir for existing workspace."""
    manager.create("ws-get", sample_finding)
    ws = manager.get("ws-get")
    assert ws is not None
    assert ws.workspace_id == "ws-get"


def test_get_nonexistent(manager: WorkspaceDirManager):
    """get() returns None for nonexistent workspace."""
    assert manager.get("ws-nope") is None


def test_delete_workspace(manager: WorkspaceDirManager, sample_finding: Finding):
    """Create then delete -> verify gone."""
    manager.create("ws-del", sample_finding)
    assert manager.get("ws-del") is not None
    assert manager.delete("ws-del") is True
    assert manager.get("ws-del") is None


def test_delete_nonexistent_returns_false(manager: WorkspaceDirManager):
    """Deleting a nonexistent workspace returns False."""
    assert manager.delete("ws-nope") is False


# ---------------------------------------------------------------------------
# Finding files
# ---------------------------------------------------------------------------


def test_finding_md_full(manager: WorkspaceDirManager, sample_finding: Finding):
    """finding.md with full data is human-readable with key fields."""
    ws = manager.create("ws-fmd", sample_finding)
    content = ws.finding_md.read_text()
    assert "# Remote Code Execution" in content
    assert "critical" in content
    assert "api-gateway" in content
    assert "platform-team" in content
    assert "Public exploit available" in content


def test_finding_md_minimal(manager: WorkspaceDirManager, minimal_finding: Finding):
    """finding.md with minimal data doesn't render 'None'."""
    ws = manager.create("ws-fmd-min", minimal_finding)
    content = ws.finding_md.read_text()
    assert "# Expired TLS certificate" in content
    assert "None" not in content


def test_finding_json_roundtrip(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """finding.json can be deserialized back to a Finding."""
    ws = manager.create("ws-fj", sample_finding)
    data = json.loads(ws.finding_json.read_text())
    restored = Finding(**data)
    assert restored.id == sample_finding.id
    assert restored.title == sample_finding.title
    assert restored.raw_severity == sample_finding.raw_severity


# ---------------------------------------------------------------------------
# AgentRunLog
# ---------------------------------------------------------------------------


def test_agent_run_log_append_read(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Append agent runs -> read back -> verify order and content."""
    ws = manager.create("ws-log", sample_finding)
    log = AgentRunLog(ws.agent_runs_log)
    log.append(agent_type="finding_enricher", status="running")
    log.append(
        agent_type="finding_enricher",
        status="completed",
        summary="Found CVE details",
    )
    log.append(agent_type="owner_resolver", status="running")

    entries = log.read_all()
    assert len(entries) == 3
    assert entries[0]["agent_type"] == "finding_enricher"
    assert entries[0]["status"] == "running"
    assert entries[1]["status"] == "completed"
    assert entries[1]["summary"] == "Found CVE details"
    assert entries[2]["agent_type"] == "owner_resolver"
    for entry in entries:
        assert "timestamp" in entry


def test_agent_run_log_read_latest(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """read_latest returns only the N most recent entries."""
    ws = manager.create("ws-latest", sample_finding)
    log = AgentRunLog(ws.agent_runs_log)
    for i in range(5):
        log.append(agent_type="finding_enricher", status=f"step-{i}")
    latest = log.read_latest(2)
    assert len(latest) == 2
    assert latest[0]["status"] == "step-3"
    assert latest[1]["status"] == "step-4"


def test_agent_run_log_empty(manager: WorkspaceDirManager, sample_finding: Finding):
    """Reading from an empty log returns empty list."""
    ws = manager.create("ws-empty-log", sample_finding)
    log = AgentRunLog(ws.agent_runs_log)
    assert log.read_all() == []


# ---------------------------------------------------------------------------
# Multiple workspaces
# ---------------------------------------------------------------------------


def test_multiple_workspaces_no_conflicts(
    manager: WorkspaceDirManager, sample_finding: Finding
):
    """Create 10 workspaces -> verify no conflicts."""
    for i in range(10):
        ws = manager.create(f"ws-{i:03d}", sample_finding)
        assert ws.exists()
    assert len(manager.list()) == 10


# ---------------------------------------------------------------------------
# ContextDocument (standalone unit tests)
# ---------------------------------------------------------------------------


def test_context_document_generate_finding_only():
    """ContextDocument.generate with only finding shows next steps."""
    finding = {"title": "Weak cipher suite", "status": "new", "source_type": "qualys"}
    doc = ContextDocument.generate(finding)
    assert "Weak cipher suite" in doc
    assert "What needs to happen next" in doc
    assert "finding enricher" in doc


def test_context_document_generate_all_sections():
    """ContextDocument.generate with all sections shows complete document."""
    finding = {
        "title": "SQL injection in login",
        "raw_severity": "high",
        "status": "in_progress",
        "asset_label": "auth-service",
        "source_type": "burp",
    }
    doc = ContextDocument.generate(
        finding,
        enrichment={"summary": "SQLi via user input", "cvss_score": 8.5},
        ownership={"recommended_owner": "backend-team", "confidence": 90},
        exposure={"reachable": "confirmed", "blast_radius": "user data"},
        evidence={
            "affected_files": [{"path": "app/login.py", "line": 42, "context": "raw SQL"}],
            "fix_safety": "code_fix",
        },
        plan={"plan_steps": ["Parameterize queries", "Add WAF rule"]},
        remediation={"status": "pr_created", "pr_url": "https://github.com/org/repo/pull/42"},
        validation={"verdict": "fixed", "recommendation": "close"},
    )
    assert "SQL injection" in doc
    assert "What we know so far" in doc
    assert "backend-team" in doc
    assert "Evidence" in doc
    assert "app/login.py" in doc
    assert "Current plan" in doc
    assert "Parameterize queries" in doc
    assert "Remediation" in doc
    assert "pr_created" in doc
    assert "All agents have run" in doc


