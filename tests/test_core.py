"""Tests for the core minimal package.
测试 core 最小包。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import numpy as np
import pytest

from core.base_processor import (
    AnalysisResult,
    BaseVideoProcessor,
    ROI,
    ROIPoint,
)


class DummyCoreProcessor(BaseVideoProcessor):
    """Concrete processor for testing the core package.
    用于测试 core 包的具体处理器。"""

    async def process_frame(self, frame, encoded, shape, roi_pixel_points):
        return AnalysisResult(extra={"tested": True})


class TestCoreAnalysisResult:
    def test_defaults(self):
        r = AnalysisResult()
        assert r.detections == []
        assert r.annotated_frame is None
        assert r.extra == {}


class TestCoreBaseVideoProcessor:
    def _make(self) -> DummyCoreProcessor:
        roi = ROI(
            id="r1",
            type="rectangle",
            points=[ROIPoint(x=0.1, y=0.2), ROIPoint(x=0.9, y=0.8)],
            tag="zone",
        )
        return DummyCoreProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            rois=[roi],
            app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
        )

    def test_init(self):
        proc = self._make()
        assert proc.source_id == "s1"
        assert proc.status == "stopped"

    def test_stream_key(self):
        proc = self._make()
        assert proc._stream_key() == "cam1"

    def test_normalize_rois(self):
        proc = self._make()
        result = proc._normalize_rois_to_pixels(1920, 1080)
        assert len(result) == 1
        pts = result[0]
        assert pts[0] == {"x": int(0.1 * 1920), "y": int(0.2 * 1080)}
        assert pts[1] == {"x": int(0.9 * 1920), "y": int(0.8 * 1080)}

    def test_draw_on_frame(self):
        proc = self._make()
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        result = AnalysisResult()
        out = proc.draw_on_frame(frame, result)
        assert out.shape == frame.shape
        assert np.array_equal(frame, np.zeros_like(frame))

    async def test_start_stop(self):
        proc = self._make()
        proc._run_loop = AsyncMock()
        await proc.start()
        assert proc.status == "running"
        await proc.stop()
        assert proc.status == "stopped"


class TestCoreBackendInheritance:
    """Verify backend.processing.base inherits from core.base_processor.
    验证 backend.processing.base 继承自 core.base_processor。"""

    def test_backend_inherits_from_core(self):
        """Backend BaseVideoProcessor should be a subclass of core's.
        后台 BaseVideoProcessor 应为 core 的子类。"""
        from backend.processing.base import BaseVideoProcessor as BackendBVP
        from core.base_processor import BaseVideoProcessor as CoreBVP
        assert issubclass(BackendBVP, CoreBVP)

    def test_analysis_result_is_same(self):
        """Backend's AnalysisResult should be the same class as core's.
        后台的 AnalysisResult 应与 core 的为同一类。"""
        from backend.processing.base import AnalysisResult as BackendAR
        from core.base_processor import AnalysisResult as CoreAR
        assert BackendAR is CoreAR


class TestCoreVEngineClient:
    """Tests for the core AsyncVEngineClient.
    测试 core 的 AsyncVEngineClient。"""

    def test_init(self):
        """Core client should initialize without any config object.
        核心客户端应无需配置对象即可初始化。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        assert client._channels == {}
        assert client._stubs == {}

    async def test_connect_creates_channels(self):
        """Connect should create channels for enabled services.
        连接应为已启用的服务创建通道。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        await client.connect()
        assert "detection" in client._channels
        assert "classification" in client._channels
        assert "action" in client._channels
        assert "ocr" in client._channels
        assert "upload" in client._channels
        await client.close()

    async def test_connect_with_custom_settings(self):
        """Connect with custom settings should respect enabled flags.
        使用自定义设置连接应尊重启用标志。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        await client.connect({
            "detection_enabled": "true",
            "classification_enabled": "false",
            "action_enabled": "false",
            "ocr_enabled": "true",
            "upload_enabled": "false",
            "vengine_host": "localhost",
            "detection_port": "50051",
            "ocr_port": "50054",
        })
        assert "detection" in client._channels
        assert "ocr" in client._channels
        assert "classification" not in client._channels
        assert "action" not in client._channels
        assert "upload" not in client._channels
        await client.close()

    async def test_close_idempotent(self):
        """Close should be safe to call multiple times.
        多次调用 close 应安全。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        await client.connect()
        await client.close()
        await client.close()  # Should not raise

    def test_make_header(self):
        """_make_header should produce a valid request header.
        _make_header 应生成有效的请求头。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        header = client._make_header("test-core")
        assert header.client_id == "test-core"
        assert header.request_id
        assert header.request_timestamp > 0

    def test_make_roi_polygon(self):
        """_make_roi_polygon should produce correct polygon.
        _make_roi_polygon 应生成正确的多边形。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        poly = client._make_roi_polygon([{"x": 10, "y": 20}, {"x": 30, "y": 40}])
        assert len(poly.points) == 2
        assert poly.points[0].x == 10.0
        assert poly.points[1].y == 40.0

    def test_make_image_from_bytes(self):
        """_make_image with image_bytes should set data field.
        使用 image_bytes 的 _make_image 应设置 data 字段。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        img = client._make_image((100, 200, 3), image_bytes=b"jpeg-data")
        assert img.data == b"jpeg-data"
        assert img.shape.dims == [100, 200, 3]

    def test_make_image_from_key(self):
        """_make_image with image_key should set key field.
        使用 image_key 的 _make_image 应设置 key 字段。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        img = client._make_image((100, 200, 3), image_key="abc-key-123")
        assert img.key == "abc-key-123"
        assert img.shape.dims == [100, 200, 3]

    def test_make_image_neither_raises(self):
        """_make_image with no bytes/key should raise ValueError.
        不提供 bytes/key 的 _make_image 应引发 ValueError。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        with pytest.raises(ValueError, match="Provide either"):
            client._make_image((100, 200, 3))

    def test_make_image_both_raises(self):
        """_make_image with both bytes and key should raise ValueError.
        同时提供 bytes 和 key 的 _make_image 应引发 ValueError。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        with pytest.raises(ValueError, match="only one"):
            client._make_image((100, 200, 3), image_bytes=b"x", image_key="k")

    async def test_disabled_detect_returns_empty(self):
        """Disabled detection should return empty list.
        禁用的检测应返回空列表。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        client._enabled = {"detection": False}
        result = await client.detect(shape=(100, 200, 3), model_name="test", image_bytes=b"x")
        assert result == []

    async def test_disabled_classify_returns_empty(self):
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        client._enabled = {"classification": False}
        result = await client.classify(shape=(100, 200, 3), model_name="test", image_bytes=b"x")
        assert result == []

    async def test_disabled_ocr_returns_empty(self):
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        client._enabled = {"ocr": False}
        result = await client.ocr(shape=(100, 200, 3), model_name="test", image_bytes=b"x")
        assert result == []

    async def test_disabled_upload_returns_empty(self):
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        client._enabled = {"upload": False}
        result = await client.upload_image(b"x")
        assert result == []

    async def test_disabled_upload_and_get_key_returns_none(self):
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        client._enabled = {"upload": False}
        result = await client.upload_and_get_key(b"x")
        assert result is None

    async def test_disabled_action_returns_empty(self):
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        client._enabled = {"action": False}
        result = await client.recognize_action(
            frames_bytes=[b"x"], shapes=[(100, 200, 3)], model_name="test"
        )
        assert result == []


class TestCoreBackendVEngineInheritance:
    """Verify backend.vengine.client inherits from core.vengine_client.
    验证 backend.vengine.client 继承自 core.vengine_client。"""

    def test_backend_client_inherits_from_core(self):
        """Backend AsyncVEngineClient should be a subclass of core's.
        后台 AsyncVEngineClient 应为 core 的子类。"""
        from backend.vengine.client import AsyncVEngineClient as BackendClient
        from core.vengine_client import AsyncVEngineClient as CoreClient
        assert issubclass(BackendClient, CoreClient)

    def test_backend_client_accepts_settings(self):
        """Backend client should accept Settings object.
        后台客户端应接受 Settings 对象。"""
        from backend.config import Settings
        from backend.vengine.client import AsyncVEngineClient
        cfg = Settings()
        client = AsyncVEngineClient(cfg)
        assert client._config is cfg

    def test_core_client_no_config(self):
        """Core client should work without config.
        核心客户端应无需配置即可工作。"""
        from core.vengine_client import AsyncVEngineClient
        client = AsyncVEngineClient()
        # Core client has no _config attribute
        assert not hasattr(client, "_config")


class TestCoreProtoReexport:
    """Verify backend.proto re-exports from core.proto.
    验证 backend.proto 从 core.proto 重新导出。"""

    def test_base_pb2_same_module(self):
        from backend.proto import base_pb2 as backend_base
        from core.proto import base_pb2 as core_base
        assert backend_base is core_base

    def test_detection_pb2_same_module(self):
        from backend.proto import detection_service_pb2 as backend_det
        from core.proto import detection_service_pb2 as core_det
        assert backend_det is core_det

    def test_classification_pb2_same_module(self):
        from backend.proto import classification_service_pb2 as backend_cls
        from core.proto import classification_service_pb2 as core_cls
        assert backend_cls is core_cls
