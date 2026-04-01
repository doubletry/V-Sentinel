"""Tests for truck_tracker and truck_processor modules.
卡车跟踪器和卡车处理器模块的测试。"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import numpy as np
import pytest

from core.base_processor import AnalysisResult, BaseVideoProcessor
from core.truck_tracker import (
    FrameAnalysis,
    TrackedTruck,
    TrackingDecision,
    TruckTracker,
    VehicleVisit,
    _box_in_roi,
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


class TestBoxInRoi:
    def test_empty_roi(self):
        assert _box_in_roi([5, 5, 15, 15], []) is True

    def test_inside(self):
        roi = [[0, 0], [100, 0], [100, 100], [0, 100]]
        assert _box_in_roi([10, 10, 30, 30], roi) is True

    def test_outside(self):
        roi = [[0, 0], [50, 0], [50, 50], [0, 50]]
        assert _box_in_roi([100, 100, 200, 200], roi) is False


class TestDetToBbox:
    def test_conversion(self):
        det = {"x_min": 1.5, "y_min": 2.7, "x_max": 10.9, "y_max": 20.1}
        assert _det_to_bbox(det) == [1, 2, 10, 20]


# ── Tests for TruckTracker ────────────────────────────────────────────────────


class TestTruckTracker:
    def test_new_truck_creates_track(self):
        tracker = TruckTracker()
        analysis = FrameAnalysis(trucks=[_truck_det()])
        decision = tracker.update(analysis)
        assert len(tracker.get_all_tracks()) == 1

    def test_same_truck_keeps_track(self):
        tracker = TruckTracker()
        det = _truck_det()
        tracker.update(FrameAnalysis(trucks=[det]))
        tracker.update(FrameAnalysis(trucks=[det]))
        assert len(tracker.get_all_tracks()) == 1

    def test_truck_leaves_produces_visit(self):
        tracker = TruckTracker()
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        assert len(tracker.get_all_tracks()) == 1
        # Next frame: no trucks
        decision = tracker.update(FrameAnalysis())
        assert len(decision.visits) == 1
        assert len(tracker.get_all_tracks()) == 0

    def test_visit_records_plate(self):
        tracker = TruckTracker()
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        track_id = list(tracker.get_all_tracks().keys())[0]
        tracker.feed_ocr(track_id, "ABC123", 0.9)
        decision = tracker.update(FrameAnalysis())
        assert decision.visits[0].plate == "ABC123"

    def test_best_plate_keeps_highest_confidence(self):
        tracker = TruckTracker()
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]
        tracker.feed_ocr(tid, "LOW", 0.5)
        tracker.feed_ocr(tid, "HIGH", 0.95)
        tracker.feed_ocr(tid, "LOWER", 0.3)
        assert tracker.get_track(tid).best_plate == "HIGH"
        assert tracker.get_track(tid).best_plate_conf == 0.95

    def test_ocr_interval_triggers_correctly(self):
        tracker = TruckTracker(ocr_interval=3)
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

    def test_person_truck_overlap_produces_classify_roi(self):
        tracker = TruckTracker()
        truck = _truck_det(10, 10, 100, 100)
        person = _person_det(20, 20, 60, 80)  # overlaps with truck
        decision = tracker.update(FrameAnalysis(trucks=[truck], persons=[person]))
        assert len(decision.classify_rois) == 1
        roi = decision.classify_rois[0]["roi"]
        # Merged box should encompass both
        assert roi == [10, 10, 100, 100]

    def test_no_person_means_no_classify_roi(self):
        tracker = TruckTracker()
        truck = _truck_det(10, 10, 100, 100)
        decision = tracker.update(FrameAnalysis(trucks=[truck]))
        assert len(decision.classify_rois) == 0

    def test_non_overlapping_person_no_classify_roi(self):
        tracker = TruckTracker()
        truck = _truck_det(10, 10, 100, 100)
        person = _person_det(200, 200, 300, 300)  # no overlap
        decision = tracker.update(FrameAnalysis(trucks=[truck], persons=[person]))
        assert len(decision.classify_rois) == 0

    def test_action_stability_filter(self):
        tracker = TruckTracker(stability_min_count=3)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        # First two: not yet stable
        assert tracker.feed_action(tid, "action1") == ""
        assert tracker.feed_action(tid, "action1") == ""
        # Third: now stable
        assert tracker.feed_action(tid, "action1") == "action1"

    def test_action_flicker_filtered(self):
        tracker = TruckTracker(stability_min_count=3)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        tracker.feed_action(tid, "action1")
        tracker.feed_action(tid, "action2")  # flicker
        tracker.feed_action(tid, "action1")
        tracker.feed_action(tid, "action1")
        # action1 appeared 3 times, action2 only once
        assert tracker.get_track(tid).stable_action == "action1"

    def test_confirmed_actions_accumulate(self):
        tracker = TruckTracker(stability_min_count=2)
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
        tracker = TruckTracker(stability_min_count=2)
        tracker.update(FrameAnalysis(trucks=[_truck_det()]))
        tid = list(tracker.get_all_tracks().keys())[0]

        tracker.feed_action(tid, "other")
        tracker.feed_action(tid, "other")
        tracker.feed_action(tid, "other")

        track = tracker.get_track(tid)
        assert "other" not in track.confirmed_actions
        assert track.stable_action == "other"

    def test_missing_actions_in_visit(self):
        required = {"action1", "action2", "action3"}
        tracker = TruckTracker(
            stability_min_count=2,
            required_actions=required,
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

    def test_roi_filter_excludes_outside_trucks(self):
        roi = [[0, 0], [50, 0], [50, 50], [0, 50]]
        tracker = TruckTracker(roi=roi)
        # Truck centred at (55, 55) → outside ROI
        decision = tracker.update(
            FrameAnalysis(trucks=[_truck_det(50, 50, 60, 60)])
        )
        assert len(tracker.get_all_tracks()) == 0

    def test_roi_filter_includes_inside_trucks(self):
        roi = [[0, 0], [100, 0], [100, 100], [0, 100]]
        tracker = TruckTracker(roi=roi)
        decision = tracker.update(
            FrameAnalysis(trucks=[_truck_det(10, 10, 40, 40)])
        )
        assert len(tracker.get_all_tracks()) == 1

    def test_feed_ocr_unknown_track_noop(self):
        tracker = TruckTracker()
        tracker.feed_ocr(999, "XYZ", 0.9)  # should not raise

    def test_feed_action_unknown_track_returns_empty(self):
        tracker = TruckTracker()
        assert tracker.feed_action(999, "action1") == ""

    def test_multiple_trucks_tracked_independently(self):
        tracker = TruckTracker()
        t1 = _truck_det(10, 10, 50, 50)
        t2 = _truck_det(200, 200, 300, 300)
        tracker.update(FrameAnalysis(trucks=[t1, t2]))
        assert len(tracker.get_all_tracks()) == 2

        # Remove t1
        decision = tracker.update(FrameAnalysis(trucks=[t2]))
        assert len(tracker.get_all_tracks()) == 1
        assert len(decision.visits) == 1

    def test_visits_property_accumulates(self):
        tracker = TruckTracker()
        tracker.update(FrameAnalysis(trucks=[_truck_det(10, 10, 50, 50)]))
        tracker.update(FrameAnalysis())  # truck leaves → visit 1
        tracker.update(FrameAnalysis(trucks=[_truck_det(200, 200, 300, 300)]))
        tracker.update(FrameAnalysis())  # truck 2 leaves → visit 2
        assert len(tracker.visits) == 2


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
