"""Tests for application configuration."""

from __future__ import annotations

from pathlib import Path

from cliff.config import Settings, _find_repo_root


def test_default_settings():
    s = Settings()
    assert s.app_host == "0.0.0.0"
    assert s.app_port == 8000
    assert s.opencode_host == "127.0.0.1"
    assert s.opencode_port == 4096


def test_opencode_url_property():
    s = Settings()
    assert s.opencode_url == "http://127.0.0.1:4096"

    s2 = Settings(opencode_host="10.0.0.1", opencode_port=9999)
    assert s2.opencode_url == "http://10.0.0.1:9999"


def test_opencode_version_reads_file():
    s = Settings()
    # The repo has .opencode-version with "1.3.2"
    version = s.opencode_version
    assert version  # not empty
    assert "." in version  # looks like a semver


def test_opencode_binary_path_with_explicit_bin():
    s = Settings(opencode_bin="/usr/local/bin/opencode")
    assert s.opencode_binary_path == Path("/usr/local/bin/opencode")


def test_resolve_data_dir_creates(tmp_path):
    s = Settings(data_dir=tmp_path / "test_data")
    result = s.resolve_data_dir()
    assert result.exists()
    assert result == tmp_path / "test_data"


def test_find_repo_root():
    root = _find_repo_root()
    assert (root / ".opencode-version").exists()


def test_demo_field_defaults_to_false():
    s = Settings()
    assert s.demo is False


def test_demo_field_settable():
    s = Settings(demo=True)
    assert s.demo is True
