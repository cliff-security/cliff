"""Tests for the OpenCode process manager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from cliff.engine.process import OpenCodeProcess


def test_is_running_false_initially():
    proc = OpenCodeProcess()
    assert proc.is_running is False


def test_is_healthy_false_initially():
    proc = OpenCodeProcess()
    assert proc.is_healthy is False


async def test_start_scrubs_host_ai_provider_env_vars():
    """The singleton OpenCode must not inherit a polluted host AI-provider
    environment (e.g. Claude Desktop's ANTHROPIC_BASE_URL without /v1).
    The extra-env values are layered back on top. (QA Q01 B07.)"""
    proc = OpenCodeProcess()
    proc.set_extra_env({"ANTHROPIC_API_KEY": "sk-ant-real"})

    mock_subproc = AsyncMock()
    mock_subproc.returncode = None

    with (
        patch.object(
            OpenCodeProcess,
            "_ensure_binary",
            new=AsyncMock(return_value=Path("/fake/opencode")),
        ),
        patch.object(
            OpenCodeProcess, "_wait_for_healthy", new=AsyncMock()
        ),
        patch(
            "cliff.engine.process.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=mock_subproc),
        ) as mock_exec,
        patch("cliff.engine.process.os") as mock_os,
    ):
        mock_os.environ = {
            "PATH": "/usr/bin",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_API_KEY": "",
        }
        await proc.start()

    passed_env = mock_exec.call_args.kwargs.get("env")
    assert "ANTHROPIC_BASE_URL" not in passed_env
    assert passed_env["ANTHROPIC_API_KEY"] == "sk-ant-real"
    assert passed_env["PATH"] == "/usr/bin"
