"""Tests for the core minimal package."""
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
    """Concrete processor for testing the core package."""

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
