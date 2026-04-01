"""Cross-frame truck tracking, license-plate OCR, action classification
stabilisation and vehicle visit logging.

跨帧卡车跟踪、车牌 OCR、动作分类稳定化及车辆到访日志。

Design
------
* Each tracked truck is represented by a ``TrackedTruck`` dataclass.
* ``TruckTracker`` is the main state-machine that should be called once per
  frame with fresh detection results.  It is *pure logic* — no I/O, no gRPC.
* The tracker takes care of:
  - Matching new truck detections to existing tracks (IoU).
  - Keeping the highest-confidence license-plate per truck.
  - Merging person + truck bounding boxes into a combined ROI for action
    classification.
  - Temporal filtering (majority-vote) to stabilise flicker-prone
    classifications.
  - Recording a ``VehicleVisit`` log entry when a truck leaves the frame.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class TrackedTruck:
    """State for a single tracked truck across frames.
    单辆被跟踪卡车在多帧间的状态。"""

    track_id: int
    bbox: list[int]  # [x1, y1, x2, y2]
    first_seen: float  # monotonic time
    last_seen: float
    frames_since_ocr: int = 0
    best_plate: str = ""
    best_plate_conf: float = 0.0
    action_history: deque = field(default_factory=lambda: deque(maxlen=15))
    confirmed_actions: set[str] = field(default_factory=set)
    stable_action: str = ""


@dataclass
class VehicleVisit:
    """Log entry for a truck that has entered and left the scene.
    一辆卡车进出场景的日志条目。"""

    track_id: int
    enter_time: float
    exit_time: float
    plate: str
    confirmed_actions: set[str]
    missing_actions: set[str]


@dataclass
class FrameAnalysis:
    """Input detections for a single frame, pre-classified by label.
    单帧的输入检测结果，按标签预分类。"""

    trucks: list[dict] = field(default_factory=list)
    persons: list[dict] = field(default_factory=list)
    others: list[dict] = field(default_factory=list)


@dataclass
class TrackingDecision:
    """Per-frame output from the tracker telling the caller what to do next.
    跟踪器的每帧输出，指示调用方下一步操作。"""

    ocr_truck_ids: list[int] = field(default_factory=list)
    """Truck track_ids that need OCR this frame."""

    classify_rois: list[dict] = field(default_factory=list)
    """Combined person+truck ROIs to send to the action classifier.
    Each dict: {track_id, roi: [x1, y1, x2, y2]}"""

    visits: list[VehicleVisit] = field(default_factory=list)
    """Vehicles that left the scene this frame."""


# ── Helpers ──────────────────────────────────────────────────────────────────


def _iou(a: list[int], b: list[int]) -> float:
    """Compute Intersection-over-Union between two [x1,y1,x2,y2] boxes.
    计算两个 [x1,y1,x2,y2] 框的 IoU。"""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _majority_vote(history: deque, min_count: int = 3) -> str:
    """Return the most frequent label in *history* if it appears ≥ *min_count*
    times; otherwise return ``""``.
    返回 *history* 中出现次数最多且 ≥ *min_count* 的标签，否则返回空串。"""
    if not history:
        return ""
    counts: dict[str, int] = {}
    for label in history:
        counts[label] = counts.get(label, 0) + 1
    best_label = max(counts, key=counts.get)  # type: ignore[arg-type]
    return best_label if counts[best_label] >= min_count else ""


def _merge_boxes(boxes: list[list[int]]) -> list[int]:
    """Return the bounding box that encloses all input boxes.
    返回包含所有输入框的外接框。"""
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes)
    y2 = max(b[3] for b in boxes)
    return [x1, y1, x2, y2]


def _boxes_overlap(a: list[int], b: list[int]) -> bool:
    """Return whether *a* and *b* overlap at all.
    返回 *a* 和 *b* 是否有重叠。"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _box_in_roi(box: list[int], roi: list[list[int]]) -> bool:
    """Rough check: is the centre of *box* inside the polygon *roi*?
    粗略检查：*box* 的中心点是否在多边形 *roi* 内？

    *roi* is a list of ``[x, y]`` pairs.  For simplicity we use a bounding-box
    approximation of the polygon.
    *roi* 是 ``[x, y]`` 对列表。简化处理，使用多边形的外接矩形近似。
    """
    if not roi:
        return True  # no ROI means everything is in scope
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    xs = [p[0] for p in roi]
    ys = [p[1] for p in roi]
    return min(xs) <= cx <= max(xs) and min(ys) <= cy <= max(ys)


def _det_to_bbox(det: dict) -> list[int]:
    """Extract [x1, y1, x2, y2] from a detection dict."""
    return [
        int(det["x_min"]),
        int(det["y_min"]),
        int(det["x_max"]),
        int(det["y_max"]),
    ]


# ── TruckTracker ─────────────────────────────────────────────────────────────


# The 6 required actions (exclude "other").
# 6 类必需动作（排除 "other"）。
REQUIRED_ACTIONS = frozenset(
    {"action1", "action2", "action3", "action4", "action5", "action6"}
)


class TruckTracker:
    """Frame-by-frame truck state machine.
    逐帧卡车状态机。

    Parameters
    ----------
    iou_threshold:
        IoU threshold for matching a new detection to an existing track.
        新检测与已有轨迹匹配的 IoU 阈值。
    ocr_interval:
        Number of frames between OCR attempts on the same truck.
        同一卡车两次 OCR 尝试之间的帧数间隔。
    max_missing_frames:
        Number of consecutive missing frames before a truck is considered gone.
        连续缺失帧数超过此值后认为卡车已离开。
    stability_window:
        Size of the temporal sliding window for majority-vote filtering.
        多数投票滤波的时间滑动窗口大小。
    stability_min_count:
        Minimum occurrences within the window to accept a classification.
        窗口内接受分类结果所需的最小出现次数。
    required_actions:
        The set of action labels that must all be observed during a visit.
        车辆到访期间需全部观测到的动作标签集合。
    roi:
        Optional ROI polygon as list of ``[x, y]`` pairs.  Trucks whose centre
        is outside the ROI are ignored.
        可选 ROI 多边形（``[x, y]`` 对列表）。中心不在 ROI 内的卡车被忽略。
    """

    def __init__(
        self,
        *,
        iou_threshold: float = 0.3,
        ocr_interval: int = 10,
        max_missing_frames: int = 15,
        stability_window: int = 7,
        stability_min_count: int = 3,
        required_actions: frozenset[str] | set[str] = REQUIRED_ACTIONS,
        roi: list[list[int]] | None = None,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.ocr_interval = ocr_interval
        self.max_missing_frames = max_missing_frames
        self.stability_window = stability_window
        self.stability_min_count = stability_min_count
        self.required_actions = frozenset(required_actions)
        self.roi = roi

        self._tracks: dict[int, TrackedTruck] = {}
        self._next_id: int = 0
        self._frame_idx: int = 0
        self._visits: list[VehicleVisit] = []

    # ── Public API ────────────────────────────────────────────────────────

    def update(self, analysis: FrameAnalysis) -> TrackingDecision:
        """Process one frame of detections and return tracking decisions.
        处理一帧检测结果并返回跟踪决策。"""
        self._frame_idx += 1
        now = time.monotonic()

        # 1. Match truck detections to existing tracks
        matched_ids: set[int] = set()
        new_trucks: list[dict] = []

        for det in analysis.trucks:
            bbox = _det_to_bbox(det)
            if not _box_in_roi(bbox, self.roi or []):
                continue
            best_id = self._match(bbox)
            if best_id is not None:
                track = self._tracks[best_id]
                track.bbox = bbox
                track.last_seen = now
                track.frames_since_ocr += 1
                matched_ids.add(best_id)
            else:
                new_trucks.append(det)

        # Create new tracks for unmatched truck detections
        for det in new_trucks:
            bbox = _det_to_bbox(det)
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = TrackedTruck(
                track_id=tid,
                bbox=bbox,
                first_seen=now,
                last_seen=now,
            )
            matched_ids.add(tid)

        # 2. Remove stale tracks (trucks that left)
        decision = TrackingDecision()
        stale_ids = [
            tid
            for tid, t in self._tracks.items()
            if tid not in matched_ids
        ]
        for tid in stale_ids:
            track = self._tracks.pop(tid)
            # Increment missing counter; only log visit if truck was seen for > 1 frame
            visit = VehicleVisit(
                track_id=track.track_id,
                enter_time=track.first_seen,
                exit_time=track.last_seen,
                plate=track.best_plate,
                confirmed_actions=set(track.confirmed_actions),
                missing_actions=self.required_actions - track.confirmed_actions,
            )
            decision.visits.append(visit)
            self._visits.append(visit)

        # 3. Determine which trucks need OCR
        for tid in matched_ids:
            track = self._tracks[tid]
            if track.frames_since_ocr >= self.ocr_interval or track.best_plate == "":
                decision.ocr_truck_ids.append(tid)

        # 4. Build combined person+truck ROIs for classification
        for tid in matched_ids:
            track = self._tracks[tid]
            nearby_persons = [
                _det_to_bbox(p)
                for p in analysis.persons
                if _boxes_overlap(track.bbox, _det_to_bbox(p))
            ]
            if nearby_persons:
                combined = _merge_boxes([track.bbox] + nearby_persons)
                decision.classify_rois.append(
                    {"track_id": tid, "roi": combined}
                )

        return decision

    def feed_ocr(self, track_id: int, text: str, confidence: float) -> None:
        """Feed an OCR result for a specific truck track.
        为特定卡车轨迹提供 OCR 结果。"""
        track = self._tracks.get(track_id)
        if track is None:
            return
        track.frames_since_ocr = 0
        if confidence > track.best_plate_conf:
            track.best_plate = text
            track.best_plate_conf = confidence

    def feed_action(self, track_id: int, label: str) -> str:
        """Feed a classification result and return the stabilised label.
        提供分类结果并返回稳定化后的标签。

        Returns the majority-voted stable label (may be ``""`` if not yet
        stable).
        返回多数投票后的稳定标签（若尚未稳定可能返回 ``""``）。
        """
        track = self._tracks.get(track_id)
        if track is None:
            return ""
        track.action_history.append(label)
        stable = _majority_vote(
            track.action_history,
            min_count=self.stability_min_count,
        )
        if stable and stable != "other":
            track.confirmed_actions.add(stable)
        track.stable_action = stable
        return stable

    def get_track(self, track_id: int) -> TrackedTruck | None:
        """Get the current state of a tracked truck."""
        return self._tracks.get(track_id)

    def get_all_tracks(self) -> dict[int, TrackedTruck]:
        """Return all active tracks."""
        return dict(self._tracks)

    @property
    def visits(self) -> list[VehicleVisit]:
        """All recorded vehicle visits (including current session)."""
        return list(self._visits)

    # ── Internal ──────────────────────────────────────────────────────────

    def _match(self, bbox: list[int]) -> int | None:
        """Find the existing track with the highest IoU to *bbox*.
        找到与 *bbox* IoU 最高的已有轨迹。"""
        best_id: int | None = None
        best_iou = self.iou_threshold
        for tid, track in self._tracks.items():
            score = _iou(bbox, track.bbox)
            if score > best_iou:
                best_iou = score
                best_id = tid
        return best_id
