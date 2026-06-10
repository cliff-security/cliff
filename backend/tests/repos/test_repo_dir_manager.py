"""Unit tests for the per-repo Project-profile store (ADR-0053 §2)."""

from __future__ import annotations

import pytest

from cliff.repos.repo_dir_manager import SCHEMA_VERSION, RepoDirManager

RID = "abc123def"


@pytest.fixture
def mgr(tmp_path):
    return RepoDirManager(tmp_path / "repos")


def test_artifact_round_trip(mgr):
    mgr.write_artifact(RID, "profile", {"kind": "service", "internet_facing": True})
    assert mgr.read_artifact(RID, "profile") == {
        "kind": "service",
        "internet_facing": True,
    }


def test_read_missing_artifact_is_none(mgr):
    assert mgr.read_artifact(RID, "profile") is None


def test_unknown_artifact_rejected(mgr):
    with pytest.raises(ValueError, match="Unknown profile artifact"):
        mgr.write_artifact(RID, "bogus", {})


def test_write_is_atomic_no_tmp_left(mgr):
    mgr.write_artifact(RID, "code_map", {"ships_roots": ["src/**"]})
    root = mgr.ensure(RID)
    # No half-written temp file survives; the committed file parses.
    assert not list(root.glob("*.tmp"))
    assert mgr.read_artifact(RID, "code_map") == {"ships_roots": ["src/**"]}


def test_overwrite_replaces_cleanly(mgr):
    mgr.write_artifact(RID, "threat", {"prior_issues": []})
    mgr.write_artifact(RID, "threat", {"prior_issues": [{"id": "CVE-1"}]})
    assert mgr.read_artifact(RID, "threat") == {"prior_issues": [{"id": "CVE-1"}]}


@pytest.mark.parametrize("bad", ["", "../escape", "a/b", "..", "x\\y"])
def test_path_traversal_rejected(mgr, bad):
    with pytest.raises(ValueError):
        mgr.write_artifact(bad, "profile", {})


def test_clone_dir_is_under_repo_root(mgr):
    clone = mgr.clone_dir(RID)
    assert clone.name == "repo"
    assert clone.parent == mgr.ensure(RID)


# ── manifest ────────────────────────────────────────────────────────────────


def test_manifest_lists_present_artifacts(mgr):
    mgr.write_artifact(RID, "profile", {"kind": "library"})
    mgr.write_artifact(RID, "threat", {"prior_issues": []})
    manifest = mgr.write_manifest(RID, source_sha="deadbeef", built_at="2026-06-10T00:00:00Z")
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["source_sha"] == "deadbeef"
    assert set(manifest["artifacts"]) == {"profile", "threat"}
    assert "code_map" not in manifest["artifacts"]
    assert mgr.read_manifest(RID) == manifest


def test_read_manifest_missing_is_none(mgr):
    assert mgr.read_manifest(RID) is None


# ── lazy PROFILE.md ───────────────────────────────────────────────────────────


def test_profile_md_is_lazy_not_written_on_artifact_write(mgr):
    mgr.write_artifact(RID, "profile", {"kind": "service"})
    # Writing an artifact must NOT regenerate the digest (it's lazy + can be big).
    assert not mgr.profile_md_path(RID).exists()


def test_regenerate_profile_md_builds_readable_digest(mgr):
    mgr.write_artifact(RID, "profile", {"kind": "self_hosted_app", "internet_facing": True})
    mgr.regenerate_profile_md(RID)
    text = mgr.profile_md_path(RID).read_text()
    assert text.startswith("# Project profile")
    assert "self_hosted_app" in text
    assert "internet_facing" in text


def test_regenerate_profile_md_empty_when_no_artifacts(mgr):
    mgr.regenerate_profile_md(RID)
    assert "No profile built yet" in mgr.profile_md_path(RID).read_text()


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_removes_store(mgr):
    mgr.write_artifact(RID, "profile", {"kind": "cli"})
    assert mgr.delete(RID) is True
    assert mgr.read_artifact(RID, "profile") is None
    assert mgr.delete(RID) is False
