"""Cross-frame single-truck state machine for the truck-monitoring pipeline.
单卡车跨帧状态机，用于卡车监控流水线。

Design / 设计
------
In a given ROI area there is typically **at most one truck** at a time.
Occasional passing trucks are filtered by requiring a minimum number of
consecutive detection frames (``min_presence_frames``) before a truck is
"confirmed" and enters the active state.
在给定 ROI 区域内，通常**同一时间最多只有一辆卡车**。
偶尔路过的卡车通过要求最少连续检测帧数（``min_presence_frames``）来过滤，
达到阈值后卡车才被 "确认" 进入活跃状态。

The tracker is pure logic — no I/O, no gRPC.
跟踪器是纯逻辑——无 I/O，无 gRPC。

Key responsibilities / 主要职责:
* Match the single primary truck across frames (no complex IoU multi-tracker).
  在帧间匹配单辆主卡车（无复杂 IoU 多目标跟踪器）。
* Filter out transient / passing truck detections.
  过滤掉瞬态/路过的卡车检测。
* Keep the highest-confidence license plate per truck via OCR.
  通过 OCR 保留每辆卡车最高置信度的车牌。
* Merge person + truck bounding boxes into a combined ROI for action
  classification.
  将人和卡车的检测框合并为复合 ROI 用于动作分类。
* Temporal majority-vote filtering to stabilise flicker-prone classifications.
  时间多数投票滤波以稳定容易闪烁的分类结果。
* Record a ``VehicleVisit`` log when the truck leaves.
  卡车离开时记录 ``VehicleVisit`` 日志。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from core.truck.constants import (
    MAX_MISSING_FRAMES,
    MIN_PRESENCE_FRAMES,
    OCR_INTERVAL,
    OTHER_ACTION_LABEL,
    REQUIRED_ACTIONS,
    STABILITY_MIN_COUNT,
    STABILITY_WINDOW,
)
from core.truck.plate import should_replace_plate


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class TrackedTruck:
    """State for the single tracked truck across frames.
    单辆被跟踪卡车在多帧间的状态。"""

    track_id: int
    bbox: list[int]  # [x1, y1, x2, y2] — latest detection box / 最新检测框
    first_seen: float  # wall-clock UNIX time when first detected / 首次检测的 UNIX 时间
    last_seen: float  # wall-clock UNIX time of last detection / 最后检测的 UNIX 时间
    presence_frames: int = 1  # consecutive frames detected / 连续检测帧数
    confirmed: bool = False  # True once min_presence_frames reached / 达到最小帧数后为 True
    frames_since_ocr: int = 0  # frames since last OCR attempt / 距上次 OCR 的帧数
    best_plate: str = ""  # best license plate text so far / 目前最佳车牌文本
    best_plate_conf: float = 0.0  # confidence of best plate / 最佳车牌置信度
    action_history: deque = field(default_factory=lambda: deque(maxlen=15))
    confirmed_actions: set[str] = field(default_factory=set)
    stable_action: str = ""  # latest stabilised action label / 最新稳定化的动作标签
    missing_frames: int = 0  # consecutive frames without detection / 连续未检测到的帧数


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
    """Truck track_ids that need OCR this frame.
    本帧需要进行 OCR 的卡车 track_id 列表。"""

    classify_rois: list[dict] = field(default_factory=list)
    """Per-person classification ROIs (person bbox merged with the truck bbox).
    Each person in the ROI gets their own classification request so that
    results can be mapped back to individual person bounding boxes.
    每个人的分类 ROI（人的检测框与卡车检测框合并）。
    ROI 内每个人都有独立的分类请求，以便将结果映射回各自的人体检测框。
    Each dict: {track_id, roi: [x1, y1, x2, y2],
                person_bbox: [x1, y1, x2, y2]}"""

    visits: list[VehicleVisit] = field(default_factory=list)
    """Vehicles that left the scene this frame.
    本帧离开场景的车辆。"""

    arrivals: list[int] = field(default_factory=list)
    """Track IDs of trucks that were newly confirmed this frame.
    本帧新确认到达的卡车 track_id 列表。"""


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
    best_label = max(counts, key=lambda k: counts[k])
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
    返回 *a* 和 *b* 是否有重叠。

    Note: this helper is no longer used in the main tracker pipeline (because
    model_roi-filtered detections already share the same ROI region), but is
    kept as a general-purpose utility.
    注意：此辅助函数不再在主跟踪器流水线中使用（因为 model_roi 过滤后的
    检测已共享相同 ROI 区域），但作为通用工具保留。
    """
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _det_to_bbox(det: dict) -> list[int]:
    """Extract [x1, y1, x2, y2] from a detection dict.
    从检测字典中提取 [x1, y1, x2, y2]。"""
    return [
        int(det["x_min"]),
        int(det["y_min"]),
        int(det["x_max"]),
        int(det["y_max"]),
    ]


# ── TruckTracker ─────────────────────────────────────────────────────────────


class TruckTracker:
    """Single-truck state machine for the truck-monitoring pipeline.
    卡车监控流水线的单卡车状态机。

    Designed for scenarios where at most one truck occupies the monitored area
    at a time.  Transient / passing trucks are filtered out by requiring
    ``min_presence_frames`` consecutive detections before a truck becomes
    "confirmed".  Brief detection gaps (≤ ``max_missing_frames``) are
    tolerated to avoid premature departure events.

    **Note**: ROI filtering is handled on the server side via ``model_roi``
    during detection, so the tracker does not need to perform local ROI checks.
    适用于同一时间监控区域内最多一辆卡车的场景。通过要求
    ``min_presence_frames`` 次连续检测来过滤瞬态/路过的卡车。
    容忍短暂检测间隙（≤ ``max_missing_frames``）以避免过早触发离开事件。

    **注意**：ROI 过滤在检测阶段通过 ``model_roi`` 在服务端完成，
    跟踪器无需进行本地 ROI 检查。

    Parameters
    ----------
    ocr_interval:
        Number of frames between OCR attempts on the tracked truck.
        同一卡车两次 OCR 之间的帧数间隔。
    max_missing_frames:
        Consecutive frames without detection before the truck is considered
        to have left.
        连续未检测到卡车的帧数上限，超过后认为卡车已离开。
    min_presence_frames:
        Minimum consecutive detection frames before a truck is "confirmed"
        (not a passing truck).  Set to 1 to disable filtering.
        卡车被 "确认" 前最少的连续检测帧数（非路过卡车）。设为 1 禁用过滤。
    stability_window:
        Size of the temporal sliding window for majority-vote filtering.
        多数投票滤波的时间滑动窗口大小。
    stability_min_count:
        Minimum occurrences within the window to accept a classification.
        窗口内接受分类结果所需的最小出现次数。
    required_actions:
        The set of action labels that must all be observed during a visit.
        车辆到访期间需全部观测到的动作标签集合。
    """

    def __init__(
        self,
        *,
        ocr_interval: int = OCR_INTERVAL,
        max_missing_frames: int = MAX_MISSING_FRAMES,
        min_presence_frames: int = MIN_PRESENCE_FRAMES,
        stability_window: int = STABILITY_WINDOW,
        stability_min_count: int = STABILITY_MIN_COUNT,
        required_actions: frozenset[str] | set[str] = REQUIRED_ACTIONS,
    ) -> None:
        self.ocr_interval = ocr_interval
        self.max_missing_frames = max_missing_frames
        self.min_presence_frames = min_presence_frames
        self.stability_window = stability_window
        self.stability_min_count = stability_min_count
        self.required_actions = frozenset(required_actions)

        # At most one active truck at a time.
        # 同一时间最多一辆活跃卡车。
        self._track: TrackedTruck | None = None
        self._next_id: int = 0
        self._frame_idx: int = 0
        self._visits: list[VehicleVisit] = []

    # ── Public API ────────────────────────────────────────────────────────

    def update(self, analysis: FrameAnalysis) -> TrackingDecision:
        """Process one frame of detections and return tracking decisions.
        处理一帧检测结果并返回跟踪决策。

        The state transitions are:
        状态转换如下：

        1. Pick the best truck detection (highest confidence).
           Detection is already filtered by ``model_roi`` on the server side,
           so no local ROI filtering is needed.
           选择最佳卡车检测（最高置信度）。
           检测已在服务端通过 ``model_roi`` 过滤，无需本地 ROI 过滤。
        2. If a truck is currently tracked:
           如果当前有被跟踪的卡车：
           a. If the new detection matches, update the track.
              如果新检测匹配，更新轨迹。
           b. Otherwise increment ``missing_frames``; if it exceeds
              ``max_missing_frames``, the truck has left.
              否则增加 ``missing_frames``；超过 ``max_missing_frames`` 则认为离开。
        3. If no truck is tracked, pick the best candidate and start counting
           ``presence_frames`` towards ``min_presence_frames``.
           如果没有被跟踪的卡车，选择最佳候选并开始累计 ``presence_frames``。
        """
        self._frame_idx += 1
        now = time.time()
        decision = TrackingDecision()

        # Pick the single best truck detection (highest confidence).
        # Detection results are already filtered to the ROI on the server
        # via model_roi, so no local filtering is needed.
        # 选择单个最佳卡车检测（最高置信度）。
        # 检测结果已在服务端通过 model_roi 过滤到 ROI 内，无需本地过滤。
        best_det: dict | None = None
        if analysis.trucks:
            best_det = max(analysis.trucks, key=lambda d: d.get("confidence", 0))

        # 2. Update existing track or handle departure.
        # 2. 更新已有轨迹或处理离开事件。
        if self._track is not None:
            if best_det is not None:
                # Truck still present — update bbox and reset missing counter.
                # 卡车仍在——更新检测框并重置缺失计数。
                self._track.bbox = _det_to_bbox(best_det)
                self._track.last_seen = now
                self._track.missing_frames = 0
                self._track.frames_since_ocr += 1

                if not self._track.confirmed:
                    self._track.presence_frames += 1
                    if self._track.presence_frames >= self.min_presence_frames:
                        self._track.confirmed = True
                        decision.arrivals.append(self._track.track_id)
            else:
                # No truck detected this frame.
                # 本帧未检测到卡车。
                self._track.missing_frames += 1
                if self._track.missing_frames > self.max_missing_frames:
                    # Truck has left — log visit only if it was confirmed.
                    # 卡车已离开——仅当已确认时记录到访日志。
                    if self._track.confirmed:
                        visit = VehicleVisit(
                            track_id=self._track.track_id,
                            enter_time=self._track.first_seen,
                            exit_time=self._track.last_seen,
                            plate=self._track.best_plate,
                            confirmed_actions=set(self._track.confirmed_actions),
                            missing_actions=(
                                self.required_actions - self._track.confirmed_actions
                            ),
                        )
                        decision.visits.append(visit)
                        self._visits.append(visit)
                    self._track = None
        else:
            # 3. No truck tracked — start a new candidate if detected.
            # 3. 当前无跟踪卡车——如检测到则启动新候选。
            if best_det is not None:
                tid = self._next_id
                self._next_id += 1
                immediately_confirmed = self.min_presence_frames <= 1
                self._track = TrackedTruck(
                    track_id=tid,
                    bbox=_det_to_bbox(best_det),
                    first_seen=now,
                    last_seen=now,
                    presence_frames=1,
                    confirmed=immediately_confirmed,
                )
                if immediately_confirmed:
                    decision.arrivals.append(tid)

        # 4. Build decisions for the confirmed active truck.
        # 4. 为已确认的活跃卡车构建决策。
        if self._track is not None and self._track.confirmed:
            tid = self._track.track_id

            # OCR needed?  Yes when: no plate yet, or interval reached.
            # 是否需要 OCR？在以下情况：尚无车牌，或达到间隔。
            if (
                self._track.best_plate == ""
                or self._track.frames_since_ocr >= self.ocr_interval
            ):
                decision.ocr_truck_ids.append(tid)

            # Classification: produce one classify_roi per person detected.
            # All persons come from model_roi-filtered detections, so they
            # are already inside the user-drawn ROI — no overlap check needed.
            # Each person's bbox is merged with the truck bbox to form the
            # classification region; the per-person bbox is preserved so
            # that classification results can be drawn on each person's box.
            # 分类：为每个检测到的人生成一个 classify_roi。
            # 所有行人都来自 model_roi 过滤后的检测，已在用户绘制的 ROI 内，
            # 无需重叠检查。每个人的检测框与卡车检测框合并构成分类区域；
            # 保留每个人的检测框以便将分类结果绘制到各自的框上。
            for p in analysis.persons:
                person_bbox = _det_to_bbox(p)
                combined = _merge_boxes([self._track.bbox, person_bbox])
                decision.classify_rois.append({
                    "track_id": tid,
                    "roi": combined,
                    "person_bbox": person_bbox,
                })

        return decision

    def feed_ocr(self, track_id: int, text: str, confidence: float) -> None:
        """Feed an OCR result for the tracked truck.
        为被跟踪的卡车提供 OCR 结果。

        Prefer the most complete plate text across the full visit; if
        completeness is tied, keep the higher-confidence result.
        在整次到访期间优先保留最完整的车牌；若完整度相同，则保留更高置信度结果。
        """
        if self._track is None or self._track.track_id != track_id:
            return
        self._track.frames_since_ocr = 0
        if should_replace_plate(
            self._track.best_plate,
            self._track.best_plate_conf,
            text,
            confidence,
        ):
            self._track.best_plate = text
            self._track.best_plate_conf = confidence

    def feed_action(self, track_id: int, label: str) -> str:
        """Feed a classification result and return the stabilised label.
        提供分类结果并返回稳定化后的标签。

        The label is added to a sliding window and the majority-vote
        winner is returned.  Only non-"other" stable labels are added
        to ``confirmed_actions``.
        标签被添加到滑动窗口中，返回多数投票的获胜者。仅非 "other" 的
        稳定标签会被添加到 ``confirmed_actions``。

        Returns the majority-voted stable label (may be ``""`` if not yet
        stable).
        返回多数投票后的稳定标签（若尚未稳定可能返回 ``""``）。
        """
        if self._track is None or self._track.track_id != track_id:
            return ""
        normalized_label = label
        self._track.action_history.append(normalized_label)
        stable = _majority_vote(
            self._track.action_history,
            min_count=self.stability_min_count,
        )
        if stable and stable != OTHER_ACTION_LABEL:
            self._track.confirmed_actions.add(stable)
        self._track.stable_action = stable
        return stable

    def get_track(self, track_id: int) -> TrackedTruck | None:
        """Get the current active truck state (or ``None``).
        获取当前活跃卡车状态（如无则返回 ``None``）。"""
        if self._track is not None and self._track.track_id == track_id:
            return self._track
        return None

    def get_all_tracks(self) -> dict[int, TrackedTruck]:
        """Return all active tracks (0 or 1 entries).
        返回所有活跃轨迹（0 或 1 条）。"""
        if self._track is not None:
            return {self._track.track_id: self._track}
        return {}

    @property
    def visits(self) -> list[VehicleVisit]:
        """All recorded vehicle visits (including current session).
        所有记录的车辆到访（包括当前会话）。"""
        return list(self._visits)
