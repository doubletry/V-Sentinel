"""Tests for the AnalysisAgent (aggregator)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.api.ws import WSManager
from backend.models.schemas import AnalysisMessage
from backend.processing.agent import AnalysisAgent
from backend.processing.base import AnalysisResult


class TestAnalysisAgentLifecycle:
    async def test_start_stop(self):
        ws = WSManager()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=1.0)
        await agent.start()
        assert agent._task is not None
        assert not agent._task.done()
        await agent.stop()

    async def test_double_stop(self):
        ws = WSManager()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=1.0)
        await agent.start()
        await agent.stop()
        await agent.stop()  # Should not raise


class TestAnalysisAgentSubmit:
    async def test_submit_forwards_messages(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=60.0)

        msg = AnalysisMessage(
            timestamp="2024-01-01T00:00:00Z",
            source_name="cam1",
            source_id="s1",
            level="info",
            message="Detected 1 object",
        )
        result = AnalysisResult(messages=[msg])
        await agent.submit("s1", "cam1", result)

        # Individual message should be forwarded immediately
        ws.broadcast.assert_awaited_once_with(msg)

    async def test_submit_queues_result(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=60.0)

        result = AnalysisResult(detections=[{"label": "car"}])
        await agent.submit("s1", "cam1", result)

        assert not agent._queue.empty()

    async def test_submit_with_no_messages(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()
        agent = AnalysisAgent(ws_manager=ws, summary_interval=60.0)

        result = AnalysisResult()
        await agent.submit("s1", "cam1", result)

        # No broadcast for individual messages
        ws.broadcast.assert_not_awaited()
        # But result should still be queued
        assert not agent._queue.empty()


class TestAnalysisAgentBuildSummary:
    def test_empty_items(self):
        summary = AnalysisAgent._build_summary([])
        assert summary is None

    def test_single_source(self):
        result = AnalysisResult(
            detections=[{"label": "person"}, {"label": "car"}],
            ocr_texts=[{"text": "ABC123"}],
        )
        summary = AnalysisAgent._build_summary([("s1", "Camera 1", result)])
        assert summary is not None
        assert summary.source_id == "__agent__"
        assert summary.source_name == "[Agent]"
        assert "Camera 1" in summary.message
        assert "2 detections" in summary.message
        assert "1 OCR texts" in summary.message
        assert summary.level == "info"

    def test_multiple_sources(self):
        r1 = AnalysisResult(detections=[{"label": "person"}])
        r2 = AnalysisResult(detections=[{"label": "car"}], ocr_texts=[{"text": "X"}])
        items = [("s1", "Cam1", r1), ("s2", "Cam2", r2)]
        summary = AnalysisAgent._build_summary(items)
        assert summary is not None
        assert "2 source(s)" in summary.message
        assert "Cam1" in summary.message
        assert "Cam2" in summary.message

    def test_warning_level(self):
        """Many detections should trigger warning level."""
        dets = [{"label": f"obj{i}"} for i in range(25)]
        result = AnalysisResult(detections=dets)
        summary = AnalysisAgent._build_summary([("s1", "cam", result)])
        assert summary is not None
        assert summary.level == "warning"

    def test_labels_collected(self):
        result = AnalysisResult(
            detections=[{"label": "dog"}, {"label": "cat"}, {"label": "dog"}]
        )
        summary = AnalysisAgent._build_summary([("s1", "cam", result)])
        assert summary is not None
        assert "cat" in summary.message
        assert "dog" in summary.message


class TestAnalysisAgentAggregation:
    async def test_aggregation_broadcasts_summary(self):
        ws = WSManager()
        ws.broadcast = AsyncMock()

        # Use a very short interval for testing
        agent = AnalysisAgent(ws_manager=ws, summary_interval=0.2)
        await agent.start()

        # Submit some results
        r1 = AnalysisResult(detections=[{"label": "person"}])
        r2 = AnalysisResult(detections=[{"label": "car"}])
        await agent.submit("s1", "Cam1", r1)
        await agent.submit("s2", "Cam2", r2)

        # Wait for the aggregation cycle
        await asyncio.sleep(0.5)

        await agent.stop()

        # Should have broadcast a summary (the individual submits had no messages)
        calls = ws.broadcast.call_args_list
        # Find the agent summary broadcast
        summaries = [
            c for c in calls
            if isinstance(c[0][0], AnalysisMessage) and c[0][0].source_id == "__agent__"
        ]
        assert len(summaries) >= 1
        summary_msg = summaries[0][0][0]
        assert "Cam1" in summary_msg.message
        assert "Cam2" in summary_msg.message
