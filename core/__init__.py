"""V-Sentinel Core — single source of truth for video processing logic.
V-Sentinel Core — 视频处理逻辑的唯一代码来源。

This package contains the shared ``BaseVideoProcessor``, ``AnalysisResult``,
``AsyncVEngineClient``, proto stubs, and data classes used by both the
standalone core runner and the full V-Sentinel backend.

The backend's ``backend.processing.base`` inherits from
``core.base_processor.BaseVideoProcessor`` and adds WebSocket broadcast /
agent aggregation integration.

The backend's ``backend.vengine.client`` inherits from
``core.vengine_client.AsyncVEngineClient`` and adds pydantic Settings
compatibility.

The backend's ``backend.proto`` re-exports from ``core.proto``.

This eliminates code duplication — core is the single source of truth.

本包包含共享的 ``BaseVideoProcessor``、``AnalysisResult``、
``AsyncVEngineClient``、proto 存根和数据类，
被独立运行器和完整 V-Sentinel 后台共同使用。

后台的 ``backend.processing.base`` 继承自本包并添加 WebSocket/代理集成。
后台的 ``backend.vengine.client`` 继承自本包并添加 pydantic Settings 兼容。
后台的 ``backend.proto`` 从 ``core.proto`` 重新导出。

从而消除代码重复 — core 是唯一的代码来源。

Typical usage::

    from core.base_processor import BaseVideoProcessor, AnalysisResult
    from core.vengine_client import AsyncVEngineClient
    from core.runner import run_processor

    class MyProcessor(BaseVideoProcessor):
        async def process_frame(self, frame, encoded, shape, roi_pixel_points):
            detections = await self.vengine.detect(
                shape=shape, model_name="yolo", image_bytes=encoded
            )
            ...
            return AnalysisResult(detections=detections)

    if __name__ == "__main__":
        run_processor(MyProcessor, rtsp_input="rtsp://localhost:8554/cam1")
"""
