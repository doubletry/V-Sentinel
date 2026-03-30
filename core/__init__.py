"""V-Sentinel Core — single source of truth for video processing logic.
V-Sentinel Core — 视频处理逻辑的唯一代码来源。

This package contains the shared ``BaseVideoProcessor``, ``AnalysisResult``,
and data classes used by both the standalone core runner and the full
V-Sentinel backend.  The backend's ``backend.processing.base`` inherits from
``core.base_processor.BaseVideoProcessor`` and adds WebSocket broadcast /
agent aggregation integration.  This eliminates code duplication.
本包包含共享的 ``BaseVideoProcessor``、``AnalysisResult`` 等类，
被独立运行器和完整 V-Sentinel 后台共同使用。后台的
``backend.processing.base`` 继承自本包并添加 WebSocket/代理集成，
从而消除代码重复。

Typical usage::

    from core.base_processor import BaseVideoProcessor, AnalysisResult
    from core.runner import run_processor

    class MyProcessor(BaseVideoProcessor):
        async def process_frame(self, frame, encoded, shape, roi_pixel_points):
            ...
            return AnalysisResult(...)

    if __name__ == "__main__":
        run_processor(MyProcessor, rtsp_input="rtsp://localhost:8554/cam1")
"""
