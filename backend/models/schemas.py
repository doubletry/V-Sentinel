from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ROIPoint(BaseModel):
    """A single normalized coordinate point for an ROI.
    ROI 的单个归一化坐标点。"""

    x: float  # normalized 0-1 / 归一化 0-1
    y: float  # normalized 0-1 / 归一化 0-1


class ROICreate(BaseModel):
    """Schema for creating a new Region of Interest.
    创建新感兴趣区域的模式。"""

    type: Literal["polygon", "rectangle"]
    points: list[ROIPoint]
    tag: str = ""


class ROI(ROICreate):
    """Persisted ROI with a unique identifier.
    带唯一标识符的已持久化 ROI。"""

    id: str


class VideoSourceCreate(BaseModel):
    """Schema for creating a new video source.
    创建新视频源的模式。"""

    name: str
    rtsp_url: str


class VideoSourceUpdate(BaseModel):
    """Schema for partially updating a video source.
    部分更新视频源的模式。"""

    name: str | None = None
    rtsp_url: str | None = None
    rois: list[ROICreate] | None = None


class VideoSource(BaseModel):
    """Full video source model with ROIs and metadata.
    包含 ROI 和元数据的完整视频源模型。"""

    id: str
    name: str
    rtsp_url: str
    rois: list[ROI] = []
    created_at: str


class ProcessorStartRequest(BaseModel):
    """Request body to start processing for a specific video source.
    启动指定视频源处理的请求体。"""

    source_id: str


class ProcessorStopRequest(BaseModel):
    """Request body to stop processing for a specific video source.
    停止指定视频源处理的请求体。"""

    source_id: str


class ProcessorStatus(BaseModel):
    """Status of a running or stopped processor.
    处理器的运行或停止状态。"""

    source_id: str
    source_name: str
    rtsp_url: str
    status: str  # "running", "stopped", "error" / 运行中、已停止、错误
    started_at: str | None = None


class AnalysisMessage(BaseModel):
    """Real-time analysis message broadcast via WebSocket.
    通过 WebSocket 广播的实时分析消息。"""

    timestamp: str
    source_name: str
    source_id: str
    level: str  # "info", "warning", "alert" / 信息、警告、告警
    message: str
    image_url: str | None = None
    image_base64: str | None = None


class ProcessorPluginInfo(BaseModel):
    """Processor plugin display metadata.
    处理器插件展示元数据。"""

    value: str
    label_zh: str
    label_en: str


class PaginatedMessagesResponse(BaseModel):
    """Paginated persisted analysis messages.
    持久化分析消息的分页响应。"""

    items: list[AnalysisMessage]
    page: int
    page_size: int
    total: int
    total_pages: int


class AppSettingsUpdate(BaseModel):
    """Partial update for app settings (all fields optional).
    部分更新应用设置（所有字段可选）。"""

    ui_language: str | None = None
    timezone: str | None = None
    site_title: str | None = None
    site_description: str | None = None
    favicon_url: str | None = None
    roi_tag_options: str | None = None

    vengine_host: str | None = None
    detection_port: str | None = None
    classification_port: str | None = None
    action_port: str | None = None
    ocr_port: str | None = None
    upload_port: str | None = None
    # Per-service enable/disable switches / 各服务启用/禁用开关
    detection_enabled: str | None = None
    classification_enabled: str | None = None
    action_enabled: str | None = None
    ocr_enabled: str | None = None
    upload_enabled: str | None = None

    processor_plugin: str | None = None

    mediamtx_rtsp_addr: str | None = None
    mediamtx_webrtc_addr: str | None = None
    mediamtx_username: str | None = None
    mediamtx_password: str | None = None
    email_from_address: str | None = None
    email_from_auth_code: str | None = None
    email_to_addresses: str | None = None
    email_cc_addresses: str | None = None
    email_port: str | None = None
    daily_summary_hour: str | None = None
    daily_summary_minute: str | None = None
    message_retention_days: str | None = None
    max_pull_workers: str | None = None
    max_push_workers: str | None = None
    max_cpu_workers: str | None = None


class EmailTestRequest(BaseModel):
    """Payload for testing email configuration without saving first.
    用于在不先保存的情况下测试邮件配置的载荷。"""

    vengine_host: str | None = None
    email_port: str | None = None
    email_from_address: str | None = None
    email_from_auth_code: str | None = None
    email_to_addresses: str | None = None
    email_cc_addresses: str | None = None
