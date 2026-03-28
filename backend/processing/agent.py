"""Analysis Agent — aggregates results from all camera processors.

Architecture:
- Each ``BaseVideoProcessor`` submits per-frame ``AnalysisResult`` into the
  agent's async queue via ``submit()``.
- A background task (``_aggregate_loop``) wakes every *interval* seconds,
  collects all queued results, and produces a cross-camera summary.
- Summaries are broadcast to the frontend via ``WSManager``.
- Individual per-camera messages are forwarded immediately.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger

from backend.models.schemas import AnalysisMessage
from backend.processing.base import AnalysisResult

if TYPE_CHECKING:
    from backend.api.ws import WSManager


class AnalysisAgent:
    """Central aggregator that collects analysis results from all processors
    and produces periodic cross-camera summary reports.

    Parameters
    ----------
    ws_manager : WSManager
        WebSocket manager for broadcasting messages to the frontend.
    summary_interval : float
        Seconds between summary aggregation cycles (default 10).
    """

    def __init__(
        self,
        ws_manager: "WSManager",
        summary_interval: float = 10.0,
    ) -> None:
        self._ws_manager = ws_manager
        self._interval = summary_interval

        # Queue for incoming per-frame results from processors (unbounded)
        self._queue: asyncio.Queue[tuple[str, str, AnalysisResult]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background aggregation loop."""
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._aggregate_loop(), name="analysis-agent"
        )
        logger.info("AnalysisAgent started (interval={}s)", self._interval)

    async def stop(self) -> None:
        """Stop the aggregation loop gracefully."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        logger.info("AnalysisAgent stopped")

    # ── Submit from processors ────────────────────────────────────────────

    async def submit(
        self,
        source_id: str,
        source_name: str,
        result: AnalysisResult,
    ) -> None:
        """Submit a per-frame analysis result.

        Called by each ``BaseVideoProcessor`` after ``process_frame``.
        Individual messages are forwarded immediately; the raw result
        is queued for periodic aggregation.
        """
        # Forward individual messages immediately
        for msg in result.messages:
            await self._ws_manager.broadcast(msg)

        # Queue result for aggregation (unbounded queue, always succeeds)
        await self._queue.put((source_id, source_name, result))

    # ── Aggregation Loop ──────────────────────────────────────────────────

    async def _aggregate_loop(self) -> None:
        """Periodically drain the queue, aggregate, and broadcast summary."""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(self._interval)

                # Drain all queued results
                items: list[tuple[str, str, AnalysisResult]] = []
                while not self._queue.empty():
                    try:
                        items.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if not items:
                    continue

                summary = self._build_summary(items)
                if summary:
                    await self._ws_manager.broadcast(summary)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("AnalysisAgent aggregation error: {}", exc)

    # ── Summary Builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        items: list[tuple[str, str, AnalysisResult]],
    ) -> AnalysisMessage | None:
        """Build a cross-camera summary message from queued results."""
        if not items:
            return None

        # Group by source
        per_source: dict[str, dict] = defaultdict(
            lambda: {
                "name": "",
                "detections": 0,
                "ocr_texts": 0,
                "classifications": 0,
                "frames": 0,
                "labels": set(),
            }
        )

        for source_id, source_name, result in items:
            info = per_source[source_id]
            info["name"] = source_name
            info["frames"] += 1
            info["detections"] += len(result.detections)
            info["ocr_texts"] += len(result.ocr_texts)
            info["classifications"] += len(result.classifications)
            for det in result.detections:
                label = det.get("label", "")
                if label:
                    info["labels"].add(label)

        # Build summary text
        parts: list[str] = []
        total_detections = 0
        total_ocr = 0
        for source_id, info in per_source.items():
            total_detections += info["detections"]
            total_ocr += info["ocr_texts"]
            labels_str = ", ".join(sorted(info["labels"])) if info["labels"] else "none"
            parts.append(
                f"[{info['name']}] {info['frames']} frames, "
                f"{info['detections']} detections ({labels_str}), "
                f"{info['ocr_texts']} OCR texts"
            )

        # Determine alert level
        if total_detections > 50:
            level = "alert"
        elif total_detections > 20:
            level = "warning"
        else:
            level = "info"

        summary_text = (
            f"Summary ({len(per_source)} source(s), "
            f"{sum(i['frames'] for i in per_source.values())} total frames): "
            + " | ".join(parts)
        )

        return AnalysisMessage(
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_name="[Agent]",
            source_id="__agent__",
            level=level,
            message=summary_text,
        )
