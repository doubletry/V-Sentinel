from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
