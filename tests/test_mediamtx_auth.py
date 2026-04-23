"""Tests for the MediaMTX HTTP authentication callback."""
from __future__ import annotations

from httpx import AsyncClient

from backend.db.database import update_settings


class TestMediaMTXAuthAPI:
    async def test_auth_allows_configured_source_with_null_id(
        self,
        async_client: AsyncClient,
    ):
        await async_client.post(
            "/api/sources",
            json={"name": "Camera 1", "rtsp_url": "rtsp://localhost:8554/zone/cam1"},
        )
        await update_settings(
            {
                "mediamtx_rtsp_addr": "rtsp://localhost:8554",
                "mediamtx_username": "alice",
                "mediamtx_password": "s3cret",
            }
        )

        resp = await async_client.post(
            "/api/mediamtx/auth",
            json={
                "user": "alice",
                "password": "s3cret",
                "ip": "127.0.0.1",
                "action": "read",
                "path": "zone/cam1",
                "protocol": "webrtc",
                "id": None,
                "query": "",
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_auth_allows_processed_stream_path(
        self,
        async_client: AsyncClient,
    ):
        await async_client.post(
            "/api/sources",
            json={"name": "Camera 1", "rtsp_url": "rtsp://localhost:8554/cam1"},
        )

        resp = await async_client.post(
            "/api/mediamtx/auth",
            json={
                "user": "",
                "password": "",
                "ip": "127.0.0.1",
                "action": "read",
                "path": "cam1_processed",
                "protocol": "webrtc",
                "id": None,
                "query": "",
            },
        )

        assert resp.status_code == 200

    async def test_auth_rejects_invalid_credentials(
        self,
        async_client: AsyncClient,
    ):
        await async_client.post(
            "/api/sources",
            json={"name": "Camera 1", "rtsp_url": "rtsp://localhost:8554/cam1"},
        )
        await update_settings(
            {
                "mediamtx_rtsp_addr": "rtsp://localhost:8554",
                "mediamtx_username": "alice",
                "mediamtx_password": "s3cret",
            }
        )

        resp = await async_client.post(
            "/api/mediamtx/auth",
            json={
                "user": "alice",
                "password": "wrong",
                "ip": "127.0.0.1",
                "action": "read",
                "path": "cam1",
                "protocol": "webrtc",
                "id": None,
                "query": "",
            },
        )

        assert resp.status_code == 401

    async def test_auth_rejects_unknown_path(
        self,
        async_client: AsyncClient,
    ):
        resp = await async_client.post(
            "/api/mediamtx/auth",
            json={
                "user": "",
                "password": "",
                "ip": "127.0.0.1",
                "action": "read",
                "path": "missing",
                "protocol": "webrtc",
                "id": None,
                "query": "",
            },
        )

        assert resp.status_code == 401
