"""V-Sentinel Core — minimal standalone package for Processor development.

This package provides the ``BaseVideoProcessor`` abstraction and a lightweight
runner so that custom processors can be developed and tested independently
of the full V-Sentinel backend.

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
