"""Tests for the Processor REST API endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestProcessorStatus:
    async def test_status_empty(self, async_client: AsyncClient):
        resp = await async_client.get("/api/processor/status")
        assert resp.status_code == 200
        assert resp.json() == []


class TestProcessorStartStop:
    async def test_start_nonexistent(self, async_client: AsyncClient):
        resp = await async_client.post(
            "/api/processor/start", json={"source_id": "nonexistent"}
        )
        assert resp.status_code == 404

    async def test_stop_not_running(self, async_client: AsyncClient):
        resp = await async_client.post(
            "/api/processor/stop", json={"source_id": "any-id"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_running"
