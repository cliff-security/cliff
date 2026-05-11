"""Tests for OpenRouter OAuth PKCE flow (IMPL-0011 Phase C)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import socket

import httpx
import pytest

from opensec.ai import openrouter_oauth as oauth


@pytest.fixture(autouse=True)
def _reset_store():
    oauth._reset_store_for_tests()
    yield
    oauth._reset_store_for_tests()


# ---------------------------------------------------------------------------
# PKCE primitives (C1)
# ---------------------------------------------------------------------------


def test_pkce_pair_lengths() -> None:
    verifier, challenge = oauth.generate_pkce_pair()
    assert len(verifier) == 43
    # base64url(sha256) → 43 chars too.
    assert len(challenge) == 43


def test_pkce_challenge_matches_verifier() -> None:
    verifier, challenge = oauth.generate_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected


def test_pkce_pairs_are_random() -> None:
    seen = {oauth.generate_pkce_pair()[0] for _ in range(10)}
    assert len(seen) == 10


def test_generate_state_is_url_safe() -> None:
    state = oauth.generate_state()
    assert len(state) >= 24
    # All chars must be in the URL-safe alphabet.
    assert all(c.isalnum() or c in "-_" for c in state)


# ---------------------------------------------------------------------------
# Session store (C2)
# ---------------------------------------------------------------------------


def test_session_store_round_trip() -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()
    assert store.get(session.session_id) is session


def test_session_store_returns_none_for_unknown() -> None:
    store = oauth.OAuthSessionStore()
    assert store.get("nope") is None


def test_session_store_lookup_by_state() -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()
    assert store.get_by_state(session.state) is session


def test_session_marks_timeout_after_ttl(monkeypatch) -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()
    # Fast-forward by replacing the monotonic clock used in get().
    future_time = session.created_at + oauth.STATE_TTL_SECONDS + 1
    monkeypatch.setattr(oauth.time, "monotonic", lambda: future_time)
    fetched = store.get(session.session_id)
    assert fetched is not None
    assert fetched.status == "timeout"


def test_session_remove() -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()
    store.remove(session.session_id)
    assert store.get(session.session_id) is None


# ---------------------------------------------------------------------------
# Listener (C3) — happy path
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_listener_happy_path_invokes_callback() -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()
    seen: dict = {}

    async def _on_cb(s, code, state):
        seen["code"] = code
        seen["state"] = state
        s.status = "connected"

    port = _free_port()
    await oauth.start_listener(
        session, on_callback=_on_cb, port=port, timeout_seconds=5.0
    )

    # Fire the callback.
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"http://127.0.0.1:{port}/callback?code=abc&state={session.state}"
        )
    assert resp.status_code == 200
    assert "close this tab" in resp.text.lower()

    # Give the handler a tick to finish.
    await asyncio.sleep(0.05)
    assert seen == {"code": "abc", "state": session.state}
    assert session.status == "connected"

    await oauth.stop_listener(session)


async def test_listener_rejects_state_mismatch() -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()

    async def _on_cb(s, code, state):  # should never be called
        pytest.fail("callback fired despite state mismatch")

    port = _free_port()
    await oauth.start_listener(
        session, on_callback=_on_cb, port=port, timeout_seconds=5.0
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"http://127.0.0.1:{port}/callback?code=x&state=wrong-state"
        )
    assert resp.status_code == 400
    await asyncio.sleep(0.05)
    assert session.status == "error"

    await oauth.stop_listener(session)


async def test_listener_port_in_use_raises() -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()

    port = _free_port()
    blocker = await asyncio.start_server(
        lambda r, w: w.close(), host="127.0.0.1", port=port
    )

    try:
        with pytest.raises(oauth.Port3000UnavailableError):
            await oauth.start_listener(
                session, on_callback=lambda *_: None, port=port
            )
    finally:
        blocker.close()
        await blocker.wait_closed()


async def test_listener_timeout_marks_session() -> None:
    store = oauth.OAuthSessionStore()
    session = store.create()

    async def _on_cb(*_):
        pytest.fail("callback should not fire for timeout test")

    port = _free_port()
    await oauth.start_listener(
        session, on_callback=_on_cb, port=port, timeout_seconds=0.2
    )
    # Wait for the timeout to fire.
    await asyncio.sleep(0.4)
    assert session.status == "timeout"


# ---------------------------------------------------------------------------
# Code exchange (C4)
# ---------------------------------------------------------------------------


async def test_exchange_code_happy_path(httpx_mock) -> None:
    httpx_mock.add_response(
        url=oauth.OPENROUTER_TOKEN_URL,
        method="POST",
        status_code=200,
        json={"key": "sk-or-v1-abc", "user_email": "a@b.co"},
    )
    data = await oauth.exchange_code("authcode-1", "verifier-1")
    assert data["key"] == "sk-or-v1-abc"
    assert data["user_email"] == "a@b.co"


async def test_exchange_code_400_raises(httpx_mock) -> None:
    httpx_mock.add_response(
        url=oauth.OPENROUTER_TOKEN_URL,
        method="POST",
        status_code=400,
    )
    with pytest.raises(oauth.OAuthExchangeError):
        await oauth.exchange_code("bad", "bad")


async def test_exchange_code_missing_key_raises(httpx_mock) -> None:
    httpx_mock.add_response(
        url=oauth.OPENROUTER_TOKEN_URL,
        method="POST",
        status_code=200,
        json={"foo": "bar"},
    )
    with pytest.raises(oauth.OAuthExchangeError):
        await oauth.exchange_code("c", "v")


async def test_exchange_code_network_raises(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("down"))
    with pytest.raises(oauth.OAuthExchangeError):
        await oauth.exchange_code("c", "v")


# ---------------------------------------------------------------------------
# Auth URL builder
# ---------------------------------------------------------------------------


def test_build_auth_url_contains_required_params() -> None:
    url = oauth.build_auth_url("challenge-x", "state-y")
    assert "openrouter.ai/auth" in url
    assert "code_challenge=challenge-x" in url
    assert "code_challenge_method=S256" in url
    assert "state=state-y" in url
    assert "callback_url=" in url
    assert "localhost%3A3000%2Fcallback" in url
