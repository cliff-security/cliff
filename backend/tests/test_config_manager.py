"""Tests for the ConfigManager."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from cliff.engine.config_manager import ConfigManager, mask_key


class TestMaskKey:
    def test_short_key(self):
        assert mask_key("abc") == "****"

    def test_normal_key(self):
        assert mask_key("sk-abc123def456") == "sk-...f456"

    def test_exact_boundary(self):
        assert mask_key("12345678") == "****"

    def test_just_over_boundary(self):
        assert mask_key("123456789") == "123...6789"


class TestConfigManagerGetModel:
    @pytest.mark.asyncio
    async def test_get_model_from_opencode(self):
        mgr = ConfigManager()
        with patch(
            "cliff.engine.config_manager.opencode_client"
        ) as mock_client:
            mock_client.get_config = AsyncMock(
                return_value={"model": "openai/gpt-4.1-nano"}
            )
            result = await mgr.get_model()
            assert result["model_full_id"] == "openai/gpt-4.1-nano"
            assert result["provider"] == "openai"
            assert result["model_id"] == "gpt-4.1-nano"

    @pytest.mark.asyncio
    async def test_get_model_fallback_on_error(self):
        mgr = ConfigManager()
        with (
            patch(
                "cliff.engine.config_manager.opencode_client"
            ) as mock_client,
            patch(
                "cliff.engine.config_manager.settings"
            ) as mock_settings,
        ):
            mock_client.get_config = AsyncMock(side_effect=Exception("down"))
            mock_settings.opencode_model = "anthropic/claude-sonnet-4-20250514"
            result = await mgr.get_model()
            assert result["model_full_id"] == "anthropic/claude-sonnet-4-20250514"


class TestConfigManagerUpdateModel:
    @pytest.mark.asyncio
    async def test_update_model_success(self, db_client, tmp_path):
        mgr = ConfigManager()
        opencode_json = tmp_path / "opencode.json"
        opencode_json.write_text(json.dumps({"model": "old/model", "permission": {}}))

        with (
            patch(
                "cliff.engine.config_manager.opencode_client"
            ) as mock_client,
            patch(
                "cliff.engine.config_manager.settings"
            ) as mock_settings,
        ):
            mock_client.update_config = AsyncMock(return_value={})
            mock_client.get_config = AsyncMock(
                return_value={"model": "openai/gpt-4.1-nano"}
            )
            mock_settings.repo_root = tmp_path
            mock_settings.opencode_model = "openai/gpt-4.1-nano"
            mock_settings.write_opencode_config = lambda m: opencode_json.write_text(
                json.dumps({"model": m, "permission": {}})
            )

            from cliff.db.connection import _db as db

            result = await mgr.update_model(db, "openai/gpt-4.1-nano")

            mock_client.update_config.assert_called_once_with(
                {"model": "openai/gpt-4.1-nano"}
            )
            assert result["model_full_id"] == "openai/gpt-4.1-nano"

    @pytest.mark.asyncio
    async def test_update_model_invalid_format(self, db_client):
        mgr = ConfigManager()
        from cliff.db.connection import _db as db

        with pytest.raises(ValueError, match="provider/model-id"):
            await mgr.update_model(db, "just-a-model-name")


class TestConfigManagerApiKeys:
    @pytest.mark.asyncio
    async def test_set_api_key(self, db_client):
        mgr = ConfigManager()
        with patch(
            "cliff.engine.config_manager.opencode_client"
        ) as mock_client:
            mock_client.set_auth = AsyncMock(return_value=True)

            from cliff.db.connection import _db as db

            result = await mgr.set_api_key(db, "openai", "sk-test123456abcdef")

            mock_client.set_auth.assert_called_once_with(
                "openai", {"type": "api", "key": "sk-test123456abcdef"}
            )
            assert result["provider"] == "openai"
            assert result["key_masked"] == "sk-...cdef"
            assert result["has_credentials"] is True

    @pytest.mark.asyncio
    async def test_get_api_keys_masked(self, db_client):
        mgr = ConfigManager()
        with patch(
            "cliff.engine.config_manager.opencode_client"
        ) as mock_client:
            mock_client.set_auth = AsyncMock(return_value=True)
            mock_client.get_provider_auth = AsyncMock(return_value={})

            from cliff.db.connection import _db as db

            await mgr.set_api_key(db, "openai", "sk-test123456abcdef")
            keys = await mgr.get_api_keys(db)

            assert len(keys) == 1
            assert keys[0]["provider"] == "openai"
            assert keys[0]["key_masked"] == "sk-...cdef"
            # Key should NOT be exposed
            assert "sk-test123456abcdef" not in str(keys)

    @pytest.mark.asyncio
    async def test_delete_api_key(self, db_client):
        mgr = ConfigManager()
        with patch(
            "cliff.engine.config_manager.opencode_client"
        ) as mock_client:
            mock_client.set_auth = AsyncMock(return_value=True)
            mock_client.get_provider_auth = AsyncMock(return_value={})

            from cliff.db.connection import _db as db

            await mgr.set_api_key(db, "openai", "sk-test123")
            assert await mgr.delete_api_key(db, "openai") is True
            keys = await mgr.get_api_keys(db)
            assert len(keys) == 0

    @pytest.mark.asyncio
    async def test_restore_keys_to_engine(self, db_client):
        mgr = ConfigManager()
        with patch(
            "cliff.engine.config_manager.opencode_client"
        ) as mock_client:
            mock_client.set_auth = AsyncMock(return_value=True)
            mock_client.get_provider_auth = AsyncMock(return_value={})

            from cliff.db.connection import _db as db

            await mgr.set_api_key(db, "openai", "sk-restore-test1")
            await mgr.set_api_key(db, "anthropic", "sk-ant-restore2")

            # Reset mock to track restore calls
            mock_client.set_auth.reset_mock()
            await mgr.restore_keys_to_engine(db)

            assert mock_client.set_auth.call_count == 2
