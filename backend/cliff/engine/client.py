"""Async HTTP client for the OpenCode REST API."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import httpx

from cliff.config import settings
from cliff.engine.models import MessageInfo, SessionDetail, SessionSummary

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class OpenCodeClient:
    """Wraps the OpenCode server REST API.

    Two interaction modes for sending messages:

    **Mode 1 — Synchronous RPC** (simple, for batch/background work):
        Use ``send_and_get_response(session_id, content)`` which blocks
        until the LLM finishes and returns the assistant's text.  No SSE
        stream management needed.

    **Mode 2 — Streaming observer** (real-time progress):
        Connect ``stream_events(session_id)`` *first*, then call
        ``send_message()`` in a delayed background task so the listener
        is already subscribed when events fire.  See ``AgentExecutor``
        for the reference implementation.

    Do NOT call ``send_message()`` followed by ``stream_events()`` —
    ``send_message`` blocks until the LLM is done, so by the time the
    stream connects, ``session.idle`` has already fired.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or settings.opencode_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # --- Sessions ---

    async def create_session(self) -> SessionSummary:
        """Create a new OpenCode session."""
        client = await self._get_client()
        resp = await client.post("/session")
        resp.raise_for_status()
        data = resp.json()
        return SessionSummary(
            id=data.get("id", data.get("sessionID", "")),
            created_at=data.get("created_at"),
        )

    async def delete_session(self, session_id: str) -> None:
        """Delete an OpenCode session. Caller should suppress errors."""
        client = await self._get_client()
        resp = await client.delete(f"/session/{session_id}")
        resp.raise_for_status()

    async def list_sessions(self) -> list[SessionSummary]:
        """List all active sessions."""
        client = await self._get_client()
        resp = await client.get("/session")
        resp.raise_for_status()
        data = resp.json()
        sessions = data if isinstance(data, list) else data.get("sessions", [])
        return [
            SessionSummary(
                id=s.get("id", s.get("sessionID", "")),
                created_at=s.get("created_at"),
            )
            for s in sessions
        ]

    async def _fetch_messages(self, session_id: str) -> list[dict]:
        """Fetch raw messages from ``GET /session/{id}/message``.

        Returns the parsed JSON list. Raises on network/HTTP errors so
        callers can decide whether to propagate or suppress.
        """
        client = await self._get_client()
        resp = await client.get(f"/session/{session_id}/message")
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    @staticmethod
    def _extract_text(msg: dict) -> str:
        """Extract concatenated text and reasoning parts from a message."""
        parts = msg.get("parts", [])
        text_parts = [
            p.get("text", "")
            for p in parts
            if p.get("type") in ("text", "reasoning") and p.get("text", "").strip()
        ]
        return "\n".join(text_parts)

    async def get_session(self, session_id: str) -> SessionDetail:
        """Get session details including messages from OpenCode."""
        client = await self._get_client()
        resp = await client.get(f"/session/{session_id}")
        resp.raise_for_status()
        data = resp.json()

        try:
            raw_messages = await self._fetch_messages(session_id)
        except Exception:
            logger.warning("Could not fetch messages for session %s", session_id, exc_info=True)
            raw_messages = []
        messages: list[MessageInfo] = []
        session_model = ""

        for m in raw_messages:
            info = m.get("info", m)
            role = info.get("role", "")
            msg_id = info.get("id", "")

            # Extract model from message metadata.
            if not session_model:
                if role == "assistant":
                    provider_id = info.get("providerID", "")
                    model_id = info.get("modelID", "")
                    if provider_id and model_id:
                        session_model = f"{provider_id}/{model_id}"
                elif role == "user":
                    model_info = info.get("model", {})
                    if isinstance(model_info, dict):
                        provider_id = model_info.get("providerID", "")
                        model_id = model_info.get("modelID", "")
                        if provider_id and model_id:
                            session_model = f"{provider_id}/{model_id}"

            content = self._extract_text(m)
            if content:
                messages.append(
                    MessageInfo(id=msg_id, role=role, content=content)
                )

        return SessionDetail(
            id=data.get("id", data.get("sessionID", session_id)),
            created_at=data.get("created_at"),
            messages=messages,
            model=session_model,
        )

    # --- Messages ---

    async def get_last_assistant_text(self, session_id: str) -> str | None:
        """Return the last assistant text from a session's message history.

        Used after ``send_message`` completes (which blocks until the LLM
        finishes) to read the response without SSE. Part of Mode 1
        (synchronous RPC).
        """
        for msg in reversed(await self._fetch_messages(session_id)):
            info = msg.get("info", msg)
            if info.get("role") != "assistant":
                continue
            text = self._extract_text(msg)
            if text:
                return text
        return None

    async def send_message(
        self, session_id: str, content: str, *, timeout: float = 120.0,
    ) -> None:
        """Send a message to an OpenCode session.

        IMPORTANT: This call **blocks** until the LLM finishes generating
        its response (typically 10–120 s). Returns ``None`` on success.

        ``timeout`` is the HTTP-level deadline on the POST call. Callers
        that can tolerate only a short wait (e.g. the provider probe in
        ADR-0031) pass a smaller value. Defaults to 120 s to preserve
        existing long-running agent behaviour.

        To get the response text afterward, use one of:
          - ``get_last_assistant_text(session_id)`` — simple, deterministic
          - ``stream_events(session_id)`` — must be connected **before**
            calling this method (see ``AgentExecutor`` for that pattern)
        """
        client = await self._get_client()
        resp = await client.post(
            f"/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": content}]},
            timeout=httpx.Timeout(timeout, connect=5.0),
        )
        resp.raise_for_status()

    async def send_and_get_response(
        self, session_id: str, content: str,
        timeout: float = 120.0, poll_interval: float = 1.0,
    ) -> str | None:
        """Send a message and return the assistant's response text.

        The OpenCode ``POST /session/{id}/message`` API returns
        immediately (non-blocking). This method polls the message
        history until an assistant reply appears or *timeout* seconds
        have elapsed. ``timeout`` is threaded through to
        ``send_message`` so the HTTP call itself also respects it.
        """
        await self.send_message(session_id, content, timeout=timeout)

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            text = await self.get_last_assistant_text(session_id)
            if text:
                return text
            await asyncio.sleep(poll_interval)

        logger.warning(
            "send_and_get_response timed out after %.0fs for session %s",
            timeout, session_id,
        )
        return None

    # --- Event streaming ---

    async def stream_events(self, session_id: str) -> AsyncIterator[dict]:
        """Subscribe to OpenCode's global SSE event stream.

        Filters events for the given session_id. Yields structured dicts:
        - {"type": "text", "content": "..."} for assistant text
        - {"type": "error", "message": "..."} for errors
        - {"type": "done"} when the session goes idle
        """
        client = await self._get_client()
        async with client.stream(
            "GET",
            "/event",
            timeout=httpx.Timeout(None, connect=5.0),
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            last_text = ""
            # When permission.asked fires, OpenCode goes idle while waiting
            # for the grant/deny. We skip that first idle. After the user
            # responds (grant or deny), OpenCode resumes and eventually
            # emits another idle — that one is the real "done".
            idle_skip_count = 0
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    parsed = self._parse_sse(event_str)
                    if not parsed:
                        continue
                    try:
                        data = json.loads(parsed["data"])
                    except (json.JSONDecodeError, KeyError):
                        continue

                    event_type = data.get("type", "")
                    props = data.get("properties", {})

                    # Filter to our session
                    event_session = (
                        props.get("sessionID")
                        or props.get("info", {}).get("sessionID")
                        or props.get("part", {}).get("sessionID")
                    )
                    if event_session and event_session != session_id:
                        continue

                    if event_type == "message.part.updated":
                        part = props.get("part", {})
                        text = part.get("text", "")
                        if text and text != last_text:
                            yield {"type": "text", "content": text}
                            last_text = text

                    elif event_type == "session.error":
                        error = props.get("error", {})
                        msg = error.get("data", {}).get("message", str(error))
                        yield {"type": "error", "message": msg}

                    elif event_type == "session.idle":
                        if idle_skip_count > 0:
                            idle_skip_count -= 1
                            logger.debug(
                                "Skipping session.idle (permission wait) "
                                "for session %s, %d skips remaining",
                                session_id, idle_skip_count,
                            )
                            continue
                        yield {"type": "done"}
                        return

                    elif event_type == "permission.asked":
                        idle_skip_count = 1
                        yield {
                            "type": "permission_request",
                            "id": props.get("id", ""),
                            "tool": props.get("permission", "unknown"),
                            "patterns": props.get("patterns", []),
                            "session_id": event_session,
                        }

                    elif event_session == session_id:
                        yield {"type": "activity", "event_type": event_type}

    @staticmethod
    def _parse_sse(raw: str) -> dict | None:
        """Parse a single SSE event block into a dict."""
        event_type = "message"
        data_lines: list[str] = []
        for line in raw.strip().split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
            elif line.startswith(":"):
                continue  # comment
        if not data_lines:
            return None
        return {"event": event_type, "data": "\n".join(data_lines)}

    # --- Permissions ---

    async def grant_permission(
        self, permission_id: str, *, session_id: str, always: bool = False,
    ) -> None:
        """Grant a pending permission request.

        Uses OpenCode's session-scoped permission API:
        POST /session/{sessionId}/permissions/{permissionId}
        """
        response = "always" if always else "once"
        client = await self._get_client()
        resp = await client.post(
            f"/session/{session_id}/permissions/{permission_id}",
            json={"response": response},
        )
        resp.raise_for_status()

    async def deny_permission(
        self, permission_id: str, *, session_id: str,
    ) -> None:
        """Deny a pending permission request."""
        client = await self._get_client()
        resp = await client.post(
            f"/session/{session_id}/permissions/{permission_id}",
            json={"response": "reject"},
        )
        resp.raise_for_status()

    # --- Health ---

    async def health_check(self) -> bool:
        """Check if OpenCode server is responding."""
        try:
            client = await self._get_client()
            resp = await client.get("/session", timeout=2.0)
            return resp.status_code < 500
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    # --- Config ---

    async def get_config(self) -> dict:
        """GET /config — current OpenCode configuration."""
        client = await self._get_client()
        resp = await client.get("/config")
        resp.raise_for_status()
        return resp.json()

    async def update_config(self, config: dict) -> dict:
        """PATCH /config — update config at runtime (model, providers, etc.)."""
        client = await self._get_client()
        resp = await client.patch("/config", json=config)
        resp.raise_for_status()
        return resp.json()

    # --- Providers ---

    async def list_providers(self) -> dict:
        """GET /provider — all available providers with model catalogs."""
        client = await self._get_client()
        resp = await client.get("/provider")
        resp.raise_for_status()
        return resp.json()

    async def get_configured_providers(self) -> dict:
        """GET /config/providers — configured providers with defaults."""
        client = await self._get_client()
        resp = await client.get("/config/providers")
        resp.raise_for_status()
        return resp.json()

    async def get_provider_auth(self) -> dict:
        """GET /provider/auth — which providers have valid credentials."""
        client = await self._get_client()
        resp = await client.get("/provider/auth")
        resp.raise_for_status()
        return resp.json()

    # --- Auth ---

    async def set_auth(self, provider_id: str, auth: dict) -> bool:
        """PUT /auth/{provider_id} — set API key or credentials at runtime."""
        client = await self._get_client()
        resp = await client.put(f"/auth/{provider_id}", json=auth)
        resp.raise_for_status()
        return resp.json()


# Singleton instance
opencode_client = OpenCodeClient()
