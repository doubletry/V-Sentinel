"""Tests for truck_tracker and truck_processor modules.
卡车跟踪器和卡车处理器模块的测试。"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import numpy as np
import pytest

from core.base_processor import AnalysisResult, BaseVideoProcessor
from core.constants import REQUIRED_ACTIONS
from core.truck_tracker import (
    FrameAnalysis,
    TrackedTruck,
    TrackingDecision,
    TruckTracker,
    VehicleVisit,
    _boxes_overlap,
    _det_to_bbox,
    _iou,
    _majority_vote,
    _merge_boxes,
)


# ── Helper factories ──────────────────────────────────────────────────────────


def _truck_det(x1=10, y1=10, x2=100, y2=100, conf=0.9, label="truck"):
    return {
        "x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2,
        "confidence": conf, "label": label,
    }


def _person_det(x1=20, y1=20, x2=60, y2=80, conf=0.8, label="person"):
    return {
        "x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2,
        "confidence": conf, "label": label,
    }


# ── Tests for helper functions ────────────────────────────────────────────────


class TestIoU:
    def test_identical_boxes(self):
        assert _iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0

    def test_no_overlap(self):
        assert _iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0

    def test_partial_overlap(self):
        iou = _iou([0, 0, 10, 10], [5, 5, 15, 15])
        assert 0 < iou < 1
        # intersection = 5*5 = 25, union = 100+100-25 = 175
        assert abs(iou - 25 / 175) < 1e-6

    def test_contained_box(self):
        iou = _iou([0, 0, 20, 20], [5, 5, 15, 15])
        # intersection = 10*10=100, union = 400+100-100=400
        assert abs(iou - 100 / 400) < 1e-6

    def test_zero_area_box(self):
        assert _iou([5, 5, 5, 5], [0, 0, 10, 10]) == 0.0


class TestMajorityVote:
    def test_empty_history(self):
        from collections import deque
        assert _majority_vote(deque()) == ""

    def test_single_label_below_threshold(self):
        from collections import deque
        assert _majority_vote(deque(["a", "a"]), min_count=3) == ""

    def test_single_label_at_threshold(self):
        from collections import deque
        assert _majority_vote(deque(["a", "a", "a"]), min_count=3) == "a"

    def test_majority_wins(self):
        from collections import deque
        history = deque(["a", "b", "a", "a", "b"])
        assert _majority_vote(history, min_count=2) == "a"


class TestMergeBoxes:
    def test_single_box(self):
        assert _merge_boxes([[10, 20, 30, 40]]) == [10, 20, 30, 40]

    def test_two_boxes(self):
        result = _merge_boxes([[10, 20, 30, 40], [5, 10, 50, 60]])
        assert result == [5, 10, 50, 60]


class TestBoxesOverlap:
    def test_overlapping(self):
        assert _boxes_overlap([0, 0, 10, 10], [5, 5, 15, 15]) is True

    def test_non_overlapping(self):
        assert _boxes_overlap([0, 0, 10, 10], [20, 20, 30, 30]) is False

    def test_adjacent(self):
        # touching edges = not overlapping
        assert _boxes_overlap([0, 0, 10, 10], [10, 0, 20, 10]) is False


class TestDetToBbox:
    def test_conversion(self):
        det = {"x_min": 1.5, "y_min": 2.7, "x_max": 10.9, "y_max": 20.1}
        assert _det_to_bbox(det) == [1, 2, 10, 20]


# ── Tests for TruckTracker (single-truck model) ──────────────────────────────


class TestTruckTracker:
    """Tests for the simplified single-truck-in-ROI state machine.
    简化的 ROI 内单卡车状态机测试。"""

    def test_new_truck_creates_track(self):
        """A new truck detection should start a candidate track.
        新的卡车检测应启动一个候选轨迹。"""
        tracker = TruckTracker(min_presence_frames=1)
        analysis = FrameAnalysis(trucks=[_truck_det()])
        tracker.update(analysis)
        assert len(tracker.get_all_tracks()) == 1

    def test_same_truck_keeps_track(self):
        """Repeated detections of the same truck maintain a single track.
        重复检测同一卡车保持单一轨迹。"""
        tracker = TruckTracker(min_presence_frames=1)
        det = _truck_det()
        tracker.update(FrameAnalysis(trucks=[det]))
        tracker.update(FrameAnalysis(trucks=[det]))
        assert len(tracker.get_all_tracks()) == 1

    def test_truck_leaves_produces_visit(self):
        """When the truck disappears, a VehicleVisit is produced.
        卡车消失时应产生 VehicleVisit。"""
        tracker = TruckTracker(min_presence_frames=1, max_missing_frames=0)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        assert len(tracker.get_all_tracks()) == 1
        # Next frame: no trucks → departure
        decision = tracker.update(FrameAnalysis())
        assert len(decision.visits) == 1
        assert len(tracker.get_all_tracks()) == 0

    def test_visit_records_plate(self):
        """Visit should record the best plate from OCR.
        到访记录应包含 OCR 的最佳车牌。"""
        tracker = TruckTracker(min_presence_frames=1, max_missing_frames=0)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        track_id = list(tracker.get_all_tracks().keys())[0]
        tracker.feed_ocr(track_id, "ABC123", 0.9)
        decision = tracker.update(FrameAnalysis())
        assert decision.visits[0].plate == "ABC123"

    def test_best_plate_keeps_highest_confidence(self):
        """Only the OCR result with the highest confidence is kept.
        仅保留置信度最高的 OCR 结果。"""
        tracker = TruckTracker(min_presence_frames=1)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]
        tracker.feed_ocr(tid, "LOW", 0.5)
        tracker.feed_ocr(tid, "HIGH", 0.95)
        tracker.feed_ocr(tid, "LOWER", 0.3)
        assert tracker.get_track(tid).best_plate == "HIGH"
        assert tracker.get_track(tid).best_plate_conf == 0.95

    def test_ocr_interval_triggers_correctly(self):
        """OCR should trigger on first frame and after ocr_interval frames.
        OCR 应在第一帧和 ocr_interval 帧后触发。"""
        tracker = TruckTracker(ocr_interval=3, min_presence_frames=1)
        det = _truck_det()
        # Frame 1: new truck → needs OCR (best_plate is empty)
        d1 = tracker.update(FrameAnalysis(trucks=[det]))
        assert len(d1.ocr_truck_ids) == 1
        # Feed OCR to reset counter
        tid = d1.ocr_truck_ids[0]
        tracker.feed_ocr(tid, "PL8", 0.8)
        # Frame 2: frames_since_ocr = 1 (< 3)
        d2 = tracker.update(FrameAnalysis(trucks=[det]))
        assert tid not in d2.ocr_truck_ids
        # Frame 3: frames_since_ocr = 2 (< 3)
        d3 = tracker.update(FrameAnalysis(trucks=[det]))
        assert tid not in d3.ocr_truck_ids
        # Frame 4: frames_since_ocr = 3 (>= 3)
        d4 = tracker.update(FrameAnalysis(trucks=[det]))
        assert tid in d4.ocr_truck_ids

    def test_person_truck_produces_classify_roi(self):
        """When person and truck are both detected, a per-person combined ROI
        is produced — no overlap check needed.
        当同时检测到行人和卡车时，为每个人产生合并 ROI——无需重叠检查。"""
        tracker = TruckTracker(min_presence_frames=1)
        truck = _truck_det(10, 10, 100, 100)
        person = _person_det(20, 20, 60, 80)
        decision = tracker.update(FrameAnalysis(trucks=[truck], persons=[person]))
        assert len(decision.classify_rois) == 1
        roi = decision.classify_rois[0]["roi"]
        # Merged box should encompass both
        assert roi == [10, 10, 100, 100]
        # person_bbox is preserved for per-person label display
        assert decision.classify_rois[0]["person_bbox"] == [20, 20, 60, 80]

    def test_no_person_means_no_classify_roi(self):
        """Without person detection, no classification ROI is produced.
        无行人检测时不产生分类 ROI。"""
        tracker = TruckTracker(min_presence_frames=1)
        truck = _truck_det(10, 10, 100, 100)
        decision = tracker.update(FrameAnalysis(trucks=[truck]))
        assert len(decision.classify_rois) == 0

    def test_non_overlapping_person_still_produces_classify_roi(self):
        """Person far from truck still produces a classification ROI because
        both are within the model_roi-filtered area — no overlap required.
        远离卡车的行人仍然产生分类 ROI，因为两者都在 model_roi 过滤区域内——
        不需要重叠。"""
        tracker = TruckTracker(min_presence_frames=1)
        truck = _truck_det(10, 10, 100, 100)
        person = _person_det(200, 200, 300, 300)  # no overlap but same ROI
        decision = tracker.update(FrameAnalysis(trucks=[truck], persons=[person]))
        assert len(decision.classify_rois) == 1
        roi = decision.classify_rois[0]["roi"]
        # Merged box encompasses both
        assert roi == [10, 10, 300, 300]
        assert decision.classify_rois[0]["person_bbox"] == [200, 200, 300, 300]

    def test_multiple_persons_produce_multiple_classify_rois(self):
        """Each person gets their own classify_roi for individual labelling.
        每个人都获得独立的 classify_roi 以进行独立标注。"""
        tracker = TruckTracker(min_presence_frames=1)
        truck = _truck_det(10, 10, 100, 100)
        p1 = _person_det(20, 20, 60, 80)
        p2 = _person_det(200, 200, 300, 300)
        decision = tracker.update(FrameAnalysis(
            trucks=[truck], persons=[p1, p2]
        ))
        assert len(decision.classify_rois) == 2
        assert decision.classify_rois[0]["person_bbox"] == [20, 20, 60, 80]
        assert decision.classify_rois[1]["person_bbox"] == [200, 200, 300, 300]

    def test_action_stability_filter(self):
        """Action labels require min_count occurrences to become stable.
        动作标签需要达到 min_count 次出现才稳定。"""
        tracker = TruckTracker(stability_min_count=3, min_presence_frames=1)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        # First two: not yet stable
        assert tracker.feed_action(tid, "action1") == ""
        assert tracker.feed_action(tid, "action1") == ""
        # Third: now stable
        assert tracker.feed_action(tid, "action1") == "action1"

    def test_action_flicker_filtered(self):
        """Flickering labels are filtered by majority vote.
        闪烁的标签被多数投票过滤。"""
        tracker = TruckTracker(stability_min_count=3, min_presence_frames=1)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        tracker.feed_action(tid, "action1")
        tracker.feed_action(tid, "action2")  # flicker
        tracker.feed_action(tid, "action1")
        tracker.feed_action(tid, "action1")
        # action1 appeared 3 times, action2 only once
        assert tracker.get_track(tid).stable_action == "action1"

    def test_confirmed_actions_accumulate(self):
        """Multiple stable actions accumulate in confirmed_actions set.
        多个稳定动作累积到 confirmed_actions 集合中。"""
        tracker = TruckTracker(stability_min_count=2, min_presence_frames=1)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        # Confirm action1 (2 consecutive → stable)
        tracker.feed_action(tid, "action1")
        tracker.feed_action(tid, "action1")
        assert "action1" in tracker.get_track(tid).confirmed_actions

        # Confirm action2 (feed enough to become the majority)
        tracker.feed_action(tid, "action2")
        tracker.feed_action(tid, "action2")
        tracker.feed_action(tid, "action2")

        track = tracker.get_track(tid)
        assert "action1" in track.confirmed_actions
        assert "action2" in track.confirmed_actions

    def test_other_label_not_added_to_confirmed(self):
        """The 'other' label should not be added to confirmed_actions.
        'other' 标签不应添加到 confirmed_actions。"""
        tracker = TruckTracker(stability_min_count=2, min_presence_frames=1)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        tracker.feed_action(tid, "other")
        tracker.feed_action(tid, "other")
        tracker.feed_action(tid, "other")

        track = tracker.get_track(tid)
        assert "other" not in track.confirmed_actions
        assert track.stable_action == "other"

    def test_missing_actions_in_visit(self):
        """Visit should report actions that were never confirmed.
        到访记录应报告未确认的动作。"""
        required = {"action1", "action2", "action3"}
        tracker = TruckTracker(
            stability_min_count=2,
            required_actions=required,
            min_presence_frames=1,
            max_missing_frames=0,
        )
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        # Only confirm action1
        tracker.feed_action(tid, "action1")
        tracker.feed_action(tid, "action1")

        # Truck leaves
        decision = tracker.update(FrameAnalysis())
        visit = decision.visits[0]
        assert visit.confirmed_actions == {"action1"}
        assert visit.missing_actions == {"action2", "action3"}

    def test_feed_ocr_unknown_track_noop(self):
        """feed_ocr on unknown track_id should not raise.
        对未知 track_id 调用 feed_ocr 不应抛异常。"""
        tracker = TruckTracker()
        tracker.feed_ocr(999, "XYZ", 0.9)  # should not raise

    def test_feed_action_unknown_track_returns_empty(self):
        """feed_action on unknown track_id returns empty string.
        对未知 track_id 调用 feed_action 返回空字符串。"""
        tracker = TruckTracker()
        assert tracker.feed_action(999, "action1") == ""

    def test_single_truck_replaces_when_old_leaves(self):
        """Only one truck tracked at a time; new one starts after old leaves.
        同一时间只跟踪一辆卡车；旧的离开后才开始跟踪新的。"""
        tracker = TruckTracker(min_presence_frames=1, max_missing_frames=0)
        t1 = _truck_det(10, 10, 50, 50)
        # Truck 1 arrives
        tracker.update(FrameAnalysis(trucks=[t1]))
        assert len(tracker.get_all_tracks()) == 1
        tid1 = list(tracker.get_all_tracks().keys())[0]

        # Truck 1 leaves (no detections)
        decision = tracker.update(FrameAnalysis())
        assert len(decision.visits) == 1
        assert len(tracker.get_all_tracks()) == 0

        # Truck 2 arrives
        t2 = _truck_det(200, 200, 300, 300)
        tracker.update(FrameAnalysis(trucks=[t2]))
        assert len(tracker.get_all_tracks()) == 1
        tid2 = list(tracker.get_all_tracks().keys())[0]
        assert tid2 != tid1  # different track_id

    def test_visits_property_accumulates(self):
        """visits property accumulates across multiple departures.
        visits 属性在多次离开中累积。"""
        tracker = TruckTracker(min_presence_frames=1, max_missing_frames=0)
        tracker.update(FrameAnalysis(trucks=[_truck_det(10, 10, 50, 50)]))
        tracker.update(FrameAnalysis())  # truck leaves → visit 1
        tracker.update(FrameAnalysis(trucks=[_truck_det(200, 200, 300, 300)]))
        tracker.update(FrameAnalysis())  # truck 2 leaves → visit 2
        assert len(tracker.visits) == 2

    def test_transient_truck_filtered_by_min_presence(self):
        """A truck appearing for fewer than min_presence_frames is filtered
        (not confirmed, no visit on departure).
        出现帧数少于 min_presence_frames 的卡车被过滤
        （不确认，离开时不产生到访记录）。"""
        tracker = TruckTracker(min_presence_frames=3, max_missing_frames=0)
        det = _truck_det()
        # Frame 1: first appearance (presence_frames=1, not confirmed)
        d1 = tracker.update(FrameAnalysis(trucks=[det]))
        assert len(tracker.get_all_tracks()) == 1
        assert len(d1.ocr_truck_ids) == 0  # not confirmed yet
        # Frame 2: still not confirmed (presence_frames=2)
        d2 = tracker.update(FrameAnalysis(trucks=[det]))
        assert len(d2.ocr_truck_ids) == 0
        # Truck disappears before reaching min_presence_frames
        d3 = tracker.update(FrameAnalysis())
        # No visit should be recorded for transient truck
        assert len(d3.visits) == 0
        assert len(tracker.get_all_tracks()) == 0

    def test_confirmed_truck_gets_ocr_and_classify(self):
        """Once confirmed, the truck triggers OCR and classification decisions.
        一旦确认，卡车触发 OCR 和分类决策。"""
        tracker = TruckTracker(min_presence_frames=2)
        det = _truck_det(10, 10, 100, 100)
        person = _person_det(20, 20, 60, 80)
        # Frame 1: not yet confirmed
        d1 = tracker.update(FrameAnalysis(trucks=[det], persons=[person]))
        assert len(d1.ocr_truck_ids) == 0
        assert len(d1.classify_rois) == 0
        # Frame 2: now confirmed
        d2 = tracker.update(FrameAnalysis(trucks=[det], persons=[person]))
        assert len(d2.ocr_truck_ids) == 1
        assert len(d2.classify_rois) == 1

    def test_max_missing_frames_tolerates_gaps(self):
        """Brief detection gaps within max_missing_frames keep the track alive.
        max_missing_frames 内的短暂检测间隙保持轨迹活跃。"""
        tracker = TruckTracker(min_presence_frames=1, max_missing_frames=2)
        det = _truck_det()
        tracker.update(FrameAnalysis(trucks=[det]))
        # 1 frame missing (within tolerance)
        d = tracker.update(FrameAnalysis())
        assert len(d.visits) == 0
        assert len(tracker.get_all_tracks()) == 1
        # 2 frames missing total
        d = tracker.update(FrameAnalysis())
        assert len(d.visits) == 0
        assert len(tracker.get_all_tracks()) == 1
        # 3 frames missing → exceeds max_missing_frames
        d = tracker.update(FrameAnalysis())
        assert len(d.visits) == 1
        assert len(tracker.get_all_tracks()) == 0

    def test_best_detection_by_confidence(self):
        """When multiple trucks detected, the one with highest confidence wins.
        当检测到多辆卡车时，置信度最高的获胜。"""
        tracker = TruckTracker(min_presence_frames=1)
        t1 = _truck_det(10, 10, 50, 50, conf=0.6)
        t2 = _truck_det(200, 200, 300, 300, conf=0.95)
        d = tracker.update(FrameAnalysis(trucks=[t1, t2]))
        assert len(tracker.get_all_tracks()) == 1
        # The tracked truck should have the bbox of the highest-conf detection
        track = list(tracker.get_all_tracks().values())[0]
        assert track.bbox == [200, 200, 300, 300]


# ── Tests for _ensure_even_dims ───────────────────────────────────────────────


class TestEnsureEvenDims:
    def test_even_dims_unchanged(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        result = BaseVideoProcessor._ensure_even_dims(frame)
        assert result.shape == (100, 200, 3)

    def test_odd_height_cropped(self):
        frame = np.zeros((101, 200, 3), dtype=np.uint8)
        result = BaseVideoProcessor._ensure_even_dims(frame)
        assert result.shape == (100, 200, 3)

    def test_odd_width_cropped(self):
        frame = np.zeros((100, 201, 3), dtype=np.uint8)
        result = BaseVideoProcessor._ensure_even_dims(frame)
        assert result.shape == (100, 200, 3)

    def test_both_odd_cropped(self):
        frame = np.zeros((101, 201, 3), dtype=np.uint8)
        result = BaseVideoProcessor._ensure_even_dims(frame)
        assert result.shape == (100, 200, 3)


# ── Tests for TruckMonitorProcessor ──────────────────────────────────────────


class TestTruckMonitorProcessor:
    async def test_no_vengine_echo_mode(self):
        """Without V-Engine, processor runs in echo mode (draws frame number).
        无 V-Engine 时，处理器运行在回显模式（绘制帧号）。"""
        from core.truck_processor import TruckMonitorProcessor
        proc = TruckMonitorProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = await proc.process_frame(
            frame=frame, encoded=b"", shape=(480, 640, 3),
            roi_pixel_points=[],
        )
        assert result.annotated_frame is not None

    async def test_full_pipeline_with_truck_and_person(self):
        """Full pipeline: detect truck+person → OCR → classify → track.
        完整流水线：检测卡车+行人 → OCR → 分类 → 跟踪。"""
        from core.truck_processor import TruckMonitorProcessor

        vengine = AsyncMock()
        vengine.upload_and_get_key.return_value = "frame-key"
        vengine.detect.return_value = [
            _truck_det(10, 10, 200, 200, label="truck"),
            _person_det(30, 30, 80, 150, label="person"),
        ]
        vengine.ocr.return_value = [
            {"text": "ABC123", "confidence": 0.85, "points": [], "image_id": 0},
        ]
        vengine.classify.return_value = [
            {"label": "action1", "confidence": 0.9, "class_id": 1, "image_id": 0},
        ]

        proc = TruckMonitorProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            vengine_client=vengine,
            app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
        )
        # Override tracker min_presence_frames=1 for test simplicity
        proc.tracker = TruckTracker(min_presence_frames=1)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = await proc.process_frame(
            frame=frame, encoded=b"jpeg",
            shape=(480, 640, 3), roi_pixel_points=[],
        )

        assert len(result.detections) == 2
        assert len(result.ocr_texts) >= 1
        assert len(result.classifications) >= 1
        # Verify OCR fed back to tracker
        tid = list(proc.tracker.get_all_tracks().keys())[0]
        track = proc.tracker.get_track(tid)
        assert track.best_plate == "ABC123"

    async def test_truck_leaves_produces_visit_message(self):
        """When truck leaves, a visit message is produced with the plate.
        卡车离开时应产生带车牌的到访消息。"""
        from core.truck_processor import TruckMonitorProcessor

        vengine = AsyncMock()
        vengine.upload_and_get_key.return_value = "frame-key"
        vengine.detect.side_effect = [
            [_truck_det(10, 10, 200, 200, label="truck")],
            [],  # truck leaves
        ]
        vengine.ocr.return_value = [
            {"text": "XY789", "confidence": 0.7, "points": [], "image_id": 0},
        ]
        vengine.classify.return_value = []

        proc = TruckMonitorProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            vengine_client=vengine,
            app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
        )
        # Override tracker for test simplicity
        proc.tracker = TruckTracker(min_presence_frames=1, max_missing_frames=0)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Frame 1: truck arrives
        await proc.process_frame(
            frame=frame, encoded=b"jpeg",
            shape=(480, 640, 3), roi_pixel_points=[],
        )
        # Frame 2: truck leaves
        result2 = await proc.process_frame(
            frame=frame, encoded=b"jpeg",
            shape=(480, 640, 3), roi_pixel_points=[],
        )

        visit_msgs = [m for m in result2.messages if "Vehicle left" in m.get("message", "")]
        assert len(visit_msgs) == 1
        assert "XY789" in visit_msgs[0]["message"]

    async def test_classification_includes_person_bbox(self):
        """Classification results include person_bbox for per-person labelling.
        分类结果包含 person_bbox 用于每个人的标注。"""
        from core.truck_processor import TruckMonitorProcessor

        vengine = AsyncMock()
        vengine.upload_and_get_key.return_value = "frame-key"
        vengine.detect.return_value = [
            _truck_det(10, 10, 200, 200, label="truck"),
            _person_det(30, 30, 80, 150, label="person"),
        ]
        vengine.ocr.return_value = [
            {"text": "ABC", "confidence": 0.9, "points": [], "image_id": 0},
        ]
        vengine.classify.return_value = [
            {"label": "action1", "confidence": 0.9, "class_id": 1, "image_id": 0},
        ]

        proc = TruckMonitorProcessor(
            source_id="s1",
            source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
            vengine_client=vengine,
            app_settings={"mediamtx_rtsp_addr": "rtsp://localhost:8554"},
        )
        proc.tracker = TruckTracker(min_presence_frames=1)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = await proc.process_frame(
            frame=frame, encoded=b"jpeg",
            shape=(480, 640, 3), roi_pixel_points=[],
        )
        assert len(result.classifications) >= 1
        cls = result.classifications[0]
        assert "person_bbox" in cls
        assert cls["person_bbox"] == [30, 30, 80, 150]


class TestDrawOnFrameWithClassifications:
    def test_person_gets_classification_label(self):
        """Person detection with matching classification shows action label.
        有匹配分类结果的行人检测显示动作标签。"""

        class DummyProcessor(BaseVideoProcessor):
            async def process_frame(self, frame, encoded, shape, roi_pixel_points):
                return AnalysisResult()

        proc = DummyProcessor(
            source_id="s1", source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = AnalysisResult(
            detections=[
                {"x_min": 30, "y_min": 30, "x_max": 80, "y_max": 150,
                 "confidence": 0.8, "label": "person"},
                {"x_min": 10, "y_min": 10, "x_max": 200, "y_max": 200,
                 "confidence": 0.9, "label": "truck"},
            ],
            classifications=[
                {"stable_label": "action1", "raw_label": "action1",
                 "confidence": 0.9,
                 "person_bbox": [30, 30, 80, 150]},
            ],
        )
        drawn = proc.draw_on_frame(frame, result)
        # Should have drawn something (non-zero pixels)
        assert drawn.sum() > 0

    def test_detection_without_classification(self):
        """Detection without classification uses default label.
        无分类结果的检测使用默认标签。"""

        class DummyProcessor(BaseVideoProcessor):
            async def process_frame(self, frame, encoded, shape, roi_pixel_points):
                return AnalysisResult()

        proc = DummyProcessor(
            source_id="s1", source_name="cam",
            rtsp_url="rtsp://localhost:8554/cam1",
        )
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = AnalysisResult(
            detections=[
                {"x_min": 10, "y_min": 10, "x_max": 100, "y_max": 100,
                 "confidence": 0.9, "label": "truck"},
            ],
        )
        drawn = proc.draw_on_frame(frame, result)
        assert drawn.sum() > 0
