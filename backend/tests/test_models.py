"""Tests for Pydantic models."""

from cliff.models import HealthStatus


def test_health_status_defaults():
    h = HealthStatus()
    assert h.cliff == "ok"
    # In-process substrate (Pydantic AI): "opencode" is the kept-for-compat
    # field name and defaults to "ok" now, not the OpenCode-probe "unknown".
    assert h.opencode == "ok"
    assert h.opencode_version == ""
    assert h.ai_provider_ready is False
