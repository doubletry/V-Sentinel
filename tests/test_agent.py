"""Tests for the truck AnalysisAgent."""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from backend.api.ws import WSManager
from backend.models.schemas import AnalysisMessage
from backend.processing.truck.agent import AnalysisAgent
from backend.processing.base import AnalysisResult


class TestAnalysisAgentLifecycle:
    async def test_start_stop(self):
        ws = WSManager()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=1.0)
        await agent.start()
        assert agent._task is not None
        assert not agent._task.done()
        await agent.stop()

    async def test_double_stop(self):
        ws = WSManager()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=1.0)
        await agent.start()
        await agent.stop()
        await agent.stop()  # Should not raise


class TestAnalysisAgentSubmit:
    async def test_submit_forwards_messages(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=60.0)

        msg = AnalysisMessage(
            timestamp="2024-01-01T00:00:00Z",
            source_name="cam1",
            source_id="s1",
            level="info",
            message="Detected 1 object",
        )
        result = AnalysisResult(messages=[msg])
        await agent.submit("s1", "cam1", result)

        # Individual message should be forwarded immediately
        ws.broadcast.assert_awaited_once_with(msg)

    async def test_submit_queues_result(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=60.0)

        result = AnalysisResult(detections=[{"label": "car"}])
        await agent.submit("s1", "cam1", result)

        assert not agent._queue.empty()

    async def test_submit_with_no_messages(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=60.0)

        result = AnalysisResult()
        await agent.submit("s1", "cam1", result)

        # No broadcast for individual messages
        ws.broadcast.assert_not_awaited()
        # But result should still be queued
        assert not agent._queue.empty()


class TestAnalysisAgentBuildSummary:
    def test_empty_items(self):
        summary = AnalysisAgent._build_summary([])
        assert summary is None

    def test_truck_agent_suppresses_generic_summary(self):
        result = AnalysisResult(detections=[{"label": "person"}])
        summary = AnalysisAgent._build_summary([("s1", "Camera 1", result)])
        assert summary is None

    def test_daily_summary_text_uses_configured_timezone(self):
        text = AnalysisAgent.build_daily_summary_text(
            [],
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T01:00:00+00:00",
            timezone_name="Asia/Shanghai",
        )
        assert "2026-01-01 08:00" in text
        assert "2026-01-01 09:00" in text

    def test_translate_visits_returns_chinese_actions(self):
        visits = [{
            "source_id": "s1",
            "source_name": "Cam1",
            "confirmed_actions": ["HandOverKeys"],
            "missing_actions": ["TakePhotosOfSeal"],
        }]
        translated = AnalysisAgent.translate_visits(visits)
        assert translated[0]["confirmed_actions"] == ["上交钥匙"]
        assert translated[0]["missing_actions"] == ["封条拍照"]

    def test_build_daily_summary_table_rows_merges_all_sources(self):
        rows = AnalysisAgent.build_daily_summary_table_rows([
            {"source_name": "Cam1", "missing_actions": ["HandOverKeys"]},
            {"source_name": "Cam2", "missing_actions": []},
        ])
        assert rows == [
            ["1", "", "Cam1", "货台检查", "上交钥匙"],
            ["2", "", "Cam2", "货台检查", "无异常"],
        ]


class TestAnalysisAgentAggregation:
    async def test_aggregation_does_not_broadcast_generic_summary(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()

        # Use a very short interval for testing
        agent = AnalysisAgent(ws_manager=ws, summary_interval=0.2)
        await agent.start()

        # Submit some results
        r1 = AnalysisResult(detections=[{"label": "person"}])
        r2 = AnalysisResult(detections=[{"label": "car"}])
        await agent.submit("s1", "Cam1", r1)
        await agent.submit("s2", "Cam2", r2)

        # Wait for the aggregation cycle
        await asyncio.sleep(0.5)

        await agent.stop()

        ws.broadcast.assert_not_awaited()

    async def test_truck_agent_daily_summary_broadcasts_message(self, monkeypatch):
        ws = WSManager()
        ws.broadcast = AsyncMock()
        fake_email_client = AsyncMock()

        async def fake_visits(_since: str) -> list[dict]:
            return [{
                "source_id": "s1",
                "source_name": "Cam1",
                "track_id": 1,
                "plate": "ABC123",
                "confirmed_actions": ["HandOverKeys"],
                "missing_actions": [],
            }]

        monkeypatch.setattr(
            "backend.processing.truck.agent.get_vehicle_visits_since",
            fake_visits,
        )
        async def fake_settings() -> dict[str, str]:
            return {
                "email_from_address": "sender@example.com",
                "email_from_auth_code": "secret",
                "email_to_addresses": "to@example.com",
                "email_cc_addresses": "",
                "vengine_host": "localhost",
                "email_port": "50055",
            }

        monkeypatch.setattr("backend.db.database.get_all_settings", fake_settings)
        agent = AnalysisAgent(
            ws_manager=ws,
            email_client=fake_email_client,
            summary_interval=60.0,
        )

        await agent._generate_daily_summary()

        ws.broadcast.assert_awaited_once()
        sent = ws.broadcast.await_args.args[0]
        assert isinstance(sent, AnalysisMessage)
        assert sent.source_id == "__daily_summary__"
        assert "ABC123" in sent.message
        fake_email_client.send_daily_summary_email.assert_awaited_once()

    async def test_truck_agent_daily_summary_target_uses_settings(self, monkeypatch):
        ws = WSManager()
        fake_email_client = AsyncMock()

        async def fake_settings() -> dict[str, str]:
            return {
                "daily_summary_hour": "21",
                "daily_summary_minute": "30",
            }

        monkeypatch.setattr("backend.db.database.get_all_settings", fake_settings)
        agent = AnalysisAgent(
            ws_manager=ws,
            email_client=fake_email_client,
            summary_interval=60.0,
        )

        target = await agent._get_daily_summary_target(datetime(2026, 1, 1, 20, 0, 0))
        assert target.hour == 21
        assert target.minute == 30
