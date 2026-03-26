"""Tests for the WSManager class."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.ws import WSManager
from backend.models.schemas import AnalysisMessage


class TestWSManager:
    def test_init(self):
        mgr = WSManager()
        assert len(mgr._connections) == 0

    async def test_connect_and_disconnect(self):
        mgr = WSManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        assert ws in mgr._connections
        ws.accept.assert_awaited_once()

        await mgr.disconnect(ws)
        assert ws not in mgr._connections

    async def test_disconnect_unknown(self):
        mgr = WSManager()
        ws = AsyncMock()
        # Should not raise even if ws was never connected
        await mgr.disconnect(ws)

    async def test_broadcast_single(self):
        mgr = WSManager()
        ws = AsyncMock()
        await mgr.connect(ws)

        msg = AnalysisMessage(
            timestamp="2024-01-01T00:00:00Z",
            source_name="cam",
            source_id="1",
            level="info",
            message="Test",
        )
        await mgr.broadcast(msg)
        ws.send_text.assert_awaited_once()
        payload = ws.send_text.call_args[0][0]
        assert "cam" in payload
        assert "Test" in payload

    async def test_broadcast_multiple_clients(self):
        mgr = WSManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        msg = AnalysisMessage(
            timestamp="t",
            source_name="c",
            source_id="1",
            level="info",
            message="m",
        )
        await mgr.broadcast(msg)
        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

    async def test_broadcast_removes_dead_connections(self):
        mgr = WSManager()
        ws_ok = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = RuntimeError("connection closed")

        await mgr.connect(ws_ok)
        await mgr.connect(ws_dead)
        assert len(mgr._connections) == 2

        msg = AnalysisMessage(
            timestamp="t",
            source_name="c",
            source_id="1",
            level="info",
            message="m",
        )
        await mgr.broadcast(msg)

        # Dead connection should have been removed
        assert ws_dead not in mgr._connections
        assert ws_ok in mgr._connections
