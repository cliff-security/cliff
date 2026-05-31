"""Provider factory tests — covers the six provider branches + error modes."""

from __future__ import annotations

import pytest

from cliff.agents.runtime.provider import (
    OLLAMA_DEFAULT_BASE_URL,
    OPENROUTER_BASE_URL,
    ProviderConfigurationError,
    build_model,
)


class TestProviderFactory:
    """Each provider prefix in the canonical model id selects the right model."""

    def test_openrouter_uses_openai_chat_model_with_or_base_url(self):
        model = build_model(
            {"OPENROUTER_API_KEY": "sk-or-fake"},
            "openrouter/anthropic/claude-haiku-4.5",
        )
        assert type(model).__name__ == "OpenAIChatModel"
        # Model id strips the leading "openrouter/" — keeps the sub-namespace
        # OpenRouter expects on the wire.
        assert "claude-haiku-4.5" in model.model_name
        assert "anthropic/" in model.model_name
        assert model.base_url.startswith(OPENROUTER_BASE_URL)

    def test_anthropic_uses_anthropic_model(self):
        model = build_model(
            {"ANTHROPIC_API_KEY": "sk-ant-fake"},
            "anthropic/claude-haiku-4-5",
        )
        assert type(model).__name__ == "AnthropicModel"
        assert model.model_name == "claude-haiku-4-5"

    def test_openai_uses_openai_chat_model(self):
        model = build_model({"OPENAI_API_KEY": "sk-fake"}, "openai/gpt-5")
        assert type(model).__name__ == "OpenAIChatModel"
        assert model.model_name == "gpt-5"

    def test_openai_with_custom_base_url(self):
        model = build_model(
            {
                "OPENAI_API_KEY": "sk-fake",
                "OPENAI_BASE_URL": "https://proxy.example/v1",
            },
            "openai/gpt-5",
        )
        assert model.base_url.startswith("https://proxy.example/")

    def test_google_uses_google_model(self):
        model = build_model(
            {"GEMINI_API_KEY": "AIza-fake"}, "google/gemini-2.5-flash"
        )
        assert type(model).__name__ == "GoogleModel"
        assert model.model_name == "gemini-2.5-flash"

    def test_ollama_uses_openai_chat_model_with_ollama_base_url(self):
        model = build_model(
            {"OLLAMA_BASE_URL": "http://localhost:11434"}, "ollama/llama3.1"
        )
        assert type(model).__name__ == "OpenAIChatModel"
        # Ollama dispatches by OpenAI-compatible /v1 endpoint (PA appends
        # the trailing slash on the base URL).
        assert "/v1" in model.base_url

    def test_ollama_default_base_url_when_env_missing(self):
        model = build_model({}, "ollama/llama3")
        assert OLLAMA_DEFAULT_BASE_URL in model.base_url

    def test_custom_provider_requires_base_url(self):
        with pytest.raises(ProviderConfigurationError) as exc:
            build_model({"OPENAI_API_KEY": "sk-fake"}, "custom/my-model")
        assert "base URL" in str(exc.value)

    def test_custom_provider_uses_openai_chat_model(self):
        model = build_model(
            {
                "OPENAI_API_KEY": "sk-fake",
                "OPENAI_BASE_URL": "https://my.api/v1",
            },
            "custom/my-model",
        )
        assert type(model).__name__ == "OpenAIChatModel"
        assert model.base_url.startswith("https://my.api/")
        assert model.model_name == "my-model"


class TestProviderFactoryErrors:
    """Failure modes the caller surfaces verbatim to the user."""

    def test_no_model_id(self):
        with pytest.raises(ProviderConfigurationError) as exc:
            build_model({}, None)
        assert "No active AI model configured" in str(exc.value)

    def test_missing_slash_in_model_id(self):
        with pytest.raises(ProviderConfigurationError) as exc:
            build_model({}, "bogus")
        assert "<provider>/<model>" in str(exc.value)

    def test_missing_api_key_per_provider(self):
        for prefix, env_key in [
            ("openrouter", "OPENROUTER_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("google", "GEMINI_API_KEY"),
        ]:
            with pytest.raises(ProviderConfigurationError) as exc:
                build_model({}, f"{prefix}/some-model")
            assert env_key in str(exc.value)

    def test_unknown_provider_prefix(self):
        with pytest.raises(ProviderConfigurationError) as exc:
            build_model({}, "azure-openai/gpt-5")
        assert "Unknown provider prefix" in str(exc.value)
