"""Unit tests for the read-only grep tool (ADR-0052 §3)."""

from __future__ import annotations

import pytest

from cliff.agents.runtime.tools.grep import search_workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def run():\n    eval(user_input)\n")
    (tmp_path / "app" / "safe.py").write_text("x = 1\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("eval secret\n")
    return tmp_path


def test_finds_matches_with_file_line(ws):
    out = search_workspace(str(ws), r"eval\(")
    assert "app/main.py:2:" in out
    assert "eval(user_input)" in out


def test_no_matches(ws):
    out = search_workspace(str(ws), "nonexistent_symbol")
    assert "[no matches" in out


def test_skips_dot_git(ws):
    # The .git/config line also contains "eval" but must be skipped.
    out = search_workspace(str(ws), "eval")
    assert ".git" not in out
    assert "app/main.py" in out


def test_invalid_regex_is_reported(ws):
    out = search_workspace(str(ws), "(unclosed")
    assert "[invalid regex" in out


def test_path_escape_refused(ws):
    out = search_workspace(str(ws), "x", path="../../../etc")
    assert "[refused" in out


def test_scoped_path(ws):
    out = search_workspace(str(ws), "x = 1", path="app")
    assert "app/safe.py" in out
