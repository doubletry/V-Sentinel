"""Example processor using the core package with real V-Engine gRPC calls.
使用 core 包的示例处理器，包含真实的 V-Engine gRPC 调用。

This processor is designed to be **directly portable** to the backend:
copy this file into ``backend/processing/`` and it will work as-is
(the only additional integration needed is the backend-specific
``WSManager`` and ``AnalysisAgent``).
此处理器设计为**可直接移植**到后台：将此文件复制到
``backend/processing/`` 即可直接使用（唯一额外需要的集成是
后台特有的 ``WSManager`` 和 ``AnalysisAgent``）。

Usage::

    python -m core.example_processor --input rtsp://localhost:8554/cam1

Pipeline:
1. Upload frame → get cache key
2. Concurrent detection + OCR (using cache key)
3. Batch classification on detected person ROIs
4. Frame annotation via cv2
5. Push annotated frame to MediaMTX

流水线：
1. 上传帧 → 获取缓存键
2. 并发检测 + OCR（使用缓存键）
3. 对检测到的 person ROI 进行批量分类
4. 通过 cv2 进行帧标注
5. 将标注帧推送到 MediaMTX
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone

import cv2
import numpy as np
from loguru import logger
try:
    from turbojpeg import TurboJPEG, TJPF_RGB
    _jpeg = TurboJPEG()
except (ImportError, RuntimeError) as _exc:
    _jpeg = None
    TJPF_RGB = None  # type: ignore[assignment]
    logger.warning("TurboJPEG unavailable in example processor: {}", _exc)

from core.base_processor import AnalysisResult, BaseVideoProcessor
from core.runner import run_processor

class ExampleProcessor(BaseVideoProcessor):
    """Example processor: upload → concurrent detection + OCR → batch classify.
    示例处理器：上传 → 并发检测 + OCR → 批量分类。

    This is functionally equivalent to ``backend.processing.example.ExampleProcessor``
    but uses only ``core`` imports, proving that core is self-sufficient.
    此处理器功能上等同于 ``backend.processing.example.ExampleProcessor``，
    但仅使用 ``core`` 导入，证明 core 是自包含的。
    """

    DETECTION_MODEL = "huotai"
    CLASSIFICATION_MODEL = "huotai"
    OCR_MODEL = "paddleocr"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._frame_count = 0

    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process one frame: upload → concurrent detection + OCR → batch classify.
        处理单帧：上传 → 并发检测 + OCR → 批量分类。"""
        self._frame_count += 1

        # Use first ROI for inference if available / 如果有 ROI 则使用第一个进行推理
        primary_roi = roi_pixel_points[0] if roi_pixel_points else None

        # Guard: if no vengine client, fall back to simple echo
        # 保护：若无 vengine 客户端，回退到简单回显
        if self.vengine is None:
            annotated = frame.copy()
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            cv2.putText(
                annotated, f"Frame #{self._frame_count}  {ts}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 255, 0), 2, cv2.LINE_AA,
            )
            return AnalysisResult(annotated_frame=annotated)

        # 0. Upload frame to cache / 上传帧到缓存
        image_key = await self.vengine.upload_and_get_key(encoded)

        # Build kwargs: prefer cache key, fall back to raw bytes
        # 构建参数：优先使用缓存 key，回退到原始字节
        img_kwargs: dict = {}
        if image_key:
            img_kwargs["image_key"] = image_key
        else:
            img_kwargs["image_bytes"] = encoded

        # 1. Concurrent detection + OCR / 并发检测 + OCR
        detect_coro = self.vengine.detect(
            shape=shape,
            model_name=self.DETECTION_MODEL,
            conf=0.5,
            model_roi=primary_roi,
            **img_kwargs,
        )
        ocr_coro = self.vengine.ocr(
            shape=shape,
            model_name=self.OCR_MODEL,
            conf=0.5,
            image_roi=primary_roi,
            **img_kwargs,
        )
        detections, ocr_texts = await asyncio.gather(detect_coro, ocr_coro)

        # 2. Batch classification on detected person ROIs / 对检测到的 person ROI 批量分类
        classifications: list[dict] = []
        h, w = shape[:2]
        person_detections: list[dict] = []
        classification_images: list[dict] = []
        for det in detections:
            if str(det.get("label", "")).lower() != "person":
                continue
            x1 = max(int(det["x_min"]), 0)
            y1 = max(int(det["y_min"]), 0)
            x2 = min(int(det["x_max"]), w)
            y2 = min(int(det["y_max"]), h)
            if x2 <= x1 or y2 <= y1:
                continue
            person_detections.append(det)
            classification_images.append(
                {
                    "shape": shape,
                    "roi": [
                        {"x": x1, "y": y1},
                        {"x": x2, "y": y1},
                        {"x": x2, "y": y2},
                        {"x": x1, "y": y2},
                    ],
                    "key": image_key,
                }
                if image_key
                else {
                    "shape": shape,
                    "roi": [
                        {"x": x1, "y": y1},
                        {"x": x2, "y": y1},
                        {"x": x2, "y": y2},
                        {"x": x1, "y": y2},
                    ],
                    "image_bytes": encoded,
                }
            )

        if classification_images:
            cls_results = await self.vengine.classify(
                shape=None,
                model_name=self.CLASSIFICATION_MODEL,
                images=classification_images,
            )
            for best in cls_results:
                image_id = best.get("image_id")
                if not isinstance(image_id, int) or not (0 <= image_id < len(person_detections)):
                    continue
                det = person_detections[image_id]
                x1 = max(int(det["x_min"]), 0)
                y1 = max(int(det["y_min"]), 0)
                x2 = min(int(det["x_max"]), w)
                y2 = min(int(det["y_max"]), h)
                classifications.append(
                    {
                        "detection_label": det["label"],
                        "classification_label": best["label"],
                        "confidence": best["confidence"],
                        "bbox": [x1, y1, x2, y2],
                    }
                )

        # 3. Assemble analysis result / 组装分析结果
        result = AnalysisResult(
            detections=detections,
            classifications=classifications,
            ocr_texts=ocr_texts,
        )

        # 4. Assemble messages / 组装消息
        messages: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        if detections:
            labels = ", ".join(d["label"] for d in detections[:5])
            thumbnail = self._encode_thumbnail(frame)
            messages.append(
                {
                    "timestamp": now,
                    "source_name": self.source_name,
                    "source_id": self.source_id,
                    "level": "info",
                    "message": f"Detected {len(detections)} object(s): {labels}",
                    "image_base64": thumbnail,
                }
            )

        if ocr_texts:
            texts = "; ".join(t["text"] for t in ocr_texts[:3])
            messages.append(
                {
                    "timestamp": now,
                    "source_name": self.source_name,
                    "source_id": self.source_id,
                    "level": "info",
                    "message": f"OCR: {texts}",
                }
            )

        result.messages = messages
        return result

    def _encode_thumbnail(
        self, frame: np.ndarray | None, max_width: int = 320
    ) -> str | None:
        """Encode a frame as a base64 JPEG thumbnail (RGB).
        将帧编码为 base64 JPEG 缩略图（RGB 通道顺序）。"""
        if frame is None:
            return None
        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / w
            frame = cv2.resize(
                frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA
            )
        if _jpeg is not None:
            encoded = _jpeg.encode(frame, quality=60, pixel_format=TJPF_RGB)
        else:
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if not ok:
                return None
            encoded = buf.tobytes()
        return base64.b64encode(encoded).decode()


def main() -> None:
    """CLI entry point for the ExampleProcessor standalone runner.
    ExampleProcessor 独立运行器的 CLI 入口点。"""
    parser = argparse.ArgumentParser(description="Run the ExampleProcessor standalone")
    parser.add_argument(
        "--input", required=True, help="RTSP input URL (e.g. rtsp://localhost:8554/cam1)"
    )
    parser.add_argument(
        "--mediamtx", default="rtsp://localhost:8554", help="MediaMTX RTSP base address"
    )
    parser.add_argument(
        "--vengine-host", default="localhost", help="V-Engine gRPC host"
    )
    parser.add_argument(
        "--no-vengine", action="store_true", help="Disable auto V-Engine client creation"
    )
    args = parser.parse_args()

    run_processor(
        ExampleProcessor,
        rtsp_input=args.input,
        mediamtx_rtsp_addr=args.mediamtx,
        vengine_host=args.vengine_host,
        auto_connect_vengine=not args.no_vengine,
    )


if __name__ == "__main__":
    main()
