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

    def test_stream_path_preserves_nested_route(self):
        proc = self._make()
        proc.rtsp_url = "rtsp://localhost:8554/zone/a01"
        assert proc._stream_path() == "zone/a01"

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
        assert isinstance(poly.points[0].x, int)
        assert isinstance(poly.points[1].y, int)
        assert poly.points[0].x == 10
        assert poly.points[1].y == 40

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


class TestCoreExampleProcessorBatchClassification:
    async def test_process_frame_reuses_image_key_for_person_rois(self):
        from core.example.processor import ExampleProcessor

        vengine = AsyncMock()
        vengine.upload_and_get_key.return_value = "frame-key"
        vengine.detect.return_value = [
            {
                "x_min": 10,
                "y_min": 20,
                "x_max": 50,
                "y_max": 80,
                "label": "person",
                "confidence": 0.95,
                "class_id": 1,
            },
            {
                "x_min": 100,
                "y_min": 120,
                "x_max": 160,
                "y_max": 220,
                "label": "car",
                "confidence": 0.70,
                "class_id": 2,
            },
            {
                "x_min": 200,
                "y_min": 220,
                "x_max": 260,
                "y_max": 320,
                "label": "person",
                "confidence": 0.88,
                "class_id": 1,
            },
        ]
        vengine.ocr.return_value = []
        vengine.classify.return_value = [
            {"label": "adult", "confidence": 0.91, "class_id": 10, "image_id": 0},
            {"label": "child", "confidence": 0.83, "class_id": 11, "image_id": 1},
        ]

        proc = ExampleProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            vengine_client=vengine,
            app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = await proc.process_frame(
            frame=frame,
            encoded=b"frame-jpeg",
            shape=(480, 640, 3),
            roi_pixel_points=[],
        )

        assert vengine.upload_and_get_key.await_count == 1
        classify_call = vengine.classify.await_args.kwargs
        assert classify_call["shape"] is None
        assert classify_call["model_name"] == proc.CLASSIFICATION_MODEL
        assert classify_call["images"] == [
            {
                "shape": (480, 640, 3),
                "roi": [
                    {"x": 10, "y": 20},
                    {"x": 50, "y": 20},
                    {"x": 50, "y": 80},
                    {"x": 10, "y": 80},
                ],
                "key": "frame-key",
            },
            {
                "shape": (480, 640, 3),
                "roi": [
                    {"x": 200, "y": 220},
                    {"x": 260, "y": 220},
                    {"x": 260, "y": 320},
                    {"x": 200, "y": 320},
                ],
                "key": "frame-key",
            },
        ]
        assert result.classifications == [
            {
                "detection_label": "person",
                "classification_label": "adult",
                "stable_label": "adult",
                "raw_label": "adult",
                "confidence": 0.91,
                "bbox": [10, 20, 50, 80],
                "person_bbox": [10, 20, 50, 80],
            },
            {
                "detection_label": "person",
                "classification_label": "child",
                "stable_label": "child",
                "raw_label": "child",
                "confidence": 0.83,
                "bbox": [200, 220, 260, 320],
                "person_bbox": [200, 220, 260, 320],
            },
        ]


class TestCoreBaseVideoProcessorPipeline:
    async def test_run_loop_allows_multiple_inflight_frames(self):
        class PipelineProcessor(BaseVideoProcessor):
            def __init__(self):
                super().__init__(
                    source_id="s1",
                    source_name="cam",
                    rtsp_url="rtsp://localhost:8554/cam1",
                    app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
                )
                self.started_two = asyncio.Event()
                self.release_first = asyncio.Event()
                self.started_count = 0

            async def process_frame(self, frame, encoded, shape, roi_pixel_points):
                self.started_count += 1
                current = self.started_count
                if current == 2:
                    self.started_two.set()
                if current == 1:
                    await self.release_first.wait()
                return AnalysisResult()

        proc = PipelineProcessor()
        proc._max_inflight_frames = 2

        def fake_reader(loop):
            frame = np.zeros((32, 32, 3), dtype=np.uint8)
            loop.call_soon_threadsafe(proc._frame_queue.put_nowait, (frame, b"a"))
            loop.call_soon_threadsafe(proc._frame_queue.put_nowait, (frame, b"b"))
            loop.call_soon_threadsafe(proc._frame_queue.put_nowait, None)

        proc._frame_reader = fake_reader
        await proc.start()
        await asyncio.wait_for(proc.started_two.wait(), timeout=1.0)
        proc.release_first.set()
        await asyncio.sleep(0.05)
        await proc.stop()

        assert proc.started_count >= 2

    async def test_display_worker_draws_and_pushes_on_demand(self):
        class DisplayProcessor(BaseVideoProcessor):
            async def process_frame(self, frame, encoded, shape, roi_pixel_points):
                return AnalysisResult()

        proc = DisplayProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
        )
        pushed: list[tuple[np.ndarray, str]] = []
        proc._push_frame = lambda frame, path: pushed.append((frame.copy(), path))
        proc._start_display_worker()
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        result = AnalysisResult(
            detections=[
                {
                    "x_min": 5,
                    "y_min": 6,
                    "x_max": 20,
                    "y_max": 30,
                    "confidence": 0.8,
                    "label": "person",
                }
            ]
        )
        proc._enqueue_display(frame, result, "cam1_processed")
        await asyncio.sleep(0.1)
        proc._stop_display_worker()

        assert len(pushed) == 1
        pushed_frame, path = pushed[0]
        assert path == "cam1_processed"
        assert pushed_frame.sum() > 0

    async def test_process_frame_item_prewarms_processed_stream(self):
        class WarmupProcessor(BaseVideoProcessor):
            def __init__(self):
                super().__init__(
                    source_id="s1",
                    source_name="cam",
                    rtsp_url="rtsp://localhost:8554/cam1",
                    app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
                )
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def process_frame(self, frame, encoded, shape, roi_pixel_points):
                self.started.set()
                await self.release.wait()
                return AnalysisResult()

        proc = WarmupProcessor()
        pushed: list[tuple[np.ndarray, str]] = []
        proc._push_frame = lambda frame, path: pushed.append((frame.copy(), path))
        frame = np.zeros((64, 64, 3), dtype=np.uint8)

        task = asyncio.create_task(proc._process_frame_item(frame, b"jpeg"))
        await asyncio.wait_for(proc.started.wait(), timeout=1.0)

        assert len(pushed) == 1
        pushed_frame, path = pushed[0]
        assert path == "cam1_processed"
        assert pushed_frame.sum() > 0

        proc.release.set()
        await asyncio.wait_for(task, timeout=1.0)

    async def test_process_frame_item_prewarms_processed_stream(self):
        class WarmupProcessor(BaseVideoProcessor):
            def __init__(self):
                super().__init__(
                    source_id="s1",
                    source_name="cam",
                    rtsp_url="rtsp://localhost:8554/cam1",
                    app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
                )
                self.started = asyncio.Event()
                self.release = asyncio.Event()

            async def process_frame(self, frame, encoded, shape, roi_pixel_points):
                self.started.set()
                await self.release.wait()
                return AnalysisResult()

        proc = WarmupProcessor()
        pushed: list[tuple[np.ndarray, str]] = []
        proc._push_frame = lambda frame, path: pushed.append((frame.copy(), path))
        frame = np.zeros((64, 64, 3), dtype=np.uint8)

        task = asyncio.create_task(proc._process_frame_item(frame, b"jpeg"))
        await asyncio.wait_for(proc.started.wait(), timeout=1.0)

        assert len(pushed) == 1
        pushed_frame, path = pushed[0]
        assert path == "cam1_processed"
        assert pushed_frame.sum() > 0

        proc.release.set()
        await asyncio.wait_for(task, timeout=1.0)
