"""Tests for the AsyncVEngineClient initialisation and image building."""
from __future__ import annotations

import pytest

from backend.config import Settings
from backend.vengine.client import AsyncVEngineClient


class TestAsyncVEngineClient:
    def test_init(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        assert client._channels == {}
        assert client._stubs == {}

    async def test_connect_creates_channels(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        await client.connect()

        assert "detection" in client._channels
        assert "classification" in client._channels
        assert "action" in client._channels
        assert "ocr" in client._channels
        assert "upload" in client._channels

        assert "detection" in client._stubs
        assert "classification" in client._stubs
        assert "action" in client._stubs
        assert "ocr" in client._stubs
        assert "upload" in client._stubs

        await client.close()

    async def test_close(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        await client.connect()
        await client.close()
        # Should not raise on double close
        await client.close()

    def test_make_header(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        header = client._make_header("test-client")
        assert header.client_id == "test-client"
        assert header.request_id
        assert header.request_timestamp > 0

    def test_make_roi_polygon(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        poly = client._make_roi_polygon([{"x": 10, "y": 20}, {"x": 30, "y": 40}])
        assert len(poly.points) == 2
        assert poly.points[0].x == 10.0
        assert poly.points[1].y == 40.0


class TestMakeImage:
    """Tests for _make_image (bytes vs key routing)."""

    def _client(self) -> AsyncVEngineClient:
        return AsyncVEngineClient(Settings())

    def test_from_bytes(self):
        client = self._client()
        img = client._make_image((100, 200, 3), image_bytes=b"jpeg-data")
        assert img.data == b"jpeg-data"
        assert img.shape.dims == [100, 200, 3]

    def test_from_key(self):
        client = self._client()
        img = client._make_image((100, 200, 3), image_key="abc-key-123")
        assert img.key == "abc-key-123"
        assert img.shape.dims == [100, 200, 3]

    def test_with_roi(self):
        client = self._client()
        img = client._make_image(
            (100, 200, 3),
            roi_points=[{"x": 10, "y": 20}],
            image_key="k",
        )
        assert len(img.region_of_interest.points) == 1

    def test_neither_raises(self):
        client = self._client()
        with pytest.raises(ValueError, match="Provide either"):
            client._make_image((100, 200, 3))

    def test_both_raises(self):
        client = self._client()
        with pytest.raises(ValueError, match="only one"):
            client._make_image((100, 200, 3), image_bytes=b"x", image_key="k")
