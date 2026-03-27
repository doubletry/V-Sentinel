from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

from backend.models.schemas import AnalysisMessage, ROI
from backend.processing.base import AnalysisResult, BaseVideoProcessor

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager


class ExampleProcessor(BaseVideoProcessor):
    """Example processor that runs detection + OCR concurrently, then classifies crops.

    Pipeline:
    1. ``asyncio.gather(detect, ocr)`` — concurrent detection + OCR
    2. Serial classification on each detection crop
    3. Message assembly and WebSocket broadcast
    4. Frame annotation via cv2
    """

    DETECTION_MODEL = "yolov8n"
    CLASSIFICATION_MODEL = "resnet50"
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
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_name=source_name,
            rtsp_url=rtsp_url,
            rois=rois,
            vengine_client=vengine_client,
            ws_manager=ws_manager,
            app_settings=app_settings,
        )
        self._frame_count = 0

    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process one frame: concurrent detection + OCR, then serial classify."""
        self._frame_count += 1

        # Use first ROI for inference if available
        primary_roi = roi_pixel_points[0] if roi_pixel_points else None

        # 1. Run detection and OCR concurrently
        detect_coro = self.vengine.detect(
            image_bytes=encoded,
            shape=shape,
            model_name=self.DETECTION_MODEL,
            conf=0.5,
            roi_points=primary_roi,
        )
        ocr_coro = self.vengine.ocr(
            image_bytes=encoded,
            shape=shape,
            model_name=self.OCR_MODEL,
            conf=0.5,
            roi_points=primary_roi,
        )
        detections, ocr_texts = await asyncio.gather(detect_coro, ocr_coro)

        # 2. Classify each detected crop (serial to avoid overwhelming the service)
        classifications: list[dict] = []
        h, w = shape[:2]
        for det in detections:
            x1 = max(int(det["x_min"]), 0)
            y1 = max(int(det["y_min"]), 0)
            x2 = min(int(det["x_max"]), w)
            y2 = min(int(det["y_max"]), h)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = frame[y1:y2, x1:x2]
            import cv2
            ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                continue
            crop_bytes = buf.tobytes()
            crop_shape = (y2 - y1, x2 - x1, 3)
            cls_results = await self.vengine.classify(
                image_bytes=crop_bytes,
                shape=crop_shape,
                model_name=self.CLASSIFICATION_MODEL,
            )
            if cls_results:
                best = cls_results[0]
                classifications.append(
                    {
                        "detection_label": det["label"],
                        "classification_label": best["label"],
                        "confidence": best["confidence"],
                        "bbox": [x1, y1, x2, y2],
                    }
                )

        # 3. Annotate frame
        result = AnalysisResult(
            detections=detections,
            classifications=classifications,
            ocr_texts=ocr_texts,
        )
        result.annotated_frame = await asyncio.to_thread(
            self.draw_on_frame, frame, result
        )

        # 4. Assemble messages
        messages: list[AnalysisMessage] = []
        now = datetime.now(timezone.utc).isoformat()

        if detections:
            labels = ", ".join(d["label"] for d in detections[:5])
            thumbnail = self._encode_thumbnail(result.annotated_frame)
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
        """Encode a frame as a base64 JPEG thumbnail."""
        if frame is None:
            return None
        import cv2

        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / w
            frame = cv2.resize(
                frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA
            )
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode()
