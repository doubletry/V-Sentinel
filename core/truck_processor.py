"""Truck-monitoring processor: detect → OCR truck ROI → classify
person + truck composite ROI.

卡车监控处理器：检测 → 卡车 ROI OCR → 人+卡车复合 ROI 分类。

Business logic / 业务逻辑
--------------
1. Every frame goes through **detection** with the user-defined ROI passed as
   ``model_roi`` (server filters results to keep only boxes inside the ROI —
   post-processing).
   每帧通过**检测**，用户定义的 ROI 作为 ``model_roi`` 传入（服务端过滤结果
   仅保留 ROI 内的检测框——后处理）。

2. The ``TruckTracker`` single-truck state machine decides:
   ``TruckTracker`` 单卡车状态机决定：
   - Whether the truck is confirmed (not a passing vehicle).
     卡车是否已确认（非路过车辆）。
   - Which trucks need **OCR** this frame (license-plate recognition).
     哪些卡车本帧需要 **OCR**（车牌识别）。
   - Which person + truck pairs need **action classification**.
     哪些人+卡车对需要**动作分类**。

3. OCR and classification requests are issued **concurrently**.
   OCR 和分类请求**并发**发出。

4. Classification uses ``image_roi`` — the combined person + truck bounding box
   is sent as a crop region so the server crops the input before classification
   (pre-processing).
   分类使用 ``image_roi``——合并的人+卡车检测框作为裁剪区域发送，
   服务端在分类前裁剪输入（前处理）。

5. Results are fed back into the tracker for temporal stability filtering.
   结果反馈给跟踪器进行时间稳定性滤波。

6. When a truck **leaves** the scene, a ``VehicleVisit`` record is produced
   containing the plate, confirmed actions, and any missing actions.
   当卡车**离开**场景时，产生 ``VehicleVisit`` 记录，包含车牌、已确认动作
   和缺少的动作。

Usage / 用法::

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

    The pipeline per frame is:
    每帧流水线：
    1. Upload frame → get cache key.
       上传帧 → 获取缓存 key。
    2. Detection with ``model_roi`` (server filters results by ROI).
       使用 ``model_roi`` 进行检测（服务端按 ROI 过滤结果）。
    3. Tracker update → decisions.
       跟踪器更新 → 决策。
    4. Concurrent OCR + classification (classification uses ``image_roi``).
       并发 OCR + 分类（分类使用 ``image_roi``）。
    5. Feed results back to tracker.
       将结果反馈给跟踪器。
    6. Generate messages for departures.
       为离开事件生成消息。
    """

    DETECTION_MODEL = "huotai"
    CLASSIFICATION_MODEL = "huotai"
    OCR_MODEL = "paddleocr"

    # Configurable via app_settings or constructor kwargs
    # 可通过 app_settings 或构造函数参数配置
    OCR_INTERVAL: int = 10  # every N frames / 每 N 帧
    TRUCK_LABELS: frozenset[str] = frozenset({"truck"})

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._frame_count = 0

        # Tracker is created with settings from app_settings if available.
        # 如果可用，使用 app_settings 中的设置创建跟踪器。
        self.tracker = TruckTracker(
            ocr_interval=int(
                self.app_settings.get("ocr_interval", str(self.OCR_INTERVAL))
            ),
        )

    # ── Main frame handler / 主帧处理器 ──────────────────────────────────

    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process one frame through the truck-monitoring pipeline.
        通过卡车监控流水线处理一帧。

        Parameters
        ----------
        frame : np.ndarray
            Raw RGB frame (H, W, 3). 原始 RGB 帧。
        encoded : bytes
            JPEG-encoded bytes of *frame*. *frame* 的 JPEG 编码字节。
        shape : tuple
            (H, W, C) shape of *frame*. *frame* 的 (H, W, C) 形状。
        roi_pixel_points : list[list[dict]]
            Pixel-coordinate ROI polygons from ``_normalize_rois_to_pixels``.
            来自 ``_normalize_rois_to_pixels`` 的像素坐标 ROI 多边形。
        """
        self._frame_count += 1

        # Set tracker ROI from first polygon (if any, once).
        # 从第一个多边形设置跟踪器 ROI（如果有，仅一次）。
        if roi_pixel_points and self.tracker.roi is None:
            self.tracker.roi = [
                [p["x"], p["y"]] for p in roi_pixel_points[0]
            ]

        # Guard: if no vengine, echo-only mode (draw frame number).
        # 保护：如无 vengine，仅回显模式（绘制帧号）。
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
        # The user-defined ROI is used as model_roi for detection: the server
        # filters detection results to keep only boxes inside the ROI
        # (post-processing).
        # 用户定义的 ROI 用作检测的 model_roi：服务端过滤检测结果仅保留 ROI 内
        # 的检测框（后处理）。
        primary_roi = roi_pixel_points[0] if roi_pixel_points else None

        # 0. Upload frame to cache to avoid duplicate transmission.
        # 0. 上传帧到缓存以避免重复传输。
        image_key = await self.vengine.upload_and_get_key(encoded)
        img_kwargs: dict = {}
        if image_key:
            img_kwargs["image_key"] = image_key
        else:
            img_kwargs["image_bytes"] = encoded

        # 1. Detection — ROI is passed as model_roi (post-processing filter).
        #    Returned detections are already filtered to those inside the ROI.
        # 1. 检测——ROI 作为 model_roi 传递（后处理过滤）。
        #    返回的检测结果已被过滤为 ROI 内的检测框。
        detections = await self.vengine.detect(
            shape=shape,
            model_name=self.DETECTION_MODEL,
            conf=0.5,
            roi_points=primary_roi,
            **img_kwargs,
        )

        # 2. Classify detections into trucks / persons / others.
        # 2. 将检测结果分为卡车/行人/其他。
        analysis = FrameAnalysis()
        for det in detections:
            label = str(det.get("label", "")).lower()
            if label in self.TRUCK_LABELS:
                analysis.trucks.append(det)
            elif label == "person":
                analysis.persons.append(det)
            else:
                analysis.others.append(det)

        # 3. Tracker update — the tracker's internal ROI filter is already
        #    set, but since detection already uses model_roi, all returned
        #    trucks are within the ROI.
        # 3. 跟踪器更新——跟踪器的内部 ROI 过滤已设置，但由于检测已使用
        #    model_roi，所有返回的卡车都在 ROI 内。
        decision: TrackingDecision = self.tracker.update(analysis)

        # 4. Concurrent OCR + classification.
        # 4. 并发 OCR + 分类。
        ocr_texts: list[dict] = []
        classifications: list[dict] = []
        coros: list = []

        # 4a. OCR for the truck (if needed this frame).
        #     OCR uses image_roi — the truck bounding box is the crop region.
        # 4a. 卡车的 OCR（如果本帧需要）。
        #     OCR 使用 image_roi——卡车检测框作为裁剪区域。
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

        # 4b. Classification for combined person + truck ROIs.
        #     Classification uses image_roi — the merged bounding box is
        #     sent as a crop region so the server crops before classifying
        #     (pre-processing).
        # 4b. 合并的人+卡车 ROI 的分类。
        #     分类使用 image_roi——合并的检测框作为裁剪区域发送，
        #     服务端在分类前裁剪（前处理）。
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

        # Gather OCR + classify concurrently for real-time performance.
        # 并发收集 OCR + 分类以保证实时性能。
        results = await asyncio.gather(*coros, return_exceptions=True)
        for r in results:
            if isinstance(r, dict):
                if "ocr_texts" in r:
                    ocr_texts.extend(r["ocr_texts"])
                if "classifications" in r:
                    classifications.extend(r["classifications"])
            elif isinstance(r, BaseException):
                logger.error("Truck processing sub-task error: {}", r)

        # 5. Assemble messages — particularly for vehicle departures.
        # 5. 组装消息——特别是车辆离开事件。
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

    # ── Sub-tasks / 子任务 ────────────────────────────────────────────────

    async def _do_ocr(
        self,
        ocr_rois: list[dict],
        track_ids: list[int],
    ) -> dict:
        """Run batched OCR and feed results back to tracker.
        运行批量 OCR 并将结果反馈给跟踪器。

        The OCR ROI is the truck bounding box — the server crops the image
        to this region before OCR (image_roi pre-processing).
        OCR 的 ROI 是卡车检测框——服务端在 OCR 前裁剪图像到该区域
        （image_roi 前处理）。
        """
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
        运行批量分类并将结果反馈给跟踪器。

        Classification uses image_roi — the combined person + truck bounding
        box is sent as a crop region, so the server crops the input image
        before running the classifier (pre-processing).
        分类使用 image_roi——合并的人+卡车检测框作为裁剪区域发送，
        服务端在运行分类器前裁剪输入图像（前处理）。
        """
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

    # ── Thumbnail / 缩略图 ───────────────────────────────────────────────

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


# ── CLI entry point / 命令行入口 ─────────────────────────────────────────────


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
