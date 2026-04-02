"""Tests for app_settings DB operations and Settings API."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from backend.config import DEFAULT_APP_SETTINGS
from backend.db.database import get_all_settings, get_setting, update_settings


class TestSettingsDB:
    async def test_defaults_seeded(self, init_db):
        """init_db should seed default settings."""
        all_settings = await get_all_settings()
        assert all_settings["ui_language"] == "zh-CN"
        assert all_settings["timezone"] == "Asia/Shanghai"
        assert all_settings["site_title"] == "V-Sentinel"
        assert all_settings["favicon_url"] == "/favicon.ico"
        assert all_settings["processor_plugin"] == "truck"
        assert "roi_tag_options" in all_settings
        assert all_settings["vengine_host"] == "localhost"
        assert all_settings["detection_port"] == "50051"
        assert all_settings["ocr_port"] == "50054"
        assert all_settings["email_from_address"] == ""
        assert all_settings["email_to_addresses"] == ""
        assert all_settings["email_port"] == "50055"
        assert all_settings["daily_summary_hour"] == "23"
        assert all_settings["daily_summary_minute"] == "59"
        assert all_settings["message_retention_days"] == "7"

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
            json={
                "vengine_host": "10.0.0.1",
                "timezone": "UTC",
                "detection_port": "9999",
                "site_title": "My Sentinel",
                "processor_plugin": "example",
                "roi_tag_options": "[\"person\",\"vehicle\"]",
                "email_from_address": "sender@example.com",
                "email_from_auth_code": "secret",
                "email_to_addresses": "to1@example.com,to2@example.com",
                "email_cc_addresses": "cc@example.com",
                "email_port": "50060",
                "daily_summary_hour": "21",
                "daily_summary_minute": "30",
                "message_retention_days": "14",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["vengine_host"] == "10.0.0.1"
        assert data["timezone"] == "UTC"
        assert data["detection_port"] == "9999"
        assert data["site_title"] == "My Sentinel"
        assert data["processor_plugin"] == "example"
        assert data["roi_tag_options"] == "[\"person\",\"vehicle\"]"
        assert data["email_from_address"] == "sender@example.com"
        assert data["email_from_auth_code"] == "secret"
        assert data["email_to_addresses"] == "to1@example.com,to2@example.com"
        assert data["email_cc_addresses"] == "cc@example.com"
        assert data["email_port"] == "50060"
        assert data["daily_summary_hour"] == "21"
        assert data["daily_summary_minute"] == "30"
        assert data["message_retention_days"] == "14"

    async def test_update_empty(self, async_client: AsyncClient):
        """Empty update should return current settings."""
        resp = await async_client.put("/api/settings", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "vengine_host" in data

    async def test_email_test_endpoint(self, async_client: AsyncClient):
        from backend.main import app

        app.state.email_client.send_test_email = AsyncMock(
            return_value={"status": "SUCCESS", "message": "ok", "email_id": "1"}
        )
        app.state.email_client.reconnect_from_settings = AsyncMock()

        resp = await async_client.post(
            "/api/settings/email/test",
            json={
                "vengine_host": "127.0.0.1",
                "email_port": "50055",
                "email_from_address": "sender@example.com",
                "email_from_auth_code": "secret",
                "email_to_addresses": "to@example.com",
                "email_cc_addresses": "cc@example.com",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        app.state.email_client.reconnect_from_settings.assert_awaited_once()
        app.state.email_client.send_test_email.assert_awaited_once()


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
