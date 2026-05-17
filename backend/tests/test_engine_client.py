"""Tests for the OpenCode HTTP client."""

from __future__ import annotations

import pytest

from cliff.engine.client import OpenCodeClient


@pytest.fixture
def oc_client():
    return OpenCodeClient(base_url="http://mock:4096")


@pytest.mark.asyncio
async def test_create_session(oc_client, httpx_mock):
    httpx_mock.add_response(
        url="http://mock:4096/session",
        method="POST",
        json={"id": "ses_test123"},
    )
    session = await oc_client.create_session()
    assert session.id == "ses_test123"


@pytest.mark.asyncio
async def test_list_sessions(oc_client, httpx_mock):
    httpx_mock.add_response(
        url="http://mock:4096/session",
        method="GET",
        json=[
            {"id": "ses_1"},
            {"id": "ses_2"},
        ],
    )
    sessions = await oc_client.list_sessions()
    assert len(sessions) == 2
    assert sessions[0].id == "ses_1"
    assert sessions[1].id == "ses_2"


@pytest.mark.asyncio
async def test_get_session_with_messages(oc_client, httpx_mock):
    httpx_mock.add_response(
        url="http://mock:4096/session/ses_test123",
        method="GET",
        json={"id": "ses_test123"},
    )
    httpx_mock.add_response(
        url="http://mock:4096/session/ses_test123/message",
        method="GET",
        json=[
            {
                "info": {"id": "msg_1", "role": "user", "sessionID": "ses_test123"},
                "parts": [{"type": "text", "text": "hello"}],
            },
            {
                "info": {"id": "msg_2", "role": "assistant", "sessionID": "ses_test123"},
                "parts": [{"type": "text", "text": "hi there"}],
            },
        ],
    )
    detail = await oc_client.get_session("ses_test123")
    assert detail.id == "ses_test123"
    assert len(detail.messages) == 2
    assert detail.messages[0].content == "hello"
    assert detail.messages[1].role == "assistant"


@pytest.mark.asyncio
async def test_send_message(oc_client, httpx_mock):
    httpx_mock.add_response(
        url="http://mock:4096/session/ses_test123/message",
        method="POST",
        content=b"",  # OpenCode returns 200 with empty body (async)
    )
    await oc_client.send_message("ses_test123", "What is CVE-2024-1234?")
    # Verify the correct body format was sent
    request = httpx_mock.get_request()
    import json

    body = json.loads(request.content)
    assert body == {"parts": [{"type": "text", "text": "What is CVE-2024-1234?"}]}


@pytest.mark.asyncio
async def test_health_check_ok(oc_client, httpx_mock):
    httpx_mock.add_response(
        url="http://mock:4096/session",
        method="GET",
        json=[],
    )
    assert await oc_client.health_check() is True


@pytest.mark.asyncio
async def test_health_check_down(oc_client, httpx_mock):
    import httpx

    httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
    assert await oc_client.health_check() is False


def test_parse_sse():
    client = OpenCodeClient()

    # Standard event
    result = client._parse_sse("event: message\ndata: hello world")
    assert result == {"event": "message", "data": "hello world"}

    # Event with no explicit type
    result = client._parse_sse("data: just data")
    assert result == {"event": "message", "data": "just data"}

    # Multi-line data
    result = client._parse_sse("data: line1\ndata: line2")
    assert result == {"event": "message", "data": "line1\nline2"}

    # Comment-only (should return None)
    result = client._parse_sse(": this is a comment")
    assert result is None

    # Empty
    result = client._parse_sse("")
    assert result is None
