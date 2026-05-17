"""Tests for the AI provider catalog (IMPL-0011 Phase A4)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from cliff.ai import catalog

if TYPE_CHECKING:
    from cliff.ai.models import AIProvider


@pytest.fixture(autouse=True)
def _reset_override_state(monkeypatch):
    # Make sure each test starts with a clean override env + reset the once-flag.
    for provider in catalog.all_providers():
        monkeypatch.delenv(
            f"CLIFF_AI_MODEL_OVERRIDE_{provider.upper()}", raising=False
        )
    catalog._reset_for_tests()
    yield
    catalog._reset_for_tests()


def test_every_provider_has_entry() -> None:
    providers: list[AIProvider] = [
        "openrouter",
        "anthropic",
        "openai",
        "google",
        "ollama",
        "custom",
    ]
    for p in providers:
        info = catalog.get(p)
        # Ollama has no API key; everything else does.
        if p == "ollama":
            assert info.env_var_name is None
            assert info.base_url_env_var == "OLLAMA_BASE_URL"
        else:
            assert info.env_var_name
        # custom + ollama have no default model; everything else does.
        if p in ("custom", "ollama"):
            assert info.default_model is None
        else:
            assert info.default_model


def test_env_var_names_match_opencode_expectations() -> None:
    assert catalog.env_var_name("openrouter") == "OPENROUTER_API_KEY"
    assert catalog.env_var_name("anthropic") == "ANTHROPIC_API_KEY"
    assert catalog.env_var_name("openai") == "OPENAI_API_KEY"
    assert catalog.env_var_name("google") == "GEMINI_API_KEY"
    assert catalog.env_var_name("ollama") is None


def test_provider_env_var_names_covers_keys_and_base_urls() -> None:
    """Both the ``*_API_KEY`` and ``*_BASE_URL`` of every provider are
    listed — callers scrub these from the host env before spawning
    OpenCode so a polluted host (e.g. Claude Desktop's ANTHROPIC_BASE_URL)
    can't leak in. (QA Q01 B07.)"""
    names = catalog.provider_env_var_names()
    assert "ANTHROPIC_API_KEY" in names
    assert "ANTHROPIC_BASE_URL" in names
    assert "OPENAI_API_KEY" in names
    assert "OPENAI_BASE_URL" in names
    assert "OPENROUTER_API_KEY" in names
    assert "OPENROUTER_BASE_URL" in names
    # Google + Ollama additions (ADR-0037).
    assert "GEMINI_API_KEY" in names
    assert "GEMINI_BASE_URL" in names
    assert "OLLAMA_BASE_URL" in names


def test_ollama_carries_default_base_url() -> None:
    """Ollama's ``base_url_env_var`` + ``default_base_url`` is the only place
    an Ollama config exists by default — the env injector relies on this
    to point OpenCode at localhost without a user config touch."""
    assert catalog.base_url_env_var("ollama") == "OLLAMA_BASE_URL"
    assert catalog.default_base_url("ollama") == "http://localhost:11434"


def test_resolve_model_returns_default_when_no_override() -> None:
    # OpenCode resolves model IDs as <provider>/<model> — for OpenRouter
    # that means an extra ``openrouter/`` prefix so OpenCode dispatches
    # via its OpenRouter provider rather than its Anthropic one.
    assert (
        catalog.resolve_model("openrouter")
        == "openrouter/anthropic/claude-haiku-4.5"
    )
    assert catalog.resolve_model("anthropic") == "anthropic/claude-haiku-4-5"
    assert catalog.resolve_model("openai") == "openai/gpt-5"
    assert catalog.resolve_model("google") == "google/gemini-2.5-flash"
    assert catalog.resolve_model("ollama") is None
    assert catalog.resolve_model("custom") is None


def test_resolve_model_uses_override_when_set(monkeypatch) -> None:
    monkeypatch.setenv("CLIFF_AI_MODEL_OVERRIDE_ANTHROPIC", "claude-opus-4-1")
    assert catalog.resolve_model("anthropic") == "claude-opus-4-1"
    # Untouched providers stay on their defaults.
    assert (
        catalog.resolve_model("openrouter")
        == "openrouter/anthropic/claude-haiku-4.5"
    )


def test_resolve_model_ignores_blank_override(monkeypatch) -> None:
    monkeypatch.setenv("CLIFF_AI_MODEL_OVERRIDE_OPENAI", "   ")
    assert catalog.resolve_model("openai") == "openai/gpt-5"


def test_has_override_reflects_env(monkeypatch) -> None:
    assert catalog.has_override("anthropic") is False
    monkeypatch.setenv("CLIFF_AI_MODEL_OVERRIDE_ANTHROPIC", "claude-opus-4-1")
    assert catalog.has_override("anthropic") is True


def test_log_override_warning_emits_once_per_override(monkeypatch, caplog) -> None:
    monkeypatch.setenv("CLIFF_AI_MODEL_OVERRIDE_OPENROUTER", "openai/gpt-4o")
    monkeypatch.setenv("CLIFF_AI_MODEL_OVERRIDE_OPENAI", "gpt-4-turbo")

    with caplog.at_level(logging.WARNING):
        catalog.log_override_warnings_once()

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("openrouter" in w and "openai/gpt-4o" in w for w in warnings)
    assert any("openai" in w and "gpt-4-turbo" in w for w in warnings)


def test_log_override_warning_does_not_repeat(monkeypatch, caplog) -> None:
    monkeypatch.setenv("CLIFF_AI_MODEL_OVERRIDE_ANTHROPIC", "claude-opus-4-1")

    with caplog.at_level(logging.WARNING):
        catalog.log_override_warnings_once()
        first_warning_count = len(caplog.records)
        catalog.log_override_warnings_once()
        second_warning_count = len(caplog.records)

    assert first_warning_count == second_warning_count


def test_log_override_warning_emits_nothing_when_no_overrides(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        catalog.log_override_warnings_once()
    assert all("override active" not in r.message for r in caplog.records)
