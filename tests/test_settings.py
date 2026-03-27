"""Tests for app_settings DB operations and Settings API."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from backend.config import DEFAULT_APP_SETTINGS
from backend.db.database import get_all_settings, get_setting, update_settings


class TestSettingsDB:
    async def test_defaults_seeded(self, init_db):
        """init_db should seed default settings."""
        all_settings = await get_all_settings()
        assert all_settings["vengine_host"] == "localhost"
        assert all_settings["detection_port"] == "50051"
        assert all_settings["ocr_port"] == "50054"

    async def test_get_setting(self, init_db):
        val = await get_setting("vengine_host")
        assert val == "localhost"

    async def test_get_setting_missing(self, init_db):
        val = await get_setting("nonexistent_key")
        assert val is None

    async def test_update_settings(self, init_db):
        result = await update_settings({"vengine_host": "192.168.1.100", "detection_port": "9001"})
        assert result["vengine_host"] == "192.168.1.100"
        assert result["detection_port"] == "9001"
        # Other defaults should still be there
        assert result["ocr_port"] == "50054"

    async def test_update_new_key(self, init_db):
        result = await update_settings({"custom_key": "custom_value"})
        assert result["custom_key"] == "custom_value"

    async def test_idempotent_init(self, init_db):
        """Calling init_db again should not duplicate settings."""
        from backend.db.database import init_db as re_init
        await re_init()
        all_settings = await get_all_settings()
        # Should still only have the default keys (no duplicates)
        assert all_settings["vengine_host"] == "localhost"


class TestSettingsAPI:
    async def test_get_settings(self, async_client: AsyncClient):
        resp = await async_client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vengine_host"] == "localhost"
        assert data["detection_port"] == "50051"

    async def test_update_settings(self, async_client: AsyncClient):
        resp = await async_client.put(
            "/api/settings",
            json={"vengine_host": "10.0.0.1", "detection_port": "9999"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["vengine_host"] == "10.0.0.1"
        assert data["detection_port"] == "9999"

    async def test_update_empty(self, async_client: AsyncClient):
        """Empty update should return current settings."""
        resp = await async_client.put("/api/settings", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "vengine_host" in data


class TestVEngineClientAddresses:
    def test_build_addresses(self):
        from backend.vengine.client import AsyncVEngineClient

        addrs = AsyncVEngineClient._build_addresses({
            "vengine_host": "10.0.0.5",
            "detection_port": "8001",
            "classification_port": "8002",
            "action_port": "8003",
            "ocr_port": "8004",
            "upload_port": "8005",
        })
        assert addrs["detection"] == "10.0.0.5:8001"
        assert addrs["classification"] == "10.0.0.5:8002"
        assert addrs["action"] == "10.0.0.5:8003"
        assert addrs["ocr"] == "10.0.0.5:8004"
        assert addrs["upload"] == "10.0.0.5:8005"

    def test_build_addresses_defaults(self):
        from backend.vengine.client import AsyncVEngineClient

        addrs = AsyncVEngineClient._build_addresses({})
        assert addrs["detection"] == "localhost:50051"
        assert addrs["upload"] == "localhost:50050"
