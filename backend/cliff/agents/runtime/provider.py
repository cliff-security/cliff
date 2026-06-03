"""Pydantic AI ``Model`` factory keyed off Cliff's canonical AI state.

ADR-0047 amends ADR-0037: the dual-path (env-vars + auth.json) collapses
to a single in-process provider instantiation. This module is the one
seam between Cliff's canonical state and Pydantic AI's model surface.

Inputs (both come from the app-level AI-state resolvers):

* ``env`` — the dict ``AIIntegrationService.resolve_env_for_workspace``
  produces. Contains the API-key env var for the active provider and,
  for URL-dispatched providers, the matching ``*_BASE_URL``.
* ``model_full_id`` — ``AIIntegrationService.resolve_model_for_workspace``
  output. Always ``<provider-prefix>/<model id>`` (e.g.
  ``"anthropic/claude-haiku-4-5"``, ``"openrouter/anthropic/claude-haiku-4.5"``).

The factory is intentionally pure: no DB, no vault, no I/O. Tests pass
fake env+id pairs and assert the right ``Model`` subclass + provider
shape; ``main.py`` (or per-request route handlers) call it with the
real resolved values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from pydantic_ai.models import Model

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"


class ProviderConfigurationError(ValueError):
    """Raised when canonical AI state is missing or inconsistent."""


def build_model(env: dict[str, str], model_full_id: str | None) -> Model:
    """Build a Pydantic AI ``Model`` from Cliff's canonical AI state.

    Raises :class:`ProviderConfigurationError` for the four failure
    modes the caller can act on (no model configured, malformed id,
    missing key, missing base_url for a URL-dispatched provider).
    """
    if not model_full_id:
        raise ProviderConfigurationError(
            "No active AI model configured — connect a provider in "
            "Settings → AI provider."
        )
    if "/" not in model_full_id:
        raise ProviderConfigurationError(
            f"Model id must be '<provider>/<model>', got {model_full_id!r}."
        )

    provider_prefix, _, model_id = model_full_id.partition("/")

    if provider_prefix == "openrouter":
        api_key = env.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ProviderConfigurationError(
                "OPENROUTER_API_KEY missing — reconnect OpenRouter in "
                "Settings → AI provider."
            )
        return OpenAIChatModel(
            model_id,
            provider=OpenAIProvider(
                base_url=OPENROUTER_BASE_URL, api_key=api_key
            ),
        )

    if provider_prefix == "anthropic":
        api_key = env.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ProviderConfigurationError(
                "ANTHROPIC_API_KEY missing — reconnect Anthropic in "
                "Settings → AI provider."
            )
        return AnthropicModel(
            model_id, provider=AnthropicProvider(api_key=api_key)
        )

    if provider_prefix == "openai":
        api_key = env.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ProviderConfigurationError(
                "OPENAI_API_KEY missing — reconnect OpenAI in "
                "Settings → AI provider."
            )
        base_url = env.get("OPENAI_BASE_URL")
        return OpenAIChatModel(
            model_id,
            provider=OpenAIProvider(api_key=api_key, base_url=base_url),
        )

    if provider_prefix == "google":
        api_key = env.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ProviderConfigurationError(
                "GEMINI_API_KEY missing — reconnect Google AI Studio in "
                "Settings → AI provider."
            )
        return GoogleModel(
            model_id, provider=GoogleProvider(api_key=api_key)
        )

    if provider_prefix == "ollama":
        base_url = env.get("OLLAMA_BASE_URL", OLLAMA_DEFAULT_BASE_URL).rstrip(
            "/"
        )
        # Ollama doesn't authenticate; the OpenAI client refuses an
        # empty api_key string, so use the conventional ``"ollama"``
        # placeholder.
        return OpenAIChatModel(
            model_id,
            provider=OpenAIProvider(
                base_url=f"{base_url}/v1", api_key="ollama"
            ),
        )

    if provider_prefix == "custom":
        api_key = env.get("OPENAI_API_KEY", "")
        base_url = env.get("OPENAI_BASE_URL")
        if not base_url:
            raise ProviderConfigurationError(
                "Custom provider needs a base URL — set it in "
                "Settings → AI provider."
            )
        if not api_key:
            raise ProviderConfigurationError(
                "Custom provider needs an API key — set it in "
                "Settings → AI provider."
            )
        return OpenAIChatModel(
            model_id,
            provider=OpenAIProvider(api_key=api_key, base_url=base_url),
        )

    raise ProviderConfigurationError(
        f"Unknown provider prefix {provider_prefix!r} in model id "
        f"{model_full_id!r}."
    )


__all__ = [
    "OLLAMA_DEFAULT_BASE_URL",
    "OPENROUTER_BASE_URL",
    "ProviderConfigurationError",
    "build_model",
]
