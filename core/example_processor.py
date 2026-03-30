"""Example standalone processor using the core package.
使用 core 包的示例独立处理器。

This demonstrates how to develop and test a processor independently.
演示如何独立开发和测试处理器。

Usage::

    python -m core.example_processor --input rtsp://localhost:8554/cam1

The processor reads frames, runs a dummy "detection" pass, draws bounding
boxes, and pushes the annotated stream to MediaMTX.
处理器读取帧、运行模拟"检测"、绘制边界框，并将标注流推送到 MediaMTX。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import numpy as np
from loguru import logger

from core.base_processor import AnalysisResult, BaseVideoProcessor
from core.runner import run_processor


class EchoProcessor(BaseVideoProcessor):
    """Minimal example: echo each frame with a timestamp overlay.
    最小示例：在每帧上叠加时间戳并回显。

    Replace the body of ``process_frame`` with your real AI logic
    (gRPC calls to V-Engine, custom OpenCV processing, etc.).
    将 ``process_frame`` 的主体替换为实际 AI 逻辑
    （调用 V-Engine gRPC、自定义 OpenCV 处理等）。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._count = 0

    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process a single frame with a timestamp overlay.
        处理单帧并叠加时间戳。"""
        self._count += 1

        # --- Your custom AI logic goes here --- / --- 在此添加您的自定义 AI 逻辑 ---
        # Example: call gRPC detection service
        # if self.vengine:
        #     detections = await self.vengine.detect(...)
        # ---

        # For demonstration: add a simple text overlay / 演示用途：添加简单文字覆盖层
        import cv2

        annotated = frame.copy()
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        cv2.putText(
            annotated,
            f"Frame #{self._count}  {ts}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

        logger.info("Processed frame #{} ({}x{})", self._count, shape[1], shape[0])

        return AnalysisResult(
            annotated_frame=annotated,
            extra={"frame_count": self._count},
        )


def main() -> None:
    """CLI entry point for the EchoProcessor standalone runner.
    EchoProcessor 独立运行器的 CLI 入口点。"""
    parser = argparse.ArgumentParser(description="Run the EchoProcessor standalone")
    parser.add_argument(
        "--input", required=True, help="RTSP input URL (e.g. rtsp://localhost:8554/cam1)"
    )
    parser.add_argument(
        "--mediamtx", default="rtsp://localhost:8554", help="MediaMTX RTSP base address"
    )
    args = parser.parse_args()

    run_processor(
        EchoProcessor,
        rtsp_input=args.input,
        mediamtx_rtsp_addr=args.mediamtx,
    )


if __name__ == "__main__":
    main()
