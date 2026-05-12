"""Tests for the auto-detect scanner (IMPL-0011 Phase B1).

All tests monkeypatch ``Path.home()`` to ``tmp_path`` and clear the four
env vars the scanner reads, so the developer's real environment never
contaminates the test.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from opensec.ai import autodetect

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    """Pretend ``$HOME`` is empty and no key env vars are set."""
    monkeypatch.setattr(autodetect, "_home", lambda: tmp_path)
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Source 1 — ~/.claude/.credentials.json
# ---------------------------------------------------------------------------


def test_claude_credentials_top_level_key(tmp_path) -> None:
    _write(
        tmp_path / ".claude" / ".credentials.json",
        json.dumps({"anthropic_api_key": "sk-ant-abc"}),
    )
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "anthropic"
    assert result.raw_key == "sk-ant-abc"
    assert ".claude/.credentials.json" in result.source


def test_claude_credentials_accounts_nested(tmp_path) -> None:
    _write(
        tmp_path / ".claude" / ".credentials.json",
        json.dumps({"accounts": [{"api_key": "sk-ant-nested"}]}),
    )
    result = autodetect.scan()
    assert result is not None
    assert result.raw_key == "sk-ant-nested"


def test_claude_credentials_malformed_json_returns_none(tmp_path) -> None:
    _write(tmp_path / ".claude" / ".credentials.json", "{this is not json")
    assert autodetect.scan() is None


def test_claude_credentials_unrelated_json_returns_none(tmp_path) -> None:
    _write(
        tmp_path / ".claude" / ".credentials.json", json.dumps({"foo": "bar"})
    )
    assert autodetect.scan() is None


# ---------------------------------------------------------------------------
# Source 2-4 — env vars
# ---------------------------------------------------------------------------


def test_anthropic_env_var(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env")
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "anthropic"
    assert result.raw_key == "sk-ant-env"
    assert result.source == "ANTHROPIC_API_KEY env"


def test_openrouter_env_var(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "openrouter"


def test_openai_env_var(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-env")
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "openai"


def test_blank_env_var_is_ignored(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert autodetect.scan() is None


# ---------------------------------------------------------------------------
# Source 5 — ~/.aider/.env
# ---------------------------------------------------------------------------


def test_aider_env_anthropic(tmp_path) -> None:
    _write(
        tmp_path / ".aider" / ".env",
        "# Aider env\nANTHROPIC_API_KEY=sk-ant-aider\nOPENAI_API_KEY=sk-openai-aider\n",
    )
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "anthropic"
    assert result.raw_key == "sk-ant-aider"


def test_aider_env_quoted_value(tmp_path) -> None:
    _write(tmp_path / ".aider" / ".env", 'OPENAI_API_KEY="sk-openai-quoted"\n')
    result = autodetect.scan()
    assert result is not None
    assert result.raw_key == "sk-openai-quoted"


def test_aider_env_ignores_comments(tmp_path) -> None:
    _write(
        tmp_path / ".aider" / ".env",
        "# OPENAI_API_KEY=sk-commented\nOPENROUTER_API_KEY=sk-or-real\n",
    )
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "openrouter"
    assert result.raw_key == "sk-or-real"


# ---------------------------------------------------------------------------
# Source 6 — ~/.config/openai/
# ---------------------------------------------------------------------------


def test_openai_config_auth_json(tmp_path) -> None:
    _write(
        tmp_path / ".config" / "openai" / "auth.json",
        json.dumps({"api_key": "sk-openai-conf"}),
    )
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "openai"
    assert result.raw_key == "sk-openai-conf"


def test_openai_config_ini_style(tmp_path) -> None:
    _write(
        tmp_path / ".config" / "openai" / "config",
        "OPENAI_API_KEY=sk-openai-ini\n",
    )
    result = autodetect.scan()
    assert result is not None
    assert result.raw_key == "sk-openai-ini"


def test_openai_config_malformed_returns_none(tmp_path) -> None:
    _write(tmp_path / ".config" / "openai" / "auth.json", "garbage{}{")
    assert autodetect.scan() is None


# ---------------------------------------------------------------------------
# Priority order
# ---------------------------------------------------------------------------


def test_priority_claude_beats_env(tmp_path, monkeypatch) -> None:
    _write(
        tmp_path / ".claude" / ".credentials.json",
        json.dumps({"anthropic_api_key": "sk-from-claude"}),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    result = autodetect.scan()
    assert result is not None
    assert result.raw_key == "sk-from-claude"


def test_priority_anthropic_env_beats_openrouter_env(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-wins")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-loses")
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "anthropic"


def test_priority_env_beats_aider_file(tmp_path, monkeypatch) -> None:
    _write(
        tmp_path / ".aider" / ".env", "ANTHROPIC_API_KEY=sk-from-aider\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env-wins")
    result = autodetect.scan()
    assert result is not None
    assert result.provider == "openai"


def test_priority_aider_beats_openai_config_dir(tmp_path) -> None:
    _write(
        tmp_path / ".aider" / ".env", "ANTHROPIC_API_KEY=sk-from-aider-wins\n"
    )
    _write(
        tmp_path / ".config" / "openai" / "auth.json",
        json.dumps({"api_key": "sk-from-openai-conf"}),
    )
    result = autodetect.scan()
    assert result is not None
    assert result.source.endswith(".aider/.env")


# ---------------------------------------------------------------------------
# No keys anywhere
# ---------------------------------------------------------------------------


def test_returns_none_when_nothing_found() -> None:
    assert autodetect.scan() is None
