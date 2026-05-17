"""Tests for Pydantic models."""

from cliff.engine.models import (
    HealthStatus,
    MessageInfo,
    SessionDetail,
    SessionSummary,
    SSEEvent,
)


def test_session_summary_serialization():
    s = SessionSummary(id="ses_abc123")
    assert s.id == "ses_abc123"
    assert s.created_at is None
    data = s.model_dump()
    assert data["id"] == "ses_abc123"


def test_session_detail_with_messages():
    msg = MessageInfo(id="msg_1", role="user", content="hello")
    detail = SessionDetail(id="ses_abc", messages=[msg])
    assert len(detail.messages) == 1
    assert detail.messages[0].role == "user"
    assert detail.messages[0].content == "hello"


def test_health_status_defaults():
    h = HealthStatus()
    assert h.cliff == "ok"
    assert h.opencode == "unknown"
    assert h.opencode_version == ""


def test_sse_event_model():
    e = SSEEvent(event="done", data='{"result": "ok"}')
    assert e.event == "done"
    assert e.data == '{"result": "ok"}'

    default = SSEEvent()
    assert default.event == "message"
    assert default.data == ""
