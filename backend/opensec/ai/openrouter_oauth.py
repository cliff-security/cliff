"""OpenRouter OAuth PKCE flow (IMPL-0011 Phase C).

OpenRouter's documented flow is straight PKCE. We run the dance entirely
server-side, parking the in-flight state in memory keyed by ``session_id``.
The frontend opens the auth URL in a new tab; the user signs in on
OpenRouter, authorizes; OpenRouter redirects the browser to
``http://localhost:3000/callback?code=...&state=...``; our one-shot
listener forwards the code into the in-memory session; we exchange the
code at the OpenRouter token endpoint; we encrypt + persist the key.

Constraints:
* Port 3000 is non-negotiable — OpenRouter requires it for local
  callbacks (ADR-0036). On conflict the start endpoint surfaces a
  typed 409 the UI translates into the BYOK fallback card.
* Sessions TTL at 10 min (state) / 5 min (listener) — kept in memory
  because a server restart kills the listener regardless.
* Raw keys never escape this module except via the
  ``AIIntegrationService.complete_oauth`` boundary, which encrypts at
  rest.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import logging
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import httpx

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_TOKEN_URL = "https://openrouter.ai/api/v1/auth/keys"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 3000
CALLBACK_PATH = "/callback"

STATE_TTL_SECONDS = 600  # 10 minutes
LISTENER_TTL_SECONDS = 300  # 5 minutes


SessionStatus = Literal["waiting", "connected", "denied", "error", "timeout"]


# ---------------------------------------------------------------------------
# PKCE primitives
# ---------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)``.

    Verifier is a 43-character URL-safe random string (per RFC 7636 §4.1
    high end of the recommended range). Challenge is the unpadded
    base64url-encoded SHA-256 of the verifier.
    """
    # 32 bytes → 43 base64url chars after stripping padding.
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    )
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    """A 32-char URL-safe random CSRF token."""
    return secrets.token_urlsafe(24)  # 24 bytes → 32 chars


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


@dataclass
class OAuthSession:
    """In-flight OAuth state. Never logged — see __repr__."""

    session_id: str
    verifier: str
    state: str
    created_at: float
    status: SessionStatus = "waiting"
    listener_task: asyncio.Task | None = field(default=None, repr=False)
    listener_server: asyncio.base_events.Server | None = field(default=None, repr=False)
    detail: str | None = None
    # Set once OpenRouter calls back with the auth code.
    auth_code: str | None = field(default=None, repr=False)
    # Populated after a successful token exchange; consumers must clear
    # this once the key has been persisted via the service.
    result_key: str | None = field(default=None, repr=False)
    result_metadata: dict | None = None

    @property
    def state_expires_at(self) -> float:
        return self.created_at + STATE_TTL_SECONDS

    @property
    def is_terminal(self) -> bool:
        return self.status in ("connected", "denied", "error", "timeout")

    def __repr__(self) -> str:  # pragma: no cover — trivial
        return (
            f"OAuthSession(session_id={self.session_id!r}, "
            f"status={self.status!r}, detail={self.detail!r})"
        )


class OAuthSessionStore:
    """Thread-unsafe in-memory store keyed by ``session_id`` with TTL eviction."""

    def __init__(self) -> None:
        self._sessions: dict[str, OAuthSession] = {}

    def create(self) -> tuple[OAuthSession, str]:
        """Mint a fresh session and return it alongside the PKCE challenge.

        Returning the challenge separately keeps the verifier inside the
        session (where it belongs) while giving the caller the one value
        it needs for the auth URL. Also drops any aged-out sessions so
        the store can't grow unbounded under a bot pounding /start.
        """
        self.evict_expired()
        verifier, challenge = generate_pkce_pair()
        session_id = secrets.token_urlsafe(16)
        state = generate_state()
        record = OAuthSession(
            session_id=session_id,
            verifier=verifier,
            state=state,
            created_at=time.monotonic(),
        )
        self._sessions[session_id] = record
        return record, challenge

    def get(self, session_id: str) -> OAuthSession | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        if not record.is_terminal and time.monotonic() > record.state_expires_at:
            record.status = "timeout"
            record.detail = "Session expired."
        return record

    def get_by_state(self, state: str) -> OAuthSession | None:
        for record in self._sessions.values():
            if record.state == state:
                return record
        return None

    def evict_expired(self) -> int:
        """Remove sessions whose state has aged out. Returns count evicted."""
        now = time.monotonic()
        evict = [
            sid
            for sid, rec in self._sessions.items()
            if rec.is_terminal and now > rec.state_expires_at + STATE_TTL_SECONDS
        ]
        for sid in evict:
            self._sessions.pop(sid, None)
        return len(evict)

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __len__(self) -> int:  # pragma: no cover — trivial
        return len(self._sessions)


# Module-level singleton — short-lived state lives only in the process.
_store = OAuthSessionStore()


def get_store() -> OAuthSessionStore:
    return _store


def _reset_store_for_tests() -> None:
    """Test hook — drop everything in the in-memory store."""
    _store._sessions.clear()  # noqa: SLF001 — intentional test access


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Port3000UnavailableError(RuntimeError):
    """Raised when the OAuth listener can't bind to localhost:3000."""


class OAuthExchangeError(RuntimeError):
    """Raised when OpenRouter's token endpoint refuses the code exchange."""


# ---------------------------------------------------------------------------
# Port 3000 one-shot listener
# ---------------------------------------------------------------------------


def build_auth_url(code_challenge: str, state: str) -> str:
    """Return the URL the frontend opens in a new tab."""
    params = {
        "callback_url": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{OPENROUTER_AUTH_URL}?{urllib.parse.urlencode(params)}"


_HTML_BODY = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<title>OpenSec — authorized</title></head><body style='"
    "font-family: system-ui, sans-serif; padding: 48px; color: #2b3437; "
    "background:#f8f9fa;'>"
    "<h2 style='font-family:Manrope,sans-serif;font-weight:700;'>You can close this tab.</h2>"
    "<p>OpenSec received the authorization. Head back to the app to continue.</p>"
    "</body></html>"
)


async def _parse_callback(
    reader: asyncio.StreamReader,
) -> tuple[str | None, str | None]:
    """Parse a minimal HTTP GET request line. Returns (code, state) or (None, None)."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
    except TimeoutError:
        return None, None
    if not request_line:
        return None, None
    try:
        parts = request_line.decode("latin-1").split(" ")
        if len(parts) < 2 or parts[0] != "GET":
            return None, None
        target = parts[1]
    except (UnicodeDecodeError, ValueError, IndexError):
        return None, None
    parsed = urllib.parse.urlparse(target)
    if parsed.path != CALLBACK_PATH:
        return None, None
    qs = urllib.parse.parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    state = qs.get("state", [None])[0]
    # Drain headers so the client gets the response.
    while True:
        line = await reader.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
    return code, state


async def _write_response(writer: asyncio.StreamWriter, status: int, body: str) -> None:
    body_bytes = body.encode("utf-8")
    headers = (
        f"HTTP/1.1 {status} OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("latin-1")
    writer.write(headers + body_bytes)
    try:
        await writer.drain()
    finally:
        writer.close()


async def start_listener(
    session: OAuthSession,
    *,
    on_callback: Callable[[OAuthSession, str, str], Awaitable[None]],
    port: int | None = None,
    timeout_seconds: float = LISTENER_TTL_SECONDS,
) -> asyncio.base_events.Server:
    """Start a one-shot HTTP listener for the OAuth callback.

    Returns the bound server. Raises ``Port3000UnavailableError`` if the
    port is already in use. The listener auto-cancels after
    ``timeout_seconds`` even if no callback arrives.
    """
    # The handler closes over `session` and the callback.
    async def _handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        code, state = await _parse_callback(reader)
        try:
            if (
                code
                and state
                and hmac.compare_digest(state, session.state)
            ):
                session.auth_code = code
                await _write_response(writer, 200, _HTML_BODY)
                await on_callback(session, code, state)
            else:
                # Either no code, missing state, or state mismatch — record
                # error but still close cleanly.
                if not session.is_terminal:
                    session.status = "error"
                    session.detail = "Invalid OAuth callback."
                await _write_response(
                    writer, 400, "<p>OpenSec rejected the callback.</p>"
                )
        finally:
            if not writer.is_closing():
                writer.close()

    resolved_port = CALLBACK_PORT if port is None else port
    try:
        server = await asyncio.start_server(
            _handle, host=CALLBACK_HOST, port=resolved_port
        )
    except OSError as exc:
        # EADDRINUSE = 48 on macOS / 98 on Linux. We classify by errno.
        if exc.errno in (48, 98, 10048):
            raise Port3000UnavailableError(
                f"Port {resolved_port} is already in use."
            ) from exc
        raise

    async def _shut_after_timeout() -> None:
        try:
            await asyncio.sleep(timeout_seconds)
            if not session.is_terminal:
                session.status = "timeout"
                session.detail = "OAuth callback timed out."
            server.close()
            await server.wait_closed()
        except asyncio.CancelledError:
            raise

    timeout_task = asyncio.create_task(_shut_after_timeout())
    session.listener_server = server
    session.listener_task = timeout_task
    return server


async def stop_listener(session: OAuthSession) -> None:
    """Stop the listener for *session* if running. Idempotent."""
    if session.listener_task is not None:
        session.listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await session.listener_task
        session.listener_task = None
    if session.listener_server is not None:
        try:
            session.listener_server.close()
            await session.listener_server.wait_closed()
        except Exception:
            pass
        session.listener_server = None


# ---------------------------------------------------------------------------
# Code exchange
# ---------------------------------------------------------------------------


async def exchange_code(
    code: str,
    code_verifier: str,
    *,
    token_url: str = OPENROUTER_TOKEN_URL,
    timeout_seconds: float = 10.0,
) -> dict:
    """POST the code + verifier to OpenRouter; return the parsed body.

    Raises ``OAuthExchangeError`` on any non-2xx / network / parse error.
    The returned dict at least contains ``key``; ``user_email``,
    ``user_id`` etc. may be present.
    """
    payload = {
        "code": code,
        "code_verifier": code_verifier,
        "code_challenge_method": "S256",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(token_url, json=payload)
    except httpx.HTTPError as exc:
        raise OAuthExchangeError(f"network error during token exchange: {exc}") from exc

    if resp.status_code < 200 or resp.status_code >= 300:
        raise OAuthExchangeError(
            f"token exchange returned HTTP {resp.status_code}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise OAuthExchangeError("token exchange returned non-JSON") from exc

    if not isinstance(data, dict) or "key" not in data:
        raise OAuthExchangeError("token exchange missing 'key' field")
    return data
