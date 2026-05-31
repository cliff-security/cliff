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

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

import httpx

from cliff.ai.models import AIProvider, ValidationResult

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Custom-endpoint URL validation — SSRF defense
# ---------------------------------------------------------------------------
#
# The "custom" provider lets the user supply a base URL for an
# OpenAI-compatible endpoint. Even though Cliff is single-user
# self-hosted, we still refuse to probe loopback / private / link-local
# / multicast / reserved addresses (and non-http(s) schemes) so a
# misconfigured BYOK can't be used to scan the host's internal network
# from the backend's network position. The validator is the only place
# in the codebase that fetches a user-supplied URL.


class CustomEndpointRejectedError(ValueError):
    """Raised when a user-supplied custom endpoint URL fails sanity checks."""


_PRIVATE_HOST_NAMES = frozenset(
    {"localhost", "ip6-localhost", "ip6-loopback"}
)


def _ip_is_unsafe(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *ip* should not be reachable from the validator.

    Strict policy: rejects loopback + RFC1918 private + link-local +
    multicast + reserved + unspecified. Used for the "custom"
    OpenAI-compatible provider and for LLM-output URLs (the reference
    verifier) — both sources we cannot trust to point at the public
    internet.
    """
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _ip_is_obviously_unsafe(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Looser policy for Ollama: rejects only clearly-malicious targets.

    Ollama is **designed** to be loopback-by-default and remote-via-SSH-
    tunnel by intent (the picker advertises ``http://localhost:11434``
    and SSH-tunnel/remote-Ollama users supply ``http://10.0.0.x:11434``).
    So loopback + RFC1918 private stay allowed. What we still reject:

    * link-local — would let a malformed base URL hit cloud-metadata
      services (``169.254.169.254``);
    * multicast / reserved / unspecified — never legitimate Ollama hosts.
    """
    return (
        ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _resolve_host_addresses(
    host: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve *host* via DNS in a thread; return parsed IPs.

    Raises ``CustomEndpointRejectedError`` if the host cannot be resolved.
    Runs the blocking ``getaddrinfo`` call in a worker thread so the
    event loop stays responsive. We don't use ``loop.getaddrinfo`` so
    tests can monkeypatch the synchronous ``socket.getaddrinfo``
    deterministically.
    """
    def _lookup() -> list[tuple]:
        return socket.getaddrinfo(host, None)

    try:
        infos = await asyncio.to_thread(_lookup)
    except socket.gaierror as exc:
        msg = f"Custom base URL host {host!r} could not be resolved."
        raise CustomEndpointRejectedError(msg) from exc

    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            addrs.append(ipaddress.ip_address(sockaddr[0]))
        except (ValueError, IndexError):
            continue
    if not addrs:
        msg = f"Custom base URL host {host!r} resolved to no usable addresses."
        raise CustomEndpointRejectedError(msg)
    return addrs


async def _safe_custom_chat_url(base_url: str) -> str:
    """Validate *base_url* and return a freshly rebuilt ``…/chat/completions`` URL.

    Two-layer SSRF defense:

    1. Lexical: reject non-http(s) schemes, empty hosts, and bare-IP
       hosts that fall in loopback / private / link-local / multicast /
       reserved / unspecified ranges.
    2. **DNS-aware**: resolve hostnames via ``socket.getaddrinfo`` and
       reject if **any** resolved address is in the same unsafe set.
       This closes the DNS-rebinding window where a public-looking
       hostname has an A/AAAA record pointing at the host's internal
       network. There is still a tiny TOCTOU between resolve and
       connect, but it's much narrower than the previous
       "hostname accepted without resolution" stance.

    Returns a URL **reconstructed via urlunparse** from validated parts
    so downstream ``httpx`` callers receive a value whose taint chain
    is broken from the raw user input (CodeQL sanitizer pattern).
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        msg = "Custom base URL must use http:// or https://"
        raise CustomEndpointRejectedError(msg)
    if not parsed.hostname:
        msg = "Custom base URL is missing a host."
        raise CustomEndpointRejectedError(msg)

    host = parsed.hostname.lower()
    if host in _PRIVATE_HOST_NAMES:
        msg = "Custom base URL must not point at the local machine."
        raise CustomEndpointRejectedError(msg)

    try:
        bare_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = (
            ipaddress.ip_address(host)
        )
    except ValueError:
        bare_ip = None

    if bare_ip is not None:
        if _ip_is_unsafe(bare_ip):
            msg = (
                "Custom base URL must not point at a private or loopback "
                "address."
            )
            raise CustomEndpointRejectedError(msg)
    else:
        # Hostname — resolve via DNS and reject if *any* resolved IP
        # falls in an unsafe range. The check is done here, before the
        # outbound HTTP request; the brief window between resolve and
        # connect can in theory be raced by a hostile resolver, but
        # the probe doesn't reflect response bodies so there is no
        # exfil channel even if it is.
        for addr in await _resolve_host_addresses(host):
            if _ip_is_unsafe(addr):
                msg = (
                    f"Custom base URL host {host!r} resolves to a private "
                    "or loopback address."
                )
                raise CustomEndpointRejectedError(msg)

    # Rebuild from validated parts. Constraining the scheme to a literal
    # known-safe pair + a verified-non-private host is what breaks the
    # SSRF taint flow for static analysis.
    safe_scheme = "https" if parsed.scheme == "https" else "http"
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
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


def _google_headers(_key: str) -> dict[str, str]:
    """Google AI Studio puts the key in the ``?key=`` query string, not a header."""
    return {}


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
            "model": "claude-haiku-4-5",
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
            # Non-reasoning model: takes ``max_tokens``. The reasoning
            # family (gpt-5/o1/o3) rejects ``max_tokens`` with a 400 and
            # the catch-all renders that as a misleading "no access" /
            # billing message.
            "model": "gpt-4o-mini",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ok"}],
        },
    ),
    # Google AI Studio's auth is ``?key=...`` (not a header), so the probe
    # URL is built in :func:`validate_google` rather than declared here.
    # The dict entry exists only so ``catalog.all_providers()`` aligns
    # with ``_PROBES.keys()`` in tests that assert parity.
    "google": _ProbeSpec(
        label="Google AI Studio",
        method="GET",
        url="https://generativelanguage.googleapis.com/v1beta/models",
        auth_header=_google_headers,
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


async def validate_google(api_key: str) -> ValidationResult:
    """Probe Google AI Studio with the user's key in the ``?key=`` param.

    The list-models endpoint authenticates with the API key but performs
    no generation, so it's the cheapest valid call to verify the key.

    The key is passed via ``httpx.params`` so it's properly URL-encoded
    (M3). A key containing ``&``, ``#``, ``?`` or whitespace would otherwise
    silently break the URL or inject extra parameters reaching Google.
    """
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"content-type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, params={"key": api_key}, headers=headers)
    except (httpx.TimeoutException, httpx.HTTPError):
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message="Can't reach Google AI Studio. Check your internet connection.",
        )
    return _interpret_response(resp, "Google AI Studio")


async def safe_ollama_tags_url(base_url: str | None) -> str:
    """Validate a user-supplied Ollama base URL and return the tags URL.

    Loopback and RFC1918 stay allowed (the SSH-tunnel / remote-Ollama
    use case explicitly depends on them). Only obviously-malicious IP
    classes (link-local incl. 169.254.169.254 cloud metadata, multicast,
    reserved, unspecified) are rejected. Reconstructs the URL via
    ``urlunparse`` from validated parts so the SSRF taint flow is broken
    for static analysis (M1, M2).
    """
    raw = base_url or "http://localhost:11434"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        msg = "Ollama base URL must use http:// or https://"
        raise CustomEndpointRejectedError(msg)
    if not parsed.hostname:
        msg = "Ollama base URL is missing a host."
        raise CustomEndpointRejectedError(msg)
    host = parsed.hostname.lower()

    try:
        bare_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = (
            ipaddress.ip_address(host)
        )
    except ValueError:
        bare_ip = None
    if bare_ip is not None and _ip_is_obviously_unsafe(bare_ip):
        msg = (
            "Ollama base URL must not point at a link-local, multicast, "
            "reserved, or unspecified address."
        )
        raise CustomEndpointRejectedError(msg)
    if bare_ip is None and host not in _PRIVATE_HOST_NAMES:
        for addr in await _resolve_host_addresses(host):
            if _ip_is_obviously_unsafe(addr):
                msg = (
                    f"Ollama base URL host {host!r} resolves to a "
                    "link-local, multicast, reserved, or unspecified "
                    "address."
                )
                raise CustomEndpointRejectedError(msg)

    safe_scheme = "https" if parsed.scheme == "https" else "http"
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    return urlunparse((safe_scheme, netloc, "/api/tags", "", "", ""))


async def validate_ollama(base_url: str | None = None) -> ValidationResult:
    """Probe a local Ollama install at ``{base_url}/api/tags``.

    No API key — Ollama is loopback-by-default. The validator is happy
    when ``/api/tags`` returns 200 (runtime up + responsive).

    The URL goes through ``safe_ollama_tags_url`` so a malformed or
    obviously-malicious ``base_url`` (e.g. ``http://169.254.169.254/``
    AWS metadata) is rejected up-front (M1). Loopback + RFC1918 stay
    allowed — the SSH-tunnel and remote-Ollama use cases depend on it.
    """
    try:
        url = await safe_ollama_tags_url(base_url)
    except CustomEndpointRejectedError as exc:
        return ValidationResult(
            ok=False,
            error_code="no_access",
            error_message=str(exc),
        )
    # CodeQL py/full-ssrf is suppressed here intentionally. ``url`` IS
    # user-influenced — Ollama is *designed* to accept user-supplied
    # base URLs including loopback (the local runtime) and RFC1918
    # (SSH-tunnel and remote-Ollama-on-LAN deployments, codified in
    # ADR-0038 as the "loose policy"). ``safe_ollama_tags_url`` already
    # applies the partial defense: reject link-local (incl. cloud
    # metadata 169.254.169.254), multicast, reserved, unspecified, and
    # rebuild the URL via ``urlunparse`` from validated parts. The
    # CodeQL alert is reviewed and dismissed per ADR-0038; suppressing
    # inline so the alert doesn't re-fire on every push.
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.get(url)  # codeql[py/full-ssrf]
    except (httpx.TimeoutException, httpx.HTTPError):
        return ValidationResult(
            ok=False,
            error_code="network",
            error_message=(
                "Can't reach Ollama. Is it running on "
                f"{url.rsplit('/', 2)[0]}?"
            ),
        )
    return _interpret_response(resp, "Ollama")


async def validate_custom(
    api_key: str, base_url: str, model: str | None = None
) -> ValidationResult:
    """OpenAI-compatible probe against a user-supplied base URL."""
    try:
        url = await _safe_custom_chat_url(base_url)
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
    """Dispatch to the appropriate validator.

    ``custom`` requires a non-empty ``base_url``. ``ollama`` ignores
    ``api_key`` and probes ``base_url`` (defaulting to localhost:11434).
    ``google`` puts the key in the URL, not a bearer header.
    """
    if provider == "custom":
        if not base_url:
            return ValidationResult(
                ok=False,
                error_code="no_access",
                error_message="Custom provider requires a base URL.",
            )
        return await validate_custom(api_key, base_url, model)
    if provider == "ollama":
        return await validate_ollama(base_url)
    if provider == "google":
        return await validate_google(api_key)
    return await _probe(_PROBES[provider], api_key)
