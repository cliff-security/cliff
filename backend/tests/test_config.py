"""Tests for application configuration."""

from __future__ import annotations

from cliff.config import Settings, _find_repo_root


def test_default_settings():
    s = Settings()
    assert s.app_host == "0.0.0.0"
    assert s.app_port == 8000


def test_resolve_data_dir_creates(tmp_path):
    s = Settings(data_dir=tmp_path / "test_data")
    result = s.resolve_data_dir()
    assert result.exists()
    assert result == tmp_path / "test_data"


def test_find_repo_root():
    root = _find_repo_root()
    assert (root / "VERSION").exists()


def test_demo_field_defaults_to_false():
    s = Settings()
    assert s.demo is False


def test_demo_field_settable():
    s = Settings(demo=True)
    assert s.demo is True
