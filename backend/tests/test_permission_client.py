"""Tests for OpenCode client permission event handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from cliff.engine.client import OpenCodeClient


def _make_mock_http_client():
    """Create a mock httpx.AsyncClient that passes _get_client() checks."""
    mock = AsyncMock()
    type(mock).is_closed = PropertyMock(return_value=False)
    return mock


class TestPermissionEventDetection:
    @pytest.mark.asyncio
    async def test_permission_asked_event_detected(self):
        """Client yields permission_request for permission.asked events."""
        sse_data = (
            'data: {"type":"permission.asked","properties":{'
            '"id":"per_123","permission":"bash",'
            '"patterns":["ls -la"],"always":[],'
            '"metadata":{},"sessionID":"ses_test",'
            '"tool":{"messageID":"msg_1","callID":"call_1"}'
            "}}\n\n"
            'data: {"type":"session.idle","properties":{'
            '"sessionID":"ses_test"}}\n\n'
        )

        client = OpenCodeClient(base_url="http://localhost:9999")
        mock_http = _make_mock_http_client()

        async def mock_aiter_text():
            yield sse_data

        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.aiter_text = mock_aiter_text

        # stream() returns a context manager, not a coroutine
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_stream(*args, **kwargs):
            yield mock_resp

        mock_http.stream = mock_stream
        client._client = mock_http

        events = []
        async for event in client.stream_events("ses_test"):
            events.append(event)

        # permission_pending logic: session.idle after permission.asked
        # is skipped, so only the permission_request event comes through.
        # The stream ends when the SSE connection closes (no more data).
        assert len(events) == 1
        assert events[0]["type"] == "permission_request"
        assert events[0]["id"] == "per_123"
        assert events[0]["tool"] == "bash"
        assert events[0]["patterns"] == ["ls -la"]


class TestPermissionGrantDeny:
    @pytest.mark.asyncio
    async def test_grant_permission(self):
        """grant_permission POSTs to /session/{sid}/permissions/{pid}."""
        client = OpenCodeClient(base_url="http://localhost:9999")
        mock_http = _make_mock_http_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_http.post.return_value = mock_resp
        client._client = mock_http

        await client.grant_permission("per_123", session_id="ses_abc")
        mock_http.post.assert_called_once_with(
            "/session/ses_abc/permissions/per_123",
            json={"response": "once"},
        )

    @pytest.mark.asyncio
    async def test_grant_permission_always(self):
        """grant_permission with always=True sends 'always' response."""
        client = OpenCodeClient(base_url="http://localhost:9999")
        mock_http = _make_mock_http_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_http.post.return_value = mock_resp
        client._client = mock_http

        await client.grant_permission("per_123", session_id="ses_abc", always=True)
        mock_http.post.assert_called_once_with(
            "/session/ses_abc/permissions/per_123",
            json={"response": "always"},
        )

    @pytest.mark.asyncio
    async def test_deny_permission(self):
        """deny_permission POSTs reject to /session/{sid}/permissions/{pid}."""
        client = OpenCodeClient(base_url="http://localhost:9999")
        mock_http = _make_mock_http_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_http.post.return_value = mock_resp
        client._client = mock_http

        await client.deny_permission("per_456", session_id="ses_abc")
        mock_http.post.assert_called_once_with(
            "/session/ses_abc/permissions/per_456",
            json={"response": "reject"},
        )

