"""Tests for the AsyncVEngineClient initialisation and image building."""
from __future__ import annotations

import grpc
import pytest

from backend.config import Settings
from core.proto import base_pb2, upload_service_pb2, upload_service_pb2_grpc
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


class TestServiceToggle:
    """Tests for per-service enable/disable switches.
    测试各服务的启用/禁用开关。"""

    def test_parse_enabled_defaults(self):
        """All services enabled by default. 默认所有服务启用。"""
        enabled = AsyncVEngineClient._parse_enabled({})
        for service in AsyncVEngineClient.SERVICE_NAMES:
            assert enabled[service] is True

    def test_parse_enabled_disabled(self):
        """Disable individual services. 禁用单个服务。"""
        settings = {
            "detection_enabled": "false",
            "ocr_enabled": "0",
            "upload_enabled": "no",
        }
        enabled = AsyncVEngineClient._parse_enabled(settings)
        assert enabled["detection"] is False
        assert enabled["ocr"] is False
        assert enabled["upload"] is False
        assert enabled["classification"] is True
        assert enabled["action"] is True

    async def test_connect_skips_disabled(self):
        """Disabled services should not have channels/stubs.
        禁用的服务不应创建通道/存根。"""
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        app_settings = {
            "detection_enabled": "true",
            "classification_enabled": "false",
            "action_enabled": "false",
            "ocr_enabled": "true",
            "upload_enabled": "false",
        }
        await client.connect(app_settings)

        assert "detection" in client._channels
        assert "ocr" in client._channels
        assert "classification" not in client._channels
        assert "action" not in client._channels
        assert "upload" not in client._channels

        assert client.is_service_enabled("detection") is True
        assert client.is_service_enabled("classification") is False

        await client.close()

    async def test_disabled_detect_returns_empty(self):
        """Detect should return empty list when disabled.
        禁用时 detect 应返回空列表。"""
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        client._enabled = {"detection": False}
        result = await client.detect(
            shape=(100, 200, 3), model_name="test", image_bytes=b"x"
        )
        assert result == []

    async def test_disabled_classify_returns_empty(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        client._enabled = {"classification": False}
        result = await client.classify(
            shape=(100, 200, 3), model_name="test", image_bytes=b"x"
        )
        assert result == []

    async def test_disabled_ocr_returns_empty(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        client._enabled = {"ocr": False}
        result = await client.ocr(
            shape=(100, 200, 3), model_name="test", image_bytes=b"x"
        )
        assert result == []

    async def test_disabled_upload_returns_empty(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        client._enabled = {"upload": False}
        result = await client.upload_image(b"x")
        assert result == []

    async def test_disabled_upload_and_get_key_returns_none(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        client._enabled = {"upload": False}
        result = await client.upload_and_get_key(b"x")
        assert result is None

    async def test_disabled_action_returns_empty(self):
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        client._enabled = {"action": False}
        result = await client.recognize_action(
            frames_bytes=[b"x"], shapes=[(100, 200, 3)], model_name="test"
        )
        assert result == []


class TestUploadServiceGrpcCompatibility:
    async def test_upload_image_roundtrip_with_real_grpc_service(self):
        seen: dict[str, object] = {}

        class UploadServicer(upload_service_pb2_grpc.UploadServicer):
            async def UploadImage(self, request, context):
                seen["request_id"] = request.request_header.request_id
                seen["client_id"] = request.request_header.client_id
                seen["filename"] = request.filename
                seen["data"] = request.data
                return upload_service_pb2.UploadResponse(
                    response_header=base_pb2.ResponseHeader(
                        request_id=request.request_header.request_id,
                        status_code=base_pb2.StatusCode.STATUS_OK,
                    ),
                    results=[
                        upload_service_pb2.UploadResult(
                            key="cache-key-1",
                            hit=False,
                            id="img-1",
                            size=len(request.data),
                        )
                    ],
                )

        server = grpc.aio.server()
        upload_service_pb2_grpc.add_UploadServicer_to_server(UploadServicer(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()

        client = AsyncVEngineClient(Settings())
        try:
            await client.connect(
                {
                    "vengine_host": "127.0.0.1",
                    "upload_port": str(port),
                    "upload_enabled": "true",
                    "detection_enabled": "false",
                    "classification_enabled": "false",
                    "action_enabled": "false",
                    "ocr_enabled": "false",
                }
            )

            results = await client.upload_image(b"hello-upload", filename="frame.jpg")
            key = await client.upload_and_get_key(b"hello-upload", filename="frame.jpg")

            assert results == [
                {
                    "key": "cache-key-1",
                    "hit": False,
                    "id": "img-1",
                    "size": 12,
                }
            ]
            assert key == "cache-key-1"
            assert seen["filename"] == "frame.jpg"
            assert seen["data"] == b"hello-upload"
            assert seen["client_id"] == "v-sentinel"
            assert seen["request_id"]
        finally:
            await client.close()
            await server.stop(None)
