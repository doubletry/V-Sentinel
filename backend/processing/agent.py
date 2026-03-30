"""Analysis Agent — aggregates results from all camera processors.
分析代理 — 汇总所有摄像头处理器的结果。

Architecture:
- Each ``BaseVideoProcessor`` submits per-frame ``AnalysisResult`` into the
  agent's async queue via ``submit()``.
- A background task (``_aggregate_loop``) wakes every *interval* seconds,
  collects all queued results, and produces a cross-camera summary.
- Summaries are broadcast to the frontend via ``WSManager``.
- Individual per-camera messages are forwarded immediately.

架构：
- 每个 ``BaseVideoProcessor`` 通过 ``submit()`` 将逐帧 ``AnalysisResult`` 提交到代理的异步队列。
- 后台任务（``_aggregate_loop``）每隔 *interval* 秒唤醒，收集所有排队结果并生成跨摄像头汇总。
- 汇总通过 ``WSManager`` 广播到前端。
- 单个摄像头的消息立即转发。
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
    中央聚合器，收集所有处理器的分析结果并生成定期跨摄像头汇总报告。

    Parameters
    ----------
    ws_manager : WSManager
        WebSocket manager for broadcasting messages to the frontend.
        用于向前端广播消息的 WebSocket 管理器。
    summary_interval : float
        Seconds between summary aggregation cycles (default 10).
        汇总聚合周期间隔秒数（默认 10）。
    """

    def __init__(
        self,
        ws_manager: "WSManager",
        summary_interval: float = 10.0,
    ) -> None:
        self._ws_manager = ws_manager
        self._interval = summary_interval

        # Queue for incoming per-frame results from processors (unbounded)
        # 来自处理器的逐帧结果的入队队列（无界）
        self._queue: asyncio.Queue[tuple[str, str, AnalysisResult]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # ── Lifecycle / 生命周期 ──────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background aggregation loop.
        启动后台聚合循环。"""
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._aggregate_loop(), name="analysis-agent"
        )
        logger.info("AnalysisAgent started (interval={}s)", self._interval)

    async def stop(self) -> None:
        """Stop the aggregation loop gracefully.
        优雅地停止聚合循环。"""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        logger.info("AnalysisAgent stopped")

    # ── Submit from processors / 处理器提交 ──────────────────────────────

    async def submit(
        self,
        source_id: str,
        source_name: str,
        result: AnalysisResult,
    ) -> None:
        """Submit a per-frame analysis result.
        提交逐帧分析结果。

        Called by each ``BaseVideoProcessor`` after ``process_frame``.
        Individual messages are forwarded immediately; the raw result
        is queued for periodic aggregation.
        由每个 ``BaseVideoProcessor`` 在 ``process_frame`` 后调用。
        单个消息立即转发；原始结果排队等待定期聚合。
        """
        # Forward individual messages immediately / 立即转发单个消息
        for msg in result.messages:
            await self._ws_manager.broadcast(msg)

        # Queue result for aggregation (unbounded queue, always succeeds)
        # 将结果加入聚合队列（无界队列，始终成功）
        await self._queue.put((source_id, source_name, result))

    # ── Aggregation Loop / 聚合循环 ──────────────────────────────────────

    async def _aggregate_loop(self) -> None:
        """Periodically drain the queue, aggregate, and broadcast summary.
        定期清空队列、聚合数据并广播汇总。"""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(self._interval)

                # Drain all queued results / 排空所有排队结果
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

    # ── Summary Builder / 汇总构建器 ────────────────────────────────────

    @staticmethod
    def _build_summary(
        items: list[tuple[str, str, AnalysisResult]],
    ) -> AnalysisMessage | None:
        """Build a cross-camera summary message from queued results.
        从排队结果构建跨摄像头汇总消息。"""
        if not items:
            return None

        # Group by source / 按源分组
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

        # Build summary text / 构建汇总文本
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

        # Determine alert level / 确定告警级别
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
