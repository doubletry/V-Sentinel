from __future__ import annotations

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient

from backend.main import configure_frontend_routes


class TestFrontendRoutes:
    def test_client_route_returns_index_html(self, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html><body>spa</body></html>", encoding="utf-8")
        assets = dist / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")

        app = FastAPI()
        configure_frontend_routes(app, dist)
        client = TestClient(app)

        settings_resp = client.get("/settings")
        assert settings_resp.status_code == 200
        assert "spa" in settings_resp.text

        asset_resp = client.get("/assets/app.js")
        assert asset_resp.status_code == 200
        assert "console.log('ok')" in asset_resp.text


class TestWebRTCProxyAPI:
    async def test_proxy_whep_offer_forwards_gateway_auth(self, async_client: AsyncClient, monkeypatch):
        update_resp = await async_client.put(
            "/api/settings",
            json={
                "mediamtx_webrtc_addr": "http://gateway.example:8889",
                "mediamtx_username": "alice",
                "mediamtx_password": "secret",
            },
        )
        assert update_resp.status_code == 200

        captured: dict[str, object] = {}

        class _FakeResponse:
            status_code = 200
            content = b"answer-sdp"
            headers = {"content-type": "application/sdp"}

        class _FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                captured["timeout"] = kwargs.get("timeout")

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, content=None, headers=None):
                captured["url"] = url
                captured["content"] = content
                captured["headers"] = headers
                return _FakeResponse()

        monkeypatch.setattr("backend.api.webrtc.httpx.AsyncClient", _FakeAsyncClient)

        resp = await async_client.post(
            "/api/webrtc/cam1/whep",
            content="v=0",
            headers={"Content-Type": "application/sdp"},
        )

        assert resp.status_code == 200
        assert resp.text == "answer-sdp"
        assert captured["url"] == "http://gateway.example:8889/cam1/whep"
        assert captured["content"] == b"v=0"
        expected_auth = "Basic " + base64.b64encode(b"alice:secret").decode("ascii")
        assert captured["headers"] == {
            "Content-Type": "application/sdp",
            "Authorization": expected_auth,
        }
