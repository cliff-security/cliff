"""Tests for the OpenRouter OAuth routes (IMPL-0011 Phase C5)."""

from __future__ import annotations

import asyncio
import os
import socket
from contextlib import asynccontextmanager

import pytest

from cliff.ai import autodetect, catalog, openrouter_oauth
from cliff.db.connection import close_db, init_db
from cliff.integrations.vault import CredentialVault


@pytest.fixture(autouse=True)
def _stub_opencode_auth_sync(monkeypatch):
    """Stub opencode_client.set_auth + get_config so the OpenCode auth.json
    sync (set_auth) and the live-probe (get_config, ADR-0037) don't try to
    hit a real 127.0.0.1:4096 inside the OAuth route tests."""
    from unittest.mock import AsyncMock

    from cliff.engine.client import opencode_client

    monkeypatch.setattr(opencode_client, "set_auth", AsyncMock(return_value=True))
    monkeypatch.setattr(
        opencode_client, "get_config", AsyncMock(return_value={})
    )


@pytest.fixture
def non_mocked_hosts() -> list[str]:
    """Let httpx requests to the local OAuth callback bypass pytest-httpx."""
    return ["127.0.0.1", "test"]


class _StubAudit:
    def __init__(self) -> None:
        self.events: list = []

    async def log(self, event) -> None:
        self.events.append(event)


@pytest.fixture
async def ai_client(monkeypatch, tmp_path):
    """HTTP client + real vault + clean OAuth store."""
    from httpx import ASGITransport, AsyncClient

    from cliff.main import app

    @asynccontextmanager
    async def _noop(_app):
        yield

    app.router.lifespan_context = _noop
    await init_db(":memory:")

    from cliff.db.connection import _db as _dbref  # type: ignore[attr-defined]
    assert _dbref is not None
    app.state.vault = CredentialVault(_dbref, key=os.urandom(32))
    app.state.audit_logger = _StubAudit()

    monkeypatch.setattr(autodetect, "_home", lambda: tmp_path)
    for var in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for provider in catalog.all_providers():
        monkeypatch.delenv(
            f"CLIFF_AI_MODEL_OVERRIDE_{provider.upper()}", raising=False
        )
    catalog._reset_for_tests()
    openrouter_oauth._reset_store_for_tests()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Tear down any listeners that the test left running.
    for s in list(openrouter_oauth.get_store()._sessions.values()):  # noqa: SLF001
        await openrouter_oauth.stop_listener(s)
    openrouter_oauth._reset_store_for_tests()

    app.state.vault = None
    app.state.audit_logger = None
    await close_db()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _fire_callback(port: int, *, code: str, state: str) -> None:
    """Send a raw HTTP GET to the OAuth listener (bypassing httpx/pytest-httpx)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        request = (
            f"GET /callback?code={code}&state={state} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("latin-1"))
        await writer.drain()
        # Read the response so the server can finish writing before we close.
        await reader.read()
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# /openrouter/start
# ---------------------------------------------------------------------------


async def test_start_returns_auth_url_and_session_id(ai_client, monkeypatch) -> None:
    # Pin the listener port to a free one so the test doesn't depend on :3000.
    port = _free_port()
    monkeypatch.setattr(openrouter_oauth, "CALLBACK_PORT", port)
    resp = await ai_client.post("/api/integrations/ai/openrouter/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_url"].startswith("https://openrouter.ai/auth?")
    assert "session_id" in body
    assert "code_challenge=" in body["auth_url"]


async def test_start_returns_409_on_port_conflict(ai_client, monkeypatch) -> None:
    port = _free_port()
    monkeypatch.setattr(openrouter_oauth, "CALLBACK_PORT", port)
    blocker = await asyncio.start_server(
        lambda r, w: w.close(), host="127.0.0.1", port=port
    )
    try:
        resp = await ai_client.post("/api/integrations/ai/openrouter/start")
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "port_3000_in_use"
    finally:
        blocker.close()
        await blocker.wait_closed()


# ---------------------------------------------------------------------------
# /openrouter/status — unknown
# ---------------------------------------------------------------------------


async def test_status_404_for_unknown_session(ai_client) -> None:
    resp = await ai_client.get(
        "/api/integrations/ai/openrouter/status",
        params={"session_id": "nope"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Full flow — start, mock OpenRouter token exchange, simulate callback
# ---------------------------------------------------------------------------


async def test_full_flow_completes_to_connected(ai_client, monkeypatch, httpx_mock) -> None:
    port = _free_port()
    monkeypatch.setattr(openrouter_oauth, "CALLBACK_PORT", port)

    start_resp = await ai_client.post("/api/integrations/ai/openrouter/start")
    session_id = start_resp.json()["session_id"]
    session = openrouter_oauth.get_store().get(session_id)
    assert session is not None

    # Initial poll → waiting.
    status_resp = await ai_client.get(
        "/api/integrations/ai/openrouter/status",
        params={"session_id": session_id},
    )
    assert status_resp.json()["status"] == "waiting"

    # Mock the OpenRouter token endpoint.
    httpx_mock.add_response(
        url=openrouter_oauth.OPENROUTER_TOKEN_URL,
        method="POST",
        status_code=200,
        json={"key": "sk-or-v1-final", "user_email": "u@example.com"},
    )

    # Simulate OpenRouter's redirect via a raw socket (pytest-httpx
    # would otherwise intercept httpx clients here).
    await _fire_callback(port, code="oauth-code", state=session.state)

    # Give the callback handler a moment to persist.
    for _ in range(50):
        await asyncio.sleep(0.02)
        if session.status == "connected":
            break

    status_resp = await ai_client.get(
        "/api/integrations/ai/openrouter/status",
        params={"session_id": session_id},
    )
    assert status_resp.json()["status"] == "connected"

    # Verify the integration is now persisted + key resolvable.
    overall = await ai_client.get("/api/integrations/ai/status")
    body = overall.json()
    assert body["state"] == "connected"
    assert body["provider"] == "openrouter"
    assert body["source"] == "openrouter-oauth"
    assert body["metadata"] == {"user_email": "u@example.com"}


async def test_flow_marks_error_on_token_exchange_failure(
    ai_client, monkeypatch, httpx_mock
) -> None:
    port = _free_port()
    monkeypatch.setattr(openrouter_oauth, "CALLBACK_PORT", port)

    start_resp = await ai_client.post("/api/integrations/ai/openrouter/start")
    session_id = start_resp.json()["session_id"]
    session = openrouter_oauth.get_store().get(session_id)

    httpx_mock.add_response(
        url=openrouter_oauth.OPENROUTER_TOKEN_URL,
        method="POST",
        status_code=400,
    )

    await _fire_callback(port, code="bad", state=session.state)

    for _ in range(50):
        await asyncio.sleep(0.02)
        if session.status == "error":
            break

    status_resp = await ai_client.get(
        "/api/integrations/ai/openrouter/status",
        params={"session_id": session_id},
    )
    body = status_resp.json()
    assert body["status"] == "error"
    assert body["detail"]
