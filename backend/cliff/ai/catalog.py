"""Provider catalog — per-provider defaults, env vars, console URLs.

Single source of truth for the small static facts about each provider Cliff
supports for AI integration (ADR-0037). Resolve-time helpers honor per-provider
env-var overrides (``CLIFF_AI_MODEL_OVERRIDE_<PROVIDER>``) and log a startup
warning when any override is active.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cliff.ai.models import AIProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderInfo:
    """Static facts about one provider.

    ``env_var_name`` is the API-key env var the model factory reads for the
    provider. For ``ollama`` (no API key) it's ``None``. ``base_url_env_var``
    and ``default_base_url`` cover providers dispatched by base URL instead
    of by hard-coded host (today: ``ollama`` always, ``custom`` when the
    user supplies a URL).
    """

    env_var_name: str | None
    default_model: str | None
    console_url: str
    key_hint: str | None
    docs_label: str
    base_url_env_var: str | None = None
    default_base_url: str | None = None


# Model ids use Cliff's ``<provider>/<model-id>`` namespace (the model
# factory in ``runtime/provider.py`` partitions on the first ``/`` to pick
# the provider branch). For OpenRouter that means an extra ``openrouter/``
# prefix in front of OpenRouter's own ``<route-provider>/<model>``
# identifier — without it the factory would take the ``anthropic`` branch
# and expect ``ANTHROPIC_API_KEY``.
_CATALOG: dict[AIProvider, ProviderInfo] = {
    "openrouter": ProviderInfo(
        env_var_name="OPENROUTER_API_KEY",
        # Claude Haiku 4.5 via OpenRouter — Anthropic's cheapest
        # current-generation model, broad coverage, and *stable* (not a
        # preview tag that can be pulled or renamed by the provider).
        # L5 (architect review): defaulting to a preview model was a
        # single point of failure for first-run UX — if Tencent pulled
        # ``tencent/hy3-preview`` every new install would 404. Tencent
        # Hy3 stays available via the picker for cost-sensitive users.
        default_model="openrouter/anthropic/claude-haiku-4.5",
        console_url="https://openrouter.ai/keys",
        key_hint="sk-or-",
        docs_label="OpenRouter",
    ),
    "anthropic": ProviderInfo(
        env_var_name="ANTHROPIC_API_KEY",
        # Haiku 4.5 — Anthropic's cheapest current-generation model.
        # Picks up the lions share of agent traffic at ~5× lower cost
        # than Sonnet, and works fine for plan / enrich / validate
        # passes. Operators who want Sonnet override via the UI picker.
        default_model="anthropic/claude-haiku-4-5",
        console_url="https://console.anthropic.com/settings/keys",
        key_hint="sk-ant-",
        docs_label="Anthropic",
    ),
    "openai": ProviderInfo(
        env_var_name="OPENAI_API_KEY",
        default_model="openai/gpt-5",
        console_url="https://platform.openai.com/api-keys",
        key_hint="sk-",
        docs_label="OpenAI",
    ),
    "google": ProviderInfo(
        env_var_name="GEMINI_API_KEY",
        # Gemini 2.5 Flash — covered by the AI Studio free tier with
        # generous quotas, plenty of capability for enrichment + plan.
        default_model="google/gemini-2.5-flash",
        console_url="https://aistudio.google.com/apikey",
        key_hint="AIza",
        docs_label="Google AI Studio",
    ),
    "ollama": ProviderInfo(
        # Ollama needs no API key — Cliff talks to it over the
        # OpenAI-compatible /v1 endpoint on a local port. Leaving
        # env_var_name None makes resolve_env_for_workspace skip the
        # key-injection branch; we still emit OLLAMA_BASE_URL so the model
        # factory points at the right host.
        env_var_name=None,
        # No default model — Ollama's available models depend on what
        # the user has pulled locally. The picker queries /api/tags and
        # presents the live list, which the user then chooses from.
        default_model=None,
        console_url="https://ollama.com/library",
        key_hint=None,
        docs_label="Local (Ollama)",
        base_url_env_var="OLLAMA_BASE_URL",
        default_base_url="http://localhost:11434",
    ),
    "custom": ProviderInfo(
        env_var_name="OPENAI_API_KEY",  # OpenAI-compatible — shares the env name
        default_model=None,  # user must specify
        console_url="",  # provider-defined
        key_hint=None,
        docs_label="Custom (OpenAI-compatible)",
        base_url_env_var="OPENAI_BASE_URL",
    ),
}


def get(provider: AIProvider) -> ProviderInfo:
    """Return the catalog entry for *provider* — raises KeyError on unknown."""
    return _CATALOG[provider]


def env_var_name(provider: AIProvider) -> str | None:
    """The API-key env var the model factory reads for this provider.

    Returns ``None`` for providers that use no API key (``ollama``).
    """
    return _CATALOG[provider].env_var_name


def base_url_env_var(provider: AIProvider) -> str | None:
    """The base-URL env var the model factory reads, if applicable."""
    return _CATALOG[provider].base_url_env_var


def default_base_url(provider: AIProvider) -> str | None:
    """The default base URL for providers that dispatch by URL (Ollama)."""
    return _CATALOG[provider].default_base_url


def all_providers() -> list[AIProvider]:
    """Stable order of supported providers (used by tests and admin views)."""
    return list(_CATALOG.keys())


def _override_env_var(provider: AIProvider) -> str:
    return f"CLIFF_AI_MODEL_OVERRIDE_{provider.upper()}"


def resolve_model(provider: AIProvider) -> str | None:
    """Return the model name Cliff should configure for *provider*.

    DEV-ONLY: ``CLIFF_AI_MODEL_OVERRIDE_<PROVIDER>`` env vars still win
    when set, so CI / local dev can pin a model without touching the DB.
    Production UI no longer exposes this override (ADR-0037) — model
    choice is the canonical ``app_setting(model)`` written via the UI
    picker. Workspace spawns resolve through
    :func:`AIIntegrationService.resolve_model_for_workspace`, which reads
    the canonical setting first; this helper is used only as the fallback
    when the canonical setting is absent (first connect of a fresh
    install).
    """
    override = os.environ.get(_override_env_var(provider), "").strip()
    if override:
        return override
    return _CATALOG[provider].default_model


def has_override(provider: AIProvider) -> bool:
    """True if a model-override env var is set for *provider*."""
    return bool(os.environ.get(_override_env_var(provider), "").strip())


# ---------------------------------------------------------------------------
# Picker entries (M10) — static suggestion list per provider.
#
# This used to live in ``api/routes/ai_integrations.py``; it's identical-
# kind metadata to ``ProviderInfo.default_model`` so it belongs next to
# the catalog. The Ollama and Custom entries stay empty here because the
# picker fetches Ollama's live ``/api/tags`` and Custom is user-supplied.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PickerOption:
    """One row in the model picker."""

    id: str
    label: str
    description: str | None


_PICKER: dict[AIProvider, list[PickerOption]] = {
    "openrouter": [
        # Claude Haiku 4.5 is the new default (L5 — see catalog entry).
        PickerOption(
            id="openrouter/anthropic/claude-haiku-4.5",
            label="Claude Haiku 4.5",
            description="Anthropic via OpenRouter — fast, cheap, broad coverage. Default.",
        ),
        PickerOption(
            id="openrouter/tencent/hy3-preview",
            label="Tencent Hy3 (preview)",
            description="262K context, ~50× cheaper than Sonnet. Preview tag — may move.",
        ),
        PickerOption(
            id="openrouter/anthropic/claude-sonnet-4.5",
            label="Claude Sonnet 4.5",
            description="Anthropic's current flagship for security reasoning.",
        ),
        PickerOption(
            id="openrouter/openai/gpt-5",
            label="GPT-5",
            description="OpenAI's flagship via OpenRouter.",
        ),
        PickerOption(
            id="openrouter/google/gemini-2.5-flash",
            label="Gemini 2.5 Flash",
            description="Google's cheap workhorse via OpenRouter.",
        ),
        PickerOption(
            id="openrouter/deepseek/deepseek-chat",
            label="DeepSeek Chat",
            description="Strong open-weight model at very low cost.",
        ),
    ],
    "anthropic": [
        PickerOption(
            id="anthropic/claude-haiku-4-5",
            label="Claude Haiku 4.5",
            description="Default — cheapest current-generation Claude.",
        ),
        PickerOption(
            id="anthropic/claude-sonnet-4-6",
            label="Claude Sonnet 4.6",
            description="Best security reasoning. ~5× cost of Haiku.",
        ),
        PickerOption(
            id="anthropic/claude-opus-4-1",
            label="Claude Opus 4.1",
            description="Highest quality, highest cost.",
        ),
    ],
    "openai": [
        PickerOption(id="openai/gpt-5", label="GPT-5", description="Default flagship."),
        PickerOption(
            id="openai/gpt-5-mini",
            label="GPT-5 Mini",
            description="Smaller, cheaper variant.",
        ),
        PickerOption(
            id="openai/gpt-4.1-mini",
            label="GPT-4.1 Mini",
            description="Solid all-rounder.",
        ),
    ],
    "google": [
        PickerOption(
            id="google/gemini-2.5-flash",
            label="Gemini 2.5 Flash",
            description="Default — fast and on the AI Studio free tier.",
        ),
        PickerOption(
            id="google/gemini-2.5-pro",
            label="Gemini 2.5 Pro",
            description="Higher quality, paid tier.",
        ),
    ],
    "ollama": [],  # picker queries /api/tags live
    "custom": [],  # user supplies
}


def picker_options(provider: AIProvider) -> list[PickerOption]:
    """Return the static picker rows for *provider* (Ollama/Custom are empty)."""
    return list(_PICKER.get(provider, []))


# ---------------------------------------------------------------------------
# Startup warning
# ---------------------------------------------------------------------------

_WARNING_LOGGED = False


def log_override_warnings_once() -> None:
    """Emit one WARNING per active model override. Safe to call multiple times.

    Called from app startup (``main.py`` lifespan). Idempotent — repeated
    calls do not re-warn so test runs that init the app multiple times in
    one process stay quiet.
    """
    global _WARNING_LOGGED
    if _WARNING_LOGGED:
        return
    _WARNING_LOGGED = True
    for provider in _CATALOG:
        override = os.environ.get(_override_env_var(provider), "").strip()
        if not override:
            continue
        logger.warning(
            "AI model override active for %s: %s. "
            "Cliff is tuned for claude-sonnet-4-6; performance may vary.",
            provider,
            override,
        )


def _reset_for_tests() -> None:
    """Reset the once-flag so tests can re-exercise the warning path."""
    global _WARNING_LOGGED
    _WARNING_LOGGED = False
