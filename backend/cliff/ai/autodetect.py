"""Auto-detect existing AI provider keys in the user's environment.

Read-only scan of common locations, in priority order (ADR-0036 / IMPL-0011
Phase B):

  1. ``~/.claude/.credentials.json``         → Anthropic
  2. ``ANTHROPIC_API_KEY`` env var           → Anthropic
  3. ``OPENROUTER_API_KEY`` env var          → OpenRouter
  4. ``OPENAI_API_KEY`` env var              → OpenAI
  5. ``~/.aider/.env``                       → first match in file
  6. ``~/.config/openai/`` (auth.json/config) → OpenAI

The scanner never persists anything — it returns a ``DetectedKey`` (or
``None``) which the API layer surfaces to the user. The user must
explicitly click *Use it* before any key is stored.

Failure modes are all soft: missing file → skip; malformed JSON → skip;
permission error → skip; missing fields → skip. The scanner never raises.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from cliff.ai.models import AIProvider, DetectedKey

logger = logging.getLogger(__name__)


def _home() -> Path:
    """Indirection so tests can monkeypatch ``Path.home`` cleanly."""
    return Path.home()


def _from_claude_credentials() -> DetectedKey | None:
    path = _home() / ".claude" / ".credentials.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    # Tolerant lookup — the format has shifted across Claude Code versions.
    candidate = None
    if isinstance(data, dict):
        candidate = data.get("anthropic_api_key") or data.get("api_key")
        if not candidate and isinstance(data.get("accounts"), list):
            for account in data["accounts"]:
                if isinstance(account, dict):
                    candidate = account.get("api_key") or account.get(
                        "anthropic_api_key"
                    )
                    if candidate:
                        break

    if not candidate or not isinstance(candidate, str):
        return None
    return DetectedKey(
        provider="anthropic",
        source=f"{path}",
        raw_key=candidate,
    )


def _from_env(var_name: str, provider: AIProvider) -> DetectedKey | None:
    value = os.environ.get(var_name, "").strip()
    if not value:
        return None
    return DetectedKey(
        provider=provider, source=f"{var_name} env", raw_key=value
    )


def _from_aider_env() -> DetectedKey | None:
    path = _home() / ".aider" / ".env"
    if not path.exists():
        return None
    try:
        content = path.read_text()
    except OSError:
        return None

    parsed: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip().strip("\"'")

    # Honor the same priority order as the env-var scan.
    aider_priority: tuple[tuple[str, AIProvider], ...] = (
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("OPENROUTER_API_KEY", "openrouter"),
        ("OPENAI_API_KEY", "openai"),
    )
    for var, provider in aider_priority:
        raw = parsed.get(var, "").strip()
        if not raw:
            continue
        return DetectedKey(
            provider=provider,
            source=f"{path}",
            raw_key=raw,
        )
    return None


def _from_openai_config_dir() -> DetectedKey | None:
    base = _home() / ".config" / "openai"
    if not base.exists():
        return None

    # Try a few common filenames inside the directory.
    candidates = [base / "auth.json", base / "config", base / "config.json"]
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text()
        except OSError:
            continue

        # JSON first.
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None

        candidate: str | None = None
        if isinstance(data, dict):
            for field in ("api_key", "openai_api_key", "OPENAI_API_KEY"):
                value = data.get(field)
                if isinstance(value, str) and value.strip():
                    candidate = value.strip()
                    break

        # ini-ish fallback: line-by-line ``OPENAI_API_KEY=…``.
        if candidate is None:
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if "OPENAI_API_KEY" in line and "=" in line:
                    _, _, value = line.partition("=")
                    value = value.strip().strip("\"'")
                    if value:
                        candidate = value
                        break

        if candidate:
            return DetectedKey(
                provider="openai", source=f"{path}", raw_key=candidate
            )

    return None


def scan() -> DetectedKey | None:
    """Run the priority scan. Returns the first found key, or ``None``.

    Order matches ADR-0036 / IMPL-0011 Phase B1. Caller treats the result
    as a *suggestion* — adoption requires explicit user action.
    """
    return (
        _from_claude_credentials()
        or _from_env("ANTHROPIC_API_KEY", "anthropic")
        or _from_env("OPENROUTER_API_KEY", "openrouter")
        or _from_env("OPENAI_API_KEY", "openai")
        or _from_aider_env()
        or _from_openai_config_dir()
    )
