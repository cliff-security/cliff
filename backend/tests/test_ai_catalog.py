"""Tests for the AI provider catalog (IMPL-0011 Phase A4)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from opensec.ai import catalog

if TYPE_CHECKING:
    from opensec.ai.models import AIProvider


@pytest.fixture(autouse=True)
def _reset_override_state(monkeypatch):
    # Make sure each test starts with a clean override env + reset the once-flag.
    for provider in catalog.all_providers():
        monkeypatch.delenv(
            f"OPENSEC_AI_MODEL_OVERRIDE_{provider.upper()}", raising=False
        )
    catalog._reset_for_tests()
    yield
    catalog._reset_for_tests()


def test_every_provider_has_entry() -> None:
    providers: list[AIProvider] = ["openrouter", "anthropic", "openai", "custom"]
    for p in providers:
        info = catalog.get(p)
        assert info.env_var_name
        # custom has no default model; everything else does.
        if p == "custom":
            assert info.default_model is None
        else:
            assert info.default_model


def test_env_var_names_match_opencode_expectations() -> None:
    assert catalog.env_var_name("openrouter") == "OPENROUTER_API_KEY"
    assert catalog.env_var_name("anthropic") == "ANTHROPIC_API_KEY"
    assert catalog.env_var_name("openai") == "OPENAI_API_KEY"


def test_resolve_model_returns_default_when_no_override() -> None:
    # OpenCode resolves model IDs as <provider>/<model> — for OpenRouter
    # that means an extra ``openrouter/`` prefix so OpenCode dispatches
    # via its OpenRouter provider rather than its Anthropic one.
    assert (
        catalog.resolve_model("openrouter")
        == "openrouter/anthropic/claude-sonnet-4.6"
    )
    assert catalog.resolve_model("anthropic") == "anthropic/claude-sonnet-4-6"
    assert catalog.resolve_model("openai") == "openai/gpt-5"
    assert catalog.resolve_model("custom") is None


def test_resolve_model_uses_override_when_set(monkeypatch) -> None:
    monkeypatch.setenv("OPENSEC_AI_MODEL_OVERRIDE_ANTHROPIC", "claude-opus-4-1")
    assert catalog.resolve_model("anthropic") == "claude-opus-4-1"
    # Untouched providers stay on their defaults.
    assert (
        catalog.resolve_model("openrouter")
        == "openrouter/anthropic/claude-sonnet-4.6"
    )


def test_resolve_model_ignores_blank_override(monkeypatch) -> None:
    monkeypatch.setenv("OPENSEC_AI_MODEL_OVERRIDE_OPENAI", "   ")
    assert catalog.resolve_model("openai") == "openai/gpt-5"


def test_has_override_reflects_env(monkeypatch) -> None:
    assert catalog.has_override("anthropic") is False
    monkeypatch.setenv("OPENSEC_AI_MODEL_OVERRIDE_ANTHROPIC", "claude-opus-4-1")
    assert catalog.has_override("anthropic") is True


def test_log_override_warning_emits_once_per_override(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENSEC_AI_MODEL_OVERRIDE_OPENROUTER", "openai/gpt-4o")
    monkeypatch.setenv("OPENSEC_AI_MODEL_OVERRIDE_OPENAI", "gpt-4-turbo")

    with caplog.at_level(logging.WARNING):
        catalog.log_override_warnings_once()

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("openrouter" in w and "openai/gpt-4o" in w for w in warnings)
    assert any("openai" in w and "gpt-4-turbo" in w for w in warnings)


def test_log_override_warning_does_not_repeat(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENSEC_AI_MODEL_OVERRIDE_ANTHROPIC", "claude-opus-4-1")

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
