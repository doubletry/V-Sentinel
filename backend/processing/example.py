from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import cv2
import numpy as np
from loguru import logger
try:
    from turbojpeg import TurboJPEG, TJPF_RGB
    _jpeg = TurboJPEG()
except (ImportError, RuntimeError) as _exc:
    _jpeg = None
    TJPF_RGB = None  # type: ignore[assignment]
    logger.warning("TurboJPEG unavailable in backend example processor: {}", _exc)

from backend.models.schemas import AnalysisMessage, ROI
from backend.processing.base import AnalysisResult, BaseVideoProcessor

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager
    from backend.processing.agent import AnalysisAgent

class ExampleProcessor(BaseVideoProcessor):
    """Example processor that runs detection + OCR concurrently, then batch classifies person ROIs.
    示例处理器，并发执行检测 + OCR，然后对 person 区域进行批量分类。

    Pipeline:
    1. ``asyncio.gather(detect, ocr)`` — concurrent detection + OCR
    2. Batch classification on detected person ROIs
    3. Message assembly and WebSocket broadcast
    4. Frame annotation via cv2

    流水线：
    1. ``asyncio.gather(detect, ocr)`` — 并发检测 + OCR
    2. 对检测到的 person ROI 进行批量分类
    3. 消息组装与 WebSocket 广播
    4. 通过 cv2 进行帧标注
    """

    DETECTION_MODEL = "huotai"
    CLASSIFICATION_MODEL = "huotai"
    OCR_MODEL = "paddleocr"

    def __init__(
        self,
        source_id: str,
        source_name: str,
        rtsp_url: str,
        rois: list[ROI],
        vengine_client: "AsyncVEngineClient",
        ws_manager: "WSManager",
        app_settings: dict[str, str],
        agent: "AnalysisAgent | None" = None,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_name=source_name,
            rtsp_url=rtsp_url,
            rois=rois,
            vengine_client=vengine_client,
            ws_manager=ws_manager,
            app_settings=app_settings,
            agent=agent,
        )
        self._frame_count = 0

    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process one frame: upload → concurrent detection + OCR by key → batch classify.
        处理单帧：上传 → 按 key 并发检测 + OCR → 批量分类。"""
        self._frame_count += 1

        # Use first ROI for inference if available / 如果有 ROI 则使用第一个进行推理
        primary_roi = roi_pixel_points[0] if roi_pixel_points else None

        # 0. Upload frame to cache to avoid duplicate transmission
        # 0. 上传帧到缓存以避免重复传输
        image_key = await self.vengine.upload_and_get_key(encoded)

        # Build kwargs: prefer cache key, fall back to raw bytes
        # 构建参数：优先使用缓存 key，回退到原始字节
        img_kwargs: dict = {}
        if image_key:
            img_kwargs["image_key"] = image_key
        else:
            img_kwargs["image_bytes"] = encoded

        # 1. Run detection and OCR concurrently (both use the same key)
        # 1. 并发运行检测和 OCR（两者使用同一 key）
        detect_coro = self.vengine.detect(
            shape=shape,
            model_name=self.DETECTION_MODEL,
            conf=0.5,
            roi_points=primary_roi,
            **img_kwargs,
        )
        ocr_coro = self.vengine.ocr(
            shape=shape,
            model_name=self.OCR_MODEL,
            conf=0.5,
            roi_points=primary_roi,
            **img_kwargs,
        )
        detections, ocr_texts = await asyncio.gather(detect_coro, ocr_coro)

        # 2. Batch classify detected person ROIs in one request
        # 2. 在一次请求中批量分类检测到的 person ROI
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

        # 3. Assemble analysis result / 3. 组装分析结果
        result = AnalysisResult(
            detections=detections,
            classifications=classifications,
            ocr_texts=ocr_texts,
        )

        # 4. Assemble messages / 4. 组装消息
        messages: list[AnalysisMessage] = []
        now = datetime.now(timezone.utc).isoformat()

        if detections:
            labels = ", ".join(d["label"] for d in detections[:5])
            thumbnail = self._encode_thumbnail(frame)
            messages.append(
                AnalysisMessage(
                    timestamp=now,
                    source_name=self.source_name,
                    source_id=self.source_id,
                    level="info",
                    message=f"Detected {len(detections)} object(s): {labels}",
                    image_base64=thumbnail,
                )
            )

        if ocr_texts:
            texts = "; ".join(t["text"] for t in ocr_texts[:3])
            messages.append(
                AnalysisMessage(
                    timestamp=now,
                    source_name=self.source_name,
                    source_id=self.source_id,
                    level="info",
                    message=f"OCR: {texts}",
                )
            )

        result.messages = messages
        return result

    def _encode_thumbnail(
        self, frame: np.ndarray | None, max_width: int = 320
    ) -> str | None:
        """Encode a frame as a base64 JPEG thumbnail using TurboJPEG (RGB).
        使用 TurboJPEG 将帧编码为 base64 JPEG 缩略图（RGB 通道顺序）。"""
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
