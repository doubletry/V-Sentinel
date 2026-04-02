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
from datetime import datetime, timezone

import cv2
import numpy as np
from loguru import logger

from core.base_processor import AnalysisResult, BaseVideoProcessor
from core.constants import (
    CLASSIFICATION_MODEL,
    DETECTION_MODEL,
    LABEL_EN_TO_ZH,
    OCR_INTERVAL,
    OCR_MODEL,
    PERSON_LABEL,
    TRUCK_LABELS,
)
from core.runner import run_processor
from core.truck.tracker import (
    FrameAnalysis,
    TrackingDecision,
    TruckTracker,
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

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._frame_count = 0

        # Tracker is created with settings from app_settings if available.
        # 如果可用，使用 app_settings 中的设置创建跟踪器。
        self.tracker = TruckTracker(
            ocr_interval=int(
                self.app_settings.get("ocr_interval", str(OCR_INTERVAL))
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
        # (post-processing).  No local ROI filtering is needed.
        # 用户定义的 ROI 用作检测的 model_roi：服务端过滤检测结果仅保留 ROI 内
        # 的检测框（后处理）。无需本地 ROI 过滤。
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
        detect_result = await self._do_detect(
            shape=shape,
            model_name=DETECTION_MODEL,
            conf=0.5,
            model_roi=primary_roi,
            **img_kwargs,
        )
        detections = detect_result["detections"]

        # 2. Classify detections into trucks / persons / others.
        # 2. 将检测结果分为卡车/行人/其他。
        analysis = FrameAnalysis()
        for det in detections:
            label = str(det.get("label", "")).lower()
            if label in TRUCK_LABELS:
                analysis.trucks.append(det)
            elif label == PERSON_LABEL:
                analysis.persons.append(det)
            else:
                analysis.others.append(det)

        # 3. Tracker update — detection already used model_roi so all returned
        #    trucks are within the ROI, no redundant local filtering.
        # 3. 跟踪器更新——检测已使用 model_roi，所有返回的卡车都在 ROI 内，
        #    无冗余的本地过滤。
        decision: TrackingDecision = self.tracker.update(analysis)

        # Capture pre-OCR/classify state to detect meaningful changes.
        # 捕获 OCR/分类前的状态，用于检测有意义的变化。
        active_track = (
            self.tracker.get_track(decision.ocr_truck_ids[0])
            if decision.ocr_truck_ids
            else None
        )
        plate_before = active_track.best_plate if active_track else ""
        actions_before: set[str] = set()
        if decision.classify_rois:
            first_tid = decision.classify_rois[0]["track_id"]
            t = self.tracker.get_track(first_tid)
            if t is not None:
                actions_before = set(t.confirmed_actions)

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
            ocr_rois.append({
                "shape": shape,
                "roi": self._bbox_to_roi_points(track.bbox, w, h),
                **({"key": image_key} if image_key else {"image_bytes": encoded}),
            })

        if ocr_rois:
            def _handle_ocr_item(item: dict) -> None:
                image_id = item.get("image_id", 0)
                if isinstance(image_id, int) and 0 <= image_id < len(ocr_track_ids):
                    tid = ocr_track_ids[image_id]
                    self.tracker.feed_ocr(
                        tid, item.get("text", ""), item.get("confidence", 0.0)
                    )

            coros.append(
                self._do_ocr(
                    ocr_rois,
                    model_name=OCR_MODEL,
                    conf=0.3,
                    on_item=_handle_ocr_item,
                )
            )

        # 4b. Per-person classification using the combined person + truck ROI.
        #     Classification uses image_roi — the merged bounding box is
        #     sent as a crop region so the server crops before classifying
        #     (pre-processing).  Each person gets a separate classification
        #     so results can be mapped back to individual person bounding boxes.
        # 4b. 对每个行人使用合并的人+卡车 ROI 进行分类。
        #     分类使用 image_roi——合并的检测框作为裁剪区域发送，
        #     服务端在分类前裁剪（前处理）。每个人单独分类，
        #     以便将结果映射回各自的人体检测框。
        cls_items = decision.classify_rois
        cls_rois: list[dict] = []
        cls_track_ids: list[int] = []
        cls_person_bboxes: list[list[int]] = []
        for item in cls_items:
            cls_rois.append({
                "shape": shape,
                "roi": self._bbox_to_roi_points(item["roi"], w, h),
                **({"key": image_key} if image_key else {"image_bytes": encoded}),
            })
            cls_track_ids.append(item["track_id"])
            cls_person_bboxes.append(item["person_bbox"])

        if cls_rois:
            def _handle_classification_item(item: dict) -> dict | None:
                image_id = item.get("image_id", 0)
                if not isinstance(image_id, int) or not (0 <= image_id < len(cls_track_ids)):
                    return None

                tid = cls_track_ids[image_id]
                raw_label = item.get("label", "other")
                stable_label = self.tracker.feed_action(tid, raw_label)
                track = self.tracker.get_track(tid)
                return {
                    "track_id": tid,
                    "raw_label": raw_label,
                    "stable_label": stable_label,
                    "confidence": item.get("confidence", 0.0),
                    "plate": track.best_plate if track else "",
                    "person_bbox": cls_person_bboxes[image_id],
                }

            coros.append(
                self._do_classify(
                    cls_rois,
                    model_name=CLASSIFICATION_MODEL,
                    on_item=_handle_classification_item,
                )
            )

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

        # 5. Assemble key messages only: arrival, OCR, actions, departure.
        # 5. 仅组装关键消息：到达、OCR 识别、动作确认、离开。
        messages: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        # 5a. Vehicle arrival — newly confirmed trucks this frame.
        # 5a. 车辆到达——本帧新确认的卡车。
        for tid in decision.arrivals:
            track = self.tracker.get_track(tid)
            thumbnail = self._encode_thumbnail(frame)
            messages.append({
                "timestamp": now,
                "source_name": self.source_name,
                "source_id": self.source_id,
                "level": "info",
                "message": f"Vehicle arrived (track #{tid})",
                "image_base64": thumbnail,
            })

        # 5b. OCR plate recognition — detect new or improved plate.
        # 5b. OCR 车牌识别——检测新识别或改进的车牌。
        if decision.ocr_truck_ids:
            tid = decision.ocr_truck_ids[0]
            track_after = self.tracker.get_track(tid)
            plate_after = track_after.best_plate if track_after else ""
            if plate_after and plate_after != plate_before:
                messages.append({
                    "timestamp": now,
                    "source_name": self.source_name,
                    "source_id": self.source_id,
                    "level": "info",
                    "message": (
                        f"Plate recognized: {plate_after} (track #{tid})"
                    ),
                })

        # 5c. New stable actions — detect actions confirmed for the first time.
        # 5c. 新稳定动作——检测首次确认的动作。
        if decision.classify_rois:
            first_tid = decision.classify_rois[0]["track_id"]
            track_after = self.tracker.get_track(first_tid)
            if track_after is not None:
                new_actions = track_after.confirmed_actions - actions_before
                for action in sorted(new_actions):
                    action_zh = LABEL_EN_TO_ZH.get(action, action)
                    plate_info = track_after.best_plate or "unknown"
                    messages.append({
                        "timestamp": now,
                        "source_name": self.source_name,
                        "source_id": self.source_id,
                        "level": "info",
                        "message": (
                            f"Action confirmed: {action_zh} "
                            f"(plate={plate_info}, track #{first_tid})"
                        ),
                    })

        # 5d. Vehicle departure — trucks that left the scene.
        # 5d. 车辆离开——离开场景的卡车。
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

        # Serialize visit data for agent persistence
        # 序列化到访数据供代理持久化
        visit_records: list[dict] = []
        for visit in decision.visits:
            visit_records.append({
                "track_id": visit.track_id,
                "enter_time": datetime.fromtimestamp(
                    visit.enter_time, tz=timezone.utc
                ).isoformat(),
                "exit_time": datetime.fromtimestamp(
                    visit.exit_time, tz=timezone.utc
                ).isoformat(),
                "plate": visit.plate,
                "confirmed_actions": sorted(visit.confirmed_actions),
                "missing_actions": sorted(visit.missing_actions),
            })

        return AnalysisResult(
            detections=detections,
            classifications=classifications,
            ocr_texts=ocr_texts,
            messages=messages,
            extra={"visits": visit_records} if visit_records else {},
        )


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
