"""Tests for ProcessorManager and BaseVideoProcessor."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from backend.api.ws import WSManager
from backend.config import DEFAULT_APP_SETTINGS
from backend.db.database import create_source
from backend.models.schemas import AnalysisMessage, ROI, ROIPoint
from backend.models.schemas import VideoSourceCreate
from backend.processing.base import AnalysisResult, BaseVideoProcessor
from backend.processing.manager import ProcessorManager


# ── Concrete subclass for testing ─────────────────────────────────────────────

class DummyProcessor(BaseVideoProcessor):
    """Minimal concrete processor for tests (no real RTSP or gRPC)."""

    async def process_frame(self, frame, encoded, shape, roi_pixel_points):
        return AnalysisResult()


class TestAnalysisResult:
    def test_defaults(self):
        r = AnalysisResult()
        assert r.detections == []
        assert r.classifications == []
        assert r.ocr_texts == []
        assert r.actions == []
        assert r.messages == []
        assert r.annotated_frame is None
        assert r.extra == {}


class TestBaseVideoProcessor:
    def _make_processor(self) -> DummyProcessor:
        ws = WSManager()
        vengine = MagicMock()
        roi = ROI(
            id="r1",
            type="rectangle",
            points=[ROIPoint(x=0.1, y=0.2), ROIPoint(x=0.9, y=0.8)],
            tag="zone",
        )
        return DummyProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            rois=[roi],
            vengine_client=vengine,
            ws_manager=ws,
            app_settings=dict(DEFAULT_APP_SETTINGS),
        )

    def test_init(self):
        proc = self._make_processor()
        assert proc.source_id == "s1"
        assert proc.status == "stopped"
        assert proc.started_at is None

    def test_stream_key(self):
        proc = self._make_processor()
        assert proc._stream_key() == "cam1"

    def test_stream_key_trailing_slash(self):
        proc = self._make_processor()
        proc.rtsp_url = "rtsp://host:8554/stream/"
        assert proc._stream_key() == "stream"

    def test_stream_path_preserves_nested_route(self):
        proc = self._make_processor()
        proc.rtsp_url = "rtsp://host:8554/zone/stream/"
        assert proc._stream_path() == "zone/stream"

    async def test_do_detect_maps_and_filters_results(self):
        proc = self._make_processor()
        proc.vengine.detect = AsyncMock(
            return_value=[
                {"label": "truck", "confidence": 0.92},
                {"label": "person", "confidence": 0.33},
            ]
        )

        result = await proc._do_detect(
            shape=(100, 200, 3),
            model_name="demo",
            image_bytes=b"frame",
            on_item=lambda item: item if item["confidence"] >= 0.5 else None,
        )

        proc.vengine.detect.assert_awaited_once()
        assert result == {
            "detections": [
                {"label": "truck", "confidence": 0.92},
            ]
        }

    def test_normalize_rois(self):
        proc = self._make_processor()
        result = proc._normalize_rois_to_pixels(1920, 1080)
        assert len(result) == 1
        pts = result[0]
        assert pts[0] == {"x": int(0.1 * 1920), "y": int(0.2 * 1080)}
        assert pts[1] == {"x": int(0.9 * 1920), "y": int(0.8 * 1080)}

    def test_draw_on_frame_empty(self):
        proc = self._make_processor()
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        result = AnalysisResult()
        out = proc.draw_on_frame(frame, result)
        assert out.shape == frame.shape
        # Original frame should not be modified
        assert np.array_equal(frame, np.zeros((100, 200, 3), dtype=np.uint8))

    def test_draw_on_frame_detections(self):
        proc = self._make_processor()
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        result = AnalysisResult(
            detections=[
                {
                    "x_min": 10,
                    "y_min": 20,
                    "x_max": 50,
                    "y_max": 60,
                    "confidence": 0.95,
                    "label": "person",
                }
            ]
        )
        out = proc.draw_on_frame(frame, result)
        # Some pixels should now be non-zero due to drawing
        assert out.sum() > 0

    async def test_start_stop(self):
        proc = self._make_processor()
        # Patch _run_loop to avoid real RTSP connection
        proc._run_loop = AsyncMock()
        await proc.start()
        assert proc.status == "running"
        assert proc.started_at is not None

        await proc.stop()
        assert proc.status == "stopped"

    async def test_start_twice(self):
        proc = self._make_processor()
        proc._run_loop = AsyncMock()
        await proc.start()
        # Starting again should not raise
        await proc.start()
        await proc.stop()


class TestProcessorManager:
    def _make_manager(self) -> ProcessorManager:
        vengine = MagicMock()
        ws = WSManager()
        return ProcessorManager(vengine_client=vengine, ws_manager=ws, app_settings=dict(DEFAULT_APP_SETTINGS))

    async def test_status_empty(self):
        mgr = self._make_manager()
        assert mgr.get_all_status() == []

    async def test_stop_not_running(self):
        mgr = self._make_manager()
        result = await mgr.stop_processor("nonexistent")
        assert result["status"] == "not_running"

    async def test_start_nonexistent_source(self, init_db):
        mgr = self._make_manager()
        with pytest.raises(ValueError, match="Source not found"):
            await mgr.start_processor("nonexistent")

    async def test_start_processor_uses_configured_plugin(self, init_db):
        source = await create_source(
            VideoSourceCreate(name="cam-1", rtsp_url="rtsp://localhost:8554/cam1")
        )
        mgr = self._make_manager()
        mgr._app_settings["processor_plugin"] = "example"

        processor = MagicMock(status="stopped")
        processor.start = AsyncMock()

        with patch("backend.processing.manager.resolve_processor_class") as resolve:
            processor_cls = MagicMock(return_value=processor)
            resolve.return_value = processor_cls

            result = await mgr.start_processor(source.id)

        resolve.assert_called_once_with("example")
        processor_cls.assert_called_once()
        processor.start.assert_awaited_once()
        assert mgr._processors[source.id] is processor
        assert result["processor_plugin"] == "example"

    async def test_stop_all_empty(self):
        mgr = self._make_manager()
        await mgr.stop_all()  # Should not raise

    def test_truck_adapter_initializes_core_state(self):
        from backend.processing.truck import TruckMonitorProcessor

        processor = TruckMonitorProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            rois=[],
            vengine_client=MagicMock(),
            ws_manager=WSManager(),
            app_settings=dict(DEFAULT_APP_SETTINGS),
        )

        assert processor.tracker is not None
        assert processor.agent is None


class TestExampleProcessorBatchClassification:
    async def test_process_frame_batches_person_roi_classification(self):
        from backend.processing.example import ExampleProcessor

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
                "label": "dog",
                "confidence": 0.75,
                "class_id": 3,
            },
        ]
        vengine.ocr.return_value = []
        vengine.classify.return_value = [
            {"label": "adult", "confidence": 0.89, "class_id": 10, "image_id": 0},
        ]

        proc = ExampleProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            rois=[],
            vengine_client=vengine,
            ws_manager=WSManager(),
            app_settings=dict(DEFAULT_APP_SETTINGS),
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
            }
        ]
        assert result.classifications == [
            {
                "detection_label": "person",
                "classification_label": "adult",
                "stable_label": "adult",
                "raw_label": "adult",
                "confidence": 0.89,
                "bbox": [10, 20, 50, 80],
                "person_bbox": [10, 20, 50, 80],
            }
        ]


class TestBackendBaseProcessorPipeline:
    async def test_handle_result_broadcasts_messages_and_enqueues_display(self):
        proc = DummyProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            rois=[],
            vengine_client=MagicMock(),
            ws_manager=WSManager(),
            app_settings=dict(DEFAULT_APP_SETTINGS),
        )
        proc.ws_manager.broadcast = AsyncMock()
        queued: list[tuple[np.ndarray, AnalysisResult, str]] = []
        proc._enqueue_display = lambda frame, result, path: queued.append((frame, result, path))
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        result = AnalysisResult(
            detections=[{"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4, "label": "person"}],
            messages=[{"message": "hello"}],
        )

        await proc._handle_result(frame, result)

        proc.ws_manager.broadcast.assert_awaited_once()
        sent = proc.ws_manager.broadcast.await_args.args[0]
        assert isinstance(sent, AnalysisMessage)
        assert sent.message == "hello"
        assert sent.source_name == "cam"
        assert sent.source_id == "s1"
        assert queued
        assert queued[0][2] == "cam1_processed"

    async def test_handle_result_preserves_nested_processed_route(self):
        proc = DummyProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/zone/cam1",
            rois=[],
            vengine_client=MagicMock(),
            ws_manager=WSManager(),
            app_settings=dict(DEFAULT_APP_SETTINGS),
        )
        queued: list[tuple[np.ndarray, AnalysisResult, str]] = []
        proc._enqueue_display = lambda frame, result, path: queued.append((frame, result, path))
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        result = AnalysisResult(
            detections=[{"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4, "label": "person"}],
        )

        await proc._handle_result(frame, result)

        assert queued
        assert queued[0][2] == "zone/cam1_processed"
