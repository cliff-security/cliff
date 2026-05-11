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
from urllib.parse import urlparse, urlunparse

import httpx

from opensec.ai.models import AIProvider, ValidationResult

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


def _classify_status(status: int) -> str | None:
    if status in (401, 403):
        return "auth_failed"
    if status == 404:
        return "model_not_found"
    if status == 429:
        return "rate_limited"
    return None


async def validate_openrouter(api_key: str) -> ValidationResult:
    """``GET https://openrouter.ai/api/v1/key`` with bearer auth."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach OpenRouter. Check your internet connection.",
        )
    except httpx.HTTPError:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach OpenRouter. Check your internet connection.",
        )
    return _interpret_response(resp, "OpenRouter")


async def validate_anthropic(api_key: str) -> ValidationResult:
    """``POST https://api.anthropic.com/v1/messages`` with ``max_tokens: 1``."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ok"}],
                },
            )
    except httpx.TimeoutException:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach Anthropic. Check your internet connection.",
        )
    except httpx.HTTPError:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach Anthropic. Check your internet connection.",
        )
    return _interpret_response(resp, "Anthropic")


async def validate_openai(api_key: str) -> ValidationResult:
    """``POST https://api.openai.com/v1/chat/completions`` with ``max_tokens: 1``."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": "gpt-5",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ok"}],
                },
            )
    except httpx.TimeoutException:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach OpenAI. Check your internet connection.",
        )
    except httpx.HTTPError:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach OpenAI. Check your internet connection.",
        )
    return _interpret_response(resp, "OpenAI")


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
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": model or "gpt-3.5-turbo",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ok"}],
                },
            )
    except httpx.TimeoutException:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach the endpoint. Check your internet connection.",
        )
    except httpx.HTTPError:
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach the endpoint. Check your internet connection.",
        )
    return _interpret_response(resp, "the endpoint")


def _interpret_response(resp: httpx.Response, label: str) -> ValidationResult:
    if 200 <= resp.status_code < 300:
        return ValidationResult(ok=True)

    code = _classify_status(resp.status_code)
    if code == "auth_failed":
        return ValidationResult(
            ok=False,
            error_code="auth_failed",
            error_message=f"This key was rejected by {label}.",
        )
    if code == "rate_limited":
        return ValidationResult(
            ok=False,
            error_code="rate_limited",
            error_message=f"{label} rate-limited the request. Try again in a minute.",
        )
    if code == "model_not_found":
        return ValidationResult(
            ok=False,
            error_code="model_not_found",
            error_message="The requested model isn't available on this account.",
        )

    # 400-499 not specifically classified → treat as no-access for billing-style
    # responses; 500-class as network for retry framing.
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


VALIDATORS = {
    "openrouter": validate_openrouter,
    "anthropic": validate_anthropic,
    "openai": validate_openai,
    # "custom" is dispatched separately because it needs base_url + model
}


async def validate(
    provider: AIProvider,
    api_key: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> ValidationResult:
    """Dispatch to the appropriate validator. Raises ``ValueError`` on unknown."""
    if provider == "custom":
        if not base_url:
            return ValidationResult(
                ok=False,
                error_code="no_access",
                error_message="Custom provider requires a base URL.",
            )
        return await validate_custom(api_key, base_url, model)
    return await VALIDATORS[provider](api_key)
