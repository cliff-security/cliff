"""Per-provider BYOK key validators (IMPL-0011 Phase D1).

Each validator fires a single cheap, side-effect-light probe at the
provider's auth surface and classifies the outcome into a typed
``ValidationResult`` the API layer surfaces to the user. Probes use
``httpx.AsyncClient`` with a 5-second timeout.

The probes are kept intentionally minimal:

* OpenRouter — ``GET /api/v1/key`` (the cheapest way to test bearer auth).
* Anthropic — ``POST /v1/messages`` with ``max_tokens: 1``.
* OpenAI — ``POST /v1/chat/completions`` with ``max_tokens: 1``.
* Custom — ``POST {base_url}/chat/completions`` with ``max_tokens: 1``.

Keys are never logged. Error bodies are surfaced as ``error_message`` but
the responses are classified through fixed string buckets that don't
contain key material.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

import httpx

from opensec.ai.models import AIProvider, ValidationResult

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Custom-endpoint URL validation — SSRF defense
# ---------------------------------------------------------------------------
#
# The "custom" provider lets the user supply a base URL for an
# OpenAI-compatible endpoint. Even though OpenSec is single-user
# self-hosted, we still refuse to probe loopback / private / link-local
# / multicast / reserved addresses (and non-http(s) schemes) so a
# misconfigured BYOK can't be used to scan the host's internal network
# from the backend's network position. The validator is the only place
# in the codebase that fetches a user-supplied URL.


class CustomEndpointRejectedError(ValueError):
    """Raised when a user-supplied custom endpoint URL fails sanity checks."""


def _safe_custom_chat_url(base_url: str) -> str:
    """Validate *base_url* and return a freshly rebuilt ``…/chat/completions`` URL.

    Rejects non-http(s) schemes and any host that resolves to a
    loopback / private / link-local / multicast / reserved address.
    Hostnames that aren't bare IPs are accepted on the assumption that
    DNS resolves to a public address — we cannot guarantee that without
    pre-resolving, which would add a TOCTOU window between check and
    request. The threat model is a user deliberately pointing OpenSec
    at their own internal API server.

    Returns a URL **reconstructed from the validated scheme + netloc**
    so that downstream `httpx` callers receive a value whose taint
    chain is broken from the raw user input.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        msg = "Custom base URL must use http:// or https://"
        raise CustomEndpointRejectedError(msg)
    if not parsed.hostname:
        msg = "Custom base URL is missing a host."
        raise CustomEndpointRejectedError(msg)

    host = parsed.hostname.lower()
    if host in ("localhost", "ip6-localhost", "ip6-loopback"):
        msg = "Custom base URL must not point at the local machine."
        raise CustomEndpointRejectedError(msg)

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        msg = "Custom base URL must not point at a private or loopback address."
        raise CustomEndpointRejectedError(msg)

    # Rebuild from validated parts. Constraining the scheme to a literal
    # known-safe pair + a verified-non-private host is what breaks the
    # SSRF taint flow for static analysis.
    safe_scheme = "https" if parsed.scheme == "https" else "http"
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    # Strip any trailing /chat/completions the user may have already
    # included, then append it ourselves so the final path is
    # statically anchored.
    user_path = parsed.path.rstrip("/")
    if user_path.endswith("/chat/completions"):
        user_path = user_path[: -len("/chat/completions")]
    safe_path = user_path + "/chat/completions"
    return urlunparse((safe_scheme, netloc, safe_path, "", "", ""))


@dataclass(frozen=True)
class _ProbeSpec:
    """Per-provider probe shape — single source of truth for the validators."""

    label: str
    method: str
    url: str
    auth_header: Callable[[str], dict[str, str]]
    body: dict | None = None


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _anthropic_headers(key: str) -> dict[str, str]:
    return {"x-api-key": key, "anthropic-version": "2023-06-01"}


_PROBES: dict[AIProvider, _ProbeSpec] = {
    "openrouter": _ProbeSpec(
        label="OpenRouter",
        method="GET",
        url="https://openrouter.ai/api/v1/key",
        auth_header=_bearer,
    ),
    "anthropic": _ProbeSpec(
        label="Anthropic",
        method="POST",
        url="https://api.anthropic.com/v1/messages",
        auth_header=_anthropic_headers,
        body={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ok"}],
        },
    ),
    "openai": _ProbeSpec(
        label="OpenAI",
        method="POST",
        url="https://api.openai.com/v1/chat/completions",
        auth_header=_bearer,
        body={
            "model": "gpt-5",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ok"}],
        },
    ),
}


async def _probe(spec: _ProbeSpec, api_key: str) -> ValidationResult:
    """Run one provider probe through the shared error-classification path."""
    headers = {"content-type": "application/json", **spec.auth_header(api_key)}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.request(
                spec.method, spec.url, headers=headers, json=spec.body
            )
    except (httpx.TimeoutException, httpx.HTTPError):
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message=(
                f"Can't reach {spec.label}. Check your internet connection."
            ),
        )
    return _interpret_response(resp, spec.label)


async def validate_openrouter(api_key: str) -> ValidationResult:
    return await _probe(_PROBES["openrouter"], api_key)


async def validate_anthropic(api_key: str) -> ValidationResult:
    return await _probe(_PROBES["anthropic"], api_key)


async def validate_openai(api_key: str) -> ValidationResult:
    return await _probe(_PROBES["openai"], api_key)


async def validate_custom(
    api_key: str, base_url: str, model: str | None = None
) -> ValidationResult:
    """OpenAI-compatible probe against a user-supplied base URL."""
    try:
        url = _safe_custom_chat_url(base_url)
    except CustomEndpointRejectedError as exc:
        return ValidationResult(
            ok=False,
            error_code="no_access",
            error_message=str(exc),
        )
    custom = _ProbeSpec(
        label="the endpoint",
        method="POST",
        url=url,
        auth_header=_bearer,
        body={
            "model": model or "gpt-3.5-turbo",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ok"}],
        },
    )
    return await _probe(custom, api_key)


# Status-code → (error_code, message_template) lookup. The template receives
# the provider label so error copy stays consistent across providers without
# four near-duplicate `if` branches.
_STATUS_MESSAGES: dict[int, tuple[str, str]] = {
    401: ("auth_failed", "This key was rejected by {label}."),
    403: ("auth_failed", "This key was rejected by {label}."),
    404: (
        "model_not_found",
        "The requested model isn't available on this account.",
    ),
    429: (
        "rate_limited",
        "{label} rate-limited the request. Try again in a minute.",
    ),
}


def _interpret_response(resp: httpx.Response, label: str) -> ValidationResult:
    if 200 <= resp.status_code < 300:
        return ValidationResult(ok=True)

    if resp.status_code in _STATUS_MESSAGES:
        code, template = _STATUS_MESSAGES[resp.status_code]
        return ValidationResult(
            ok=False,
            error_code=code,  # type: ignore[arg-type]
            error_message=template.format(label=label),
        )

    # 400-499 not specifically classified → treat as no-access for
    # billing-style responses; 500-class as network for retry framing.
    if 400 <= resp.status_code < 500:
        return ValidationResult(
            ok=False,
            error_code="no_access",
            error_message=(
                f"Your account doesn't have access. Check billing setup at {label}."
            ),
        )
    return ValidationResult(
        ok=False,
        error_code="network",
        error_message=f"{label} is unavailable right now.",
    )


async def validate(
    provider: AIProvider,
    api_key: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> ValidationResult:
    """Dispatch to the appropriate validator."""
    if provider == "custom":
        if not base_url:
            return ValidationResult(
                ok=False,
                error_code="no_access",
                error_message="Custom provider requires a base URL.",
            )
        return await validate_custom(api_key, base_url, model)
    return await _probe(_PROBES[provider], api_key)
