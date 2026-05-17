"""Tests for session endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

from cliff.engine.models import MessageInfo, SessionDetail


def test_create_session_success(client):
    resp = client.post("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "test-session-123"


def test_create_session_engine_down(client, mock_opencode_client):
    mock_opencode_client.sessions.create_session = AsyncMock(
        side_effect=Exception("Connection refused")
    )
    resp = client.post("/api/sessions")
    assert resp.status_code == 502


def test_list_sessions_success(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "test-session-123"


def test_get_session_success(client, mock_opencode_client):
    mock_opencode_client.sessions.get_session = AsyncMock(
        return_value=SessionDetail(
            id="test-session-123",
            messages=[
                MessageInfo(id="msg_1", role="user", content="hello"),
            ],
        )
    )
    resp = client.get("/api/sessions/test-session-123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "test-session-123"
    assert len(data["messages"]) == 1
