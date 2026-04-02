"""Tests for the Processor REST API endpoints."""
from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient

from backend.processing.log_buffer import processing_log_buffer


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


class TestProcessorGlobalControl:
    async def test_start_all_no_sources(self, async_client: AsyncClient):
        resp = await async_client.post("/api/processor/start-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_sources"
        assert data["total"] == 0

    async def test_stop_all_not_running(self, async_client: AsyncClient):
        resp = await async_client.post("/api/processor/stop-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_running"
        assert data["stopped"] == 0


class TestProcessorLogs:
    async def test_get_processing_logs_page(self, async_client: AsyncClient):
        resp = await async_client.get(
            "/api/processor/logs",
            params={"page": 1, "page_size": 10},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "items" in data
        assert "page" in data
        assert "page_size" in data
        assert "total" in data
        assert "total_pages" in data
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert isinstance(data["items"], list)

        if data["items"]:
            first = data["items"][0]
            assert "timestamp" in first
            assert "level" in first
            assert "module" in first
            assert "message" in first

    async def test_processing_logs_capture_uvicorn_access_and_core_modules(
        self, async_client: AsyncClient
    ):
        from backend.main import _should_capture_runtime_log

        processing_log_buffer.clear()
        assert _should_capture_runtime_log("core.truck.processor") is True
        assert _should_capture_runtime_log("uvicorn.access") is True
        assert _should_capture_runtime_log("random.module") is False

        uvicorn_logger = logging.getLogger("uvicorn.access")
        original_level = uvicorn_logger.level
        uvicorn_logger.setLevel(logging.INFO)
        uvicorn_logger.info('127.0.0.1 - "GET /health HTTP/1.1" 200 OK')

        resp = await async_client.get("/api/processor/logs", params={"page": 1, "page_size": 20})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(item["module"] == "uvicorn.access" for item in items)
        uvicorn_logger.setLevel(original_level)
