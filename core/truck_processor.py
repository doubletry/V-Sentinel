"""Truck-monitoring processor: detect → OCR truck ROI → classify
person + truck composite ROI.

卡车监控处理器：检测 → 卡车 ROI OCR → 人+卡车复合 ROI 分类。

Business logic
--------------
1. Every frame goes through **detection** first (trucks, persons, etc.).
2. The ``TruckTracker`` matches detections to existing tracks and decides:
   - Which trucks need **OCR** this frame (license-plate recognition).
   - Which person + truck pairs need **action classification**.
3. OCR and classification requests are issued **concurrently** (cache-key based).
4. Results are fed back into the tracker for temporal stability filtering.
5. When a truck **leaves** the scene, a ``VehicleVisit`` record is produced
   containing the plate, confirmed actions, and any missing actions.

Usage::

    python -m core.truck_processor --input rtsp://localhost:8554/cam1

用法::

    python -m core.truck_processor --input rtsp://localhost:8554/cam1
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

from core.base_processor import AnalysisResult, BaseVideoProcessor
from core.runner import run_processor
from core.truck_tracker import (
    FrameAnalysis,
    TrackingDecision,
    TruckTracker,
    VehicleVisit,
)


class TruckMonitorProcessor(BaseVideoProcessor):
    """Processor that monitors truck arrivals, license plates and worker
    actions using cross-frame state tracking.

    使用跨帧状态跟踪监控卡车到达、车牌和工人动作的处理器。
    """

    DETECTION_MODEL = "huotai"
    CLASSIFICATION_MODEL = "huotai"
    OCR_MODEL = "paddleocr"

    # Configurable via app_settings or constructor kwargs
    OCR_INTERVAL: int = 10  # every N frames
    TRUCK_LABELS: frozenset[str] = frozenset({"truck"})

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._frame_count = 0

        # Build ROI for tracker from first ROI polygon (pixel coords resolved
        # per-frame, so tracker uses normalized or pixel ROI passed at init).
        # We will pass the pixel-coordinate ROI on each frame instead.
        self.tracker = TruckTracker(
            ocr_interval=int(
                self.app_settings.get("ocr_interval", str(self.OCR_INTERVAL))
            ),
        )

    # ── Main frame handler ────────────────────────────────────────────────

    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process one frame through the truck-monitoring pipeline.
        通过卡车监控流水线处理一帧。"""
        self._frame_count += 1

        # Set tracker ROI from first polygon (if any)
        if roi_pixel_points and self.tracker.roi is None:
            self.tracker.roi = [
                [p["x"], p["y"]] for p in roi_pixel_points[0]
            ]

        # Guard: if no vengine, echo-only
        if self.vengine is None:
            annotated = frame.copy()
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            cv2.putText(
                annotated, f"Frame #{self._frame_count}  {ts}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 255, 0), 2, cv2.LINE_AA,
            )
            return AnalysisResult(annotated_frame=annotated)

        h, w = shape[:2]
        primary_roi = roi_pixel_points[0] if roi_pixel_points else None

        # 0. Upload frame to cache
        image_key = await self.vengine.upload_and_get_key(encoded)
        img_kwargs: dict = {}
        if image_key:
            img_kwargs["image_key"] = image_key
        else:
            img_kwargs["image_bytes"] = encoded

        # 1. Detection
        detections = await self.vengine.detect(
            shape=shape,
            model_name=self.DETECTION_MODEL,
            conf=0.5,
            roi_points=primary_roi,
            **img_kwargs,
        )

        # 2. Classify detections into trucks / persons / others
        analysis = FrameAnalysis()
        for det in detections:
            label = str(det.get("label", "")).lower()
            if label in self.TRUCK_LABELS:
                analysis.trucks.append(det)
            elif label == "person":
                analysis.persons.append(det)
            else:
                analysis.others.append(det)

        # 3. Tracker update
        decision: TrackingDecision = self.tracker.update(analysis)

        # 4. Concurrent OCR + classification
        ocr_texts: list[dict] = []
        classifications: list[dict] = []
        coros: list = []

        # 4a. OCR for trucks that need it
        ocr_track_ids = decision.ocr_truck_ids
        ocr_rois: list[dict] = []
        for tid in ocr_track_ids:
            track = self.tracker.get_track(tid)
            if track is None:
                continue
            x1, y1, x2, y2 = track.bbox
            ocr_rois.append({
                "shape": shape,
                "roi": [
                    {"x": max(x1, 0), "y": max(y1, 0)},
                    {"x": min(x2, w), "y": max(y1, 0)},
                    {"x": min(x2, w), "y": min(y2, h)},
                    {"x": max(x1, 0), "y": min(y2, h)},
                ],
                **({"key": image_key} if image_key else {"image_bytes": encoded}),
            })

        if ocr_rois:
            coros.append(self._do_ocr(ocr_rois, ocr_track_ids))

        # 4b. Classification for combined person+truck ROIs
        cls_items = decision.classify_rois
        cls_rois: list[dict] = []
        cls_track_ids: list[int] = []
        for item in cls_items:
            x1, y1, x2, y2 = item["roi"]
            cls_rois.append({
                "shape": shape,
                "roi": [
                    {"x": max(x1, 0), "y": max(y1, 0)},
                    {"x": min(x2, w), "y": max(y1, 0)},
                    {"x": min(x2, w), "y": min(y2, h)},
                    {"x": max(x1, 0), "y": min(y2, h)},
                ],
                **({"key": image_key} if image_key else {"image_bytes": encoded}),
            })
            cls_track_ids.append(item["track_id"])

        if cls_rois:
            coros.append(self._do_classify(cls_rois, cls_track_ids))

        # Gather OCR + classify concurrently
        results = await asyncio.gather(*coros, return_exceptions=True)
        for r in results:
            if isinstance(r, dict):
                if "ocr_texts" in r:
                    ocr_texts.extend(r["ocr_texts"])
                if "classifications" in r:
                    classifications.extend(r["classifications"])
            elif isinstance(r, BaseException):
                logger.error("Truck processing sub-task error: {}", r)

        # 5. Assemble messages
        messages: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        for visit in decision.visits:
            missing = ", ".join(sorted(visit.missing_actions)) or "none"
            messages.append({
                "timestamp": now,
                "source_name": self.source_name,
                "source_id": self.source_id,
                "level": "warning" if visit.missing_actions else "info",
                "message": (
                    f"Vehicle left: plate={visit.plate or 'unknown'}, "
                    f"missing actions: {missing}"
                ),
            })

        if detections:
            labels = ", ".join(d["label"] for d in detections[:5])
            thumbnail = self._encode_thumbnail(frame)
            messages.append({
                "timestamp": now,
                "source_name": self.source_name,
                "source_id": self.source_id,
                "level": "info",
                "message": f"Detected {len(detections)} object(s): {labels}",
                "image_base64": thumbnail,
            })

        return AnalysisResult(
            detections=detections,
            classifications=classifications,
            ocr_texts=ocr_texts,
            messages=messages,
        )

    # ── Sub-tasks ─────────────────────────────────────────────────────────

    async def _do_ocr(
        self,
        ocr_rois: list[dict],
        track_ids: list[int],
    ) -> dict:
        """Run batched OCR and feed results back to tracker.
        运行批量 OCR 并将结果反馈给跟踪器。"""
        raw = await self.vengine.ocr(
            shape=None,
            model_name=self.OCR_MODEL,
            conf=0.3,
            images=ocr_rois,
        )
        ocr_texts: list[dict] = []
        for item in raw:
            image_id = item.get("image_id", 0)
            if isinstance(image_id, int) and 0 <= image_id < len(track_ids):
                tid = track_ids[image_id]
                self.tracker.feed_ocr(
                    tid, item.get("text", ""), item.get("confidence", 0.0)
                )
            ocr_texts.append(item)
        return {"ocr_texts": ocr_texts}

    async def _do_classify(
        self,
        cls_rois: list[dict],
        track_ids: list[int],
    ) -> dict:
        """Run batched classification and feed results back to tracker.
        运行批量分类并将结果反馈给跟踪器。"""
        raw = await self.vengine.classify(
            shape=None,
            model_name=self.CLASSIFICATION_MODEL,
            images=cls_rois,
        )
        classifications: list[dict] = []
        for item in raw:
            image_id = item.get("image_id", 0)
            if isinstance(image_id, int) and 0 <= image_id < len(track_ids):
                tid = track_ids[image_id]
                raw_label = item.get("label", "other")
                stable_label = self.tracker.feed_action(tid, raw_label)
                track = self.tracker.get_track(tid)
                classifications.append({
                    "track_id": tid,
                    "raw_label": raw_label,
                    "stable_label": stable_label,
                    "confidence": item.get("confidence", 0.0),
                    "plate": track.best_plate if track else "",
                })
        return {"classifications": classifications}

    # ── Thumbnail ─────────────────────────────────────────────────────────

    def _encode_thumbnail(
        self, frame: np.ndarray | None, max_width: int = 320
    ) -> str | None:
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


# ── CLI entry point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the TruckMonitorProcessor standalone"
    )
    parser.add_argument(
        "--input", required=True,
        help="RTSP input URL (e.g. rtsp://localhost:8554/cam1)",
    )
    parser.add_argument(
        "--mediamtx", default="rtsp://localhost:8554",
        help="MediaMTX RTSP base address",
    )
    parser.add_argument(
        "--vengine-host", default="localhost",
        help="V-Engine gRPC host",
    )
    parser.add_argument(
        "--no-vengine", action="store_true",
        help="Disable auto V-Engine client creation",
    )
    args = parser.parse_args()

    run_processor(
        TruckMonitorProcessor,
        rtsp_input=args.input,
        mediamtx_rtsp_addr=args.mediamtx,
        vengine_host=args.vengine_host,
        auto_connect_vengine=not args.no_vengine,
    )


if __name__ == "__main__":
    main()
