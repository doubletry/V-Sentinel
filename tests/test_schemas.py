"""Tests for Pydantic schemas."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.models.schemas import (
    ROI,
    ROICreate,
    ROIPoint,
    AnalysisMessage,
    ProcessorStartRequest,
    ProcessorStatus,
    ProcessorStopRequest,
    VideoSource,
    VideoSourceCreate,
    VideoSourceUpdate,
)


class TestROIPoint:
    def test_valid(self):
        p = ROIPoint(x=0.5, y=0.3)
        assert p.x == 0.5
        assert p.y == 0.3

    def test_coercion(self):
        p = ROIPoint(x=1, y=0)
        assert isinstance(p.x, float)


class TestROICreate:
    def test_rectangle(self):
        roi = ROICreate(
            type="rectangle",
            points=[ROIPoint(x=0, y=0), ROIPoint(x=1, y=1)],
            tag="zone-A",
        )
        assert roi.type == "rectangle"
        assert roi.tag == "zone-A"
        assert len(roi.points) == 2

    def test_polygon(self):
        roi = ROICreate(
            type="polygon",
            points=[ROIPoint(x=0, y=0), ROIPoint(x=0.5, y=0), ROIPoint(x=0.5, y=0.5)],
        )
        assert roi.type == "polygon"
        assert roi.tag == ""

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            ROICreate(type="circle", points=[])

    def test_default_tag(self):
        roi = ROICreate(type="rectangle", points=[])
        assert roi.tag == ""


class TestROI:
    def test_extends_create(self):
        roi = ROI(
            id="abc",
            type="polygon",
            points=[ROIPoint(x=0.1, y=0.2)],
            tag="t",
        )
        assert roi.id == "abc"
        assert roi.type == "polygon"


class TestVideoSourceCreate:
    def test_valid(self):
        s = VideoSourceCreate(name="cam1", rtsp_url="rtsp://host/live")
        assert s.name == "cam1"
        assert s.rtsp_url == "rtsp://host/live"

    def test_missing_name(self):
        with pytest.raises(ValidationError):
            VideoSourceCreate(rtsp_url="rtsp://host/live")

    def test_missing_url(self):
        with pytest.raises(ValidationError):
            VideoSourceCreate(name="cam1")


class TestVideoSourceUpdate:
    def test_all_optional(self):
        u = VideoSourceUpdate()
        assert u.name is None
        assert u.rtsp_url is None
        assert u.rois is None

    def test_partial(self):
        u = VideoSourceUpdate(name="new name")
        assert u.name == "new name"
        assert u.rtsp_url is None


class TestVideoSource:
    def test_full(self):
        vs = VideoSource(
            id="1",
            name="Camera",
            rtsp_url="rtsp://x",
            rois=[],
            created_at="2024-01-01T00:00:00Z",
        )
        assert vs.id == "1"
        assert vs.rois == []


class TestProcessorModels:
    def test_start_request(self):
        r = ProcessorStartRequest(source_id="abc")
        assert r.source_id == "abc"

    def test_stop_request(self):
        r = ProcessorStopRequest(source_id="xyz")
        assert r.source_id == "xyz"

    def test_status(self):
        s = ProcessorStatus(
            source_id="1",
            source_name="cam",
            rtsp_url="rtsp://x",
            status="running",
        )
        assert s.started_at is None


class TestAnalysisMessage:
    def test_full(self):
        m = AnalysisMessage(
            timestamp="2024-01-01T00:00:00Z",
            source_name="cam",
            source_id="1",
            level="info",
            message="Hello",
        )
        assert m.image_url is None
        assert m.image_base64 is None

    def test_with_image(self):
        m = AnalysisMessage(
            timestamp="2024-01-01T00:00:00Z",
            source_name="cam",
            source_id="1",
            level="alert",
            message="Alert!",
            image_url="/message-images/2024-01-01/demo.jpg",
            image_base64="abc123==",
        )
        assert m.image_url == "/message-images/2024-01-01/demo.jpg"
        assert m.image_base64 == "abc123=="
