"""Provider catalog — per-provider defaults, env vars, console URLs.

Single source of truth for the small static facts about each provider OpenSec
supports for AI integration. Resolve-time helpers honor per-provider env-var
overrides (``OPENSEC_AI_MODEL_OVERRIDE_<PROVIDER>``) and log a startup warning
when any override is active — see ADR-0036.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opensec.ai.models import AIProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderInfo:
    """Static facts about one provider."""

    env_var_name: str
    default_model: str | None
    console_url: str
    key_hint: str | None
    docs_label: str


# Defaults per ADR-0036. Sonnet 4.6 where available; gpt-5 on OpenAI direct
# (Sonnet isn't served there); custom requires the user to specify a model.
#
# Model IDs use OpenCode's ``<provider>/<model-id>`` namespace. For
# OpenRouter that means an extra ``openrouter/`` prefix in front of
# OpenRouter's own ``<route-provider>/<model>`` identifier — without it
# OpenCode would dispatch the call through its own ``anthropic`` provider
# config (and expect ``ANTHROPIC_API_KEY``).
_CATALOG: dict[AIProvider, ProviderInfo] = {
    "openrouter": ProviderInfo(
        env_var_name="OPENROUTER_API_KEY",
        # Tencent Hy3 preview — high-context (262K) MoE model designed for
        # agentic workflows. ~50× cheaper per output token than Claude
        # Sonnet 4.6 ($0.066/$0.26 per 1M input/output vs Sonnet's
        # ~$3/$15), which keeps low-budget OpenRouter accounts from
        # hitting the credit-exhaustion failure. OpenCode-prefixed because
        # OpenRouter is routed via the ``openrouter/`` provider, then the
        # OpenRouter slug ``tencent/hy3-preview`` follows.
        default_model="openrouter/tencent/hy3-preview",
        console_url="https://openrouter.ai/keys",
        key_hint="sk-or-",
        docs_label="OpenRouter",
    ),
    "anthropic": ProviderInfo(
        env_var_name="ANTHROPIC_API_KEY",
        default_model="anthropic/claude-sonnet-4-6",
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
    "custom": ProviderInfo(
        env_var_name="OPENAI_API_KEY",  # OpenAI-compatible — shares the env name
        default_model=None,  # user must specify
        console_url="",  # provider-defined
        key_hint=None,
        docs_label="Custom (OpenAI-compatible)",
    ),
}


def get(provider: AIProvider) -> ProviderInfo:
    """Return the catalog entry for *provider* — raises KeyError on unknown."""
    return _CATALOG[provider]


def env_var_name(provider: AIProvider) -> str:
    """The env var name OpenCode reads to pick up the key for this provider."""
    return _CATALOG[provider].env_var_name


def all_providers() -> list[AIProvider]:
    """Stable order of supported providers (used by tests and admin views)."""
    return list(_CATALOG.keys())


def provider_env_var_names() -> frozenset[str]:
    """Every host env var name OpenSec controls for AI providers.

    For each catalogued provider this is its ``*_API_KEY`` plus the
    matching ``*_BASE_URL``. Callers spawning OpenCode subprocesses scrub
    these from the inherited host environment before layering OpenSec's
    own resolved values on top — otherwise a polluted host leaks in. The
    motivating case (QA Q01 B07): Claude Desktop exports
    ``ANTHROPIC_BASE_URL=https://api.anthropic.com`` (note: no ``/v1``),
    which makes OpenCode hit ``…/messages`` and get a 404, plus an empty
    ``ANTHROPIC_API_KEY`` that would otherwise shadow the real one.
    """
    names: set[str] = set()
    for info in _CATALOG.values():
        names.add(info.env_var_name)
        names.add(info.env_var_name.replace("_API_KEY", "_BASE_URL"))
    return frozenset(names)


def _override_env_var(provider: AIProvider) -> str:
    return f"OPENSEC_AI_MODEL_OVERRIDE_{provider.upper()}"


def resolve_model(provider: AIProvider) -> str | None:
    """Return the model name OpenSec should configure for *provider*.

    Honors ``OPENSEC_AI_MODEL_OVERRIDE_<PROVIDER>`` if set, else the
    catalog default. ``None`` is possible only for the ``custom`` provider
    when no override is set — callers (e.g. the workspace config renderer)
    treat ``None`` as "user must supply via the BYOK form's ``model``
    field."
    """
    override = os.environ.get(_override_env_var(provider), "").strip()
    if override:
        return override
    return _CATALOG[provider].default_model


def has_override(provider: AIProvider) -> bool:
    """True if a model-override env var is set for *provider*."""
    return bool(os.environ.get(_override_env_var(provider), "").strip())


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
            "OpenSec is tuned for claude-sonnet-4-6; performance may vary.",
            provider,
            override,
        )


def _reset_for_tests() -> None:
    """Reset the once-flag so tests can re-exercise the warning path."""
    global _WARNING_LOGGED
    _WARNING_LOGGED = False
