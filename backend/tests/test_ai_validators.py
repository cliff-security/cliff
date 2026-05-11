"""Tests for the BYOK key validators (IMPL-0011 Phase D1).

Uses ``pytest-httpx`` to inject deterministic HTTP responses against each
provider's auth surface. Validators must classify outcomes into the typed
``ValidationResult`` shape.
"""

from __future__ import annotations

import httpx

from opensec.ai import validators

# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------


async def test_validate_openrouter_happy_path(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/key",
        method="GET",
        status_code=200,
        json={"data": {"label": "ok"}},
    )
    result = await validators.validate_openrouter("sk-or-key")
    assert result.ok is True
    assert result.error_code is None


async def test_validate_openrouter_auth_failed(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/key",
        method="GET",
        status_code=401,
    )
    result = await validators.validate_openrouter("bad")
    assert result.ok is False
    assert result.error_code == "auth_failed"


async def test_validate_openrouter_network(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("network down"))
    result = await validators.validate_openrouter("sk-or-key")
    assert result.ok is False
    assert result.error_code == "network"


async def test_validate_openrouter_timeout(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    result = await validators.validate_openrouter("sk-or-key")
    assert result.error_code == "network"


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


async def test_validate_anthropic_happy_path(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    result = await validators.validate_anthropic("sk-ant-key")
    assert result.ok is True


async def test_validate_anthropic_auth_failed(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=401,
    )
    result = await validators.validate_anthropic("bad")
    assert result.error_code == "auth_failed"
    assert "Anthropic" in result.error_message


async def test_validate_anthropic_no_access_for_400(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=400,
        json={"error": "no billing"},
    )
    result = await validators.validate_anthropic("sk-ant-key")
    assert result.error_code == "no_access"


async def test_validate_anthropic_rate_limit(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=429,
    )
    result = await validators.validate_anthropic("sk-ant-key")
    assert result.error_code == "rate_limited"


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


async def test_validate_openai_happy_path(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        status_code=200,
        json={"choices": []},
    )
    result = await validators.validate_openai("sk-openai-key")
    assert result.ok is True


async def test_validate_openai_model_not_found(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        status_code=404,
    )
    result = await validators.validate_openai("sk-openai-key")
    assert result.error_code == "model_not_found"


async def test_validate_openai_403(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        status_code=403,
    )
    result = await validators.validate_openai("sk-openai-key")
    assert result.error_code == "auth_failed"


# ---------------------------------------------------------------------------
# Custom
# ---------------------------------------------------------------------------


async def test_validate_custom_requires_base_url() -> None:
    result = await validators.validate("custom", "sk-x", base_url=None)
    assert result.ok is False
    assert result.error_code == "no_access"


async def test_validate_custom_happy_path(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://my-llm.example/v1/chat/completions",
        method="POST",
        status_code=200,
        json={"choices": []},
    )
    result = await validators.validate(
        "custom",
        "sk-anything",
        base_url="https://my-llm.example/v1",
        model="llama-3",
    )
    assert result.ok is True


async def test_validate_custom_strips_trailing_slash(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://my-llm.example/v1/chat/completions",
        method="POST",
        status_code=401,
    )
    result = await validators.validate(
        "custom", "sk-x", base_url="https://my-llm.example/v1/"
    )
    assert result.error_code == "auth_failed"


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------


async def test_dispatcher_routes_to_anthropic(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        method="POST",
        status_code=200,
        json={"content": []},
    )
    result = await validators.validate("anthropic", "sk-ant-key")
    assert result.ok is True
