from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ROIPoint(BaseModel):
    x: float  # normalized 0-1
    y: float  # normalized 0-1


class ROICreate(BaseModel):
    type: Literal["polygon", "rectangle"]
    points: list[ROIPoint]
    tag: str = ""


class ROI(ROICreate):
    id: str


class VideoSourceCreate(BaseModel):
    name: str
    rtsp_url: str


class VideoSourceUpdate(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None
    rois: list[ROICreate] | None = None


class VideoSource(BaseModel):
    id: str
    name: str
    rtsp_url: str
    rois: list[ROI] = []
    created_at: str


class ProcessorStartRequest(BaseModel):
    source_id: str


class ProcessorStopRequest(BaseModel):
    source_id: str


class ProcessorStatus(BaseModel):
    source_id: str
    source_name: str
    rtsp_url: str
    status: str  # "running", "stopped", "error"
    started_at: str | None = None


class AnalysisMessage(BaseModel):
    timestamp: str
    source_name: str
    source_id: str
    level: str  # "info", "warning", "alert"
    message: str
    image_base64: str | None = None


class AppSettingsUpdate(BaseModel):
    """Partial update for app settings (all fields optional)."""

    vengine_host: str | None = None
    detection_port: str | None = None
    classification_port: str | None = None
    action_port: str | None = None
    ocr_port: str | None = None
    upload_port: str | None = None
    mediamtx_rtsp_addr: str | None = None
    mediamtx_webrtc_addr: str | None = None
    max_pull_workers: str | None = None
    max_push_workers: str | None = None
    max_cpu_workers: str | None = None
