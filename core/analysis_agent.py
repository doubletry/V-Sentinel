"""Reusable analysis-agent template for processor result aggregation.
可复用的分析代理模板，用于聚合处理器结果。

The backend-specific agent can inherit this class and add:
* message-model adaptation
* database persistence
* scene-specific daily summaries

后台专用 agent 可继承此类，并在其上增加：
* 消息模型适配
* 数据库存储
* 场景相关的每日总结
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from core.base_processor import AnalysisResult


class BaseAnalysisAgent:
    """Generic analysis-agent template shared across scenarios.
    通用分析代理模板，可跨场景复用。

    Responsibilities / 职责：
    * forward per-frame messages immediately
    * queue raw frame results for periodic aggregation
    * emit a generic cross-source summary message every N seconds

    Subclasses can override hooks to add scene-specific behaviour without
    reimplementing the lifecycle or queueing logic.
    子类可通过覆写钩子添加场景逻辑，而无需重复实现生命周期或队列逻辑。
    """

    def __init__(self, broadcaster: Any, summary_interval: float = 10.0) -> None:
        self._broadcaster = broadcaster
        self._interval = summary_interval
        self._queue: asyncio.Queue[tuple[str, str, AnalysisResult]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the periodic aggregation loop.
        启动周期聚合循环。"""
        if self._task is not None and not self._task.done():
            logger.warning("Analysis agent already running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._aggregate_loop(), name=self.__class__.__name__.lower()
        )
        logger.info(
            "{} started (interval={}s)", self.__class__.__name__, self._interval
        )

    async def stop(self) -> None:
        """Stop the aggregation loop gracefully.
        优雅停止聚合循环。"""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        logger.info("{} stopped", self.__class__.__name__)

    async def submit(
        self,
        source_id: str,
        source_name: str,
        result: AnalysisResult,
    ) -> None:
        """Submit a per-frame analysis result.
        提交逐帧分析结果。

        The default behaviour is:
        1. forward per-frame messages immediately
        2. run a scenario hook for extra handling
        3. enqueue the raw result for periodic summary aggregation
        默认行为：
        1. 立即转发逐帧消息
        2. 运行场景扩展钩子
        3. 将原始结果入队，等待周期性汇总
        """
        for message in result.messages:
            await self._broadcast(self.normalize_message(message))

        await self.handle_result_extras(source_id, source_name, result)
        await self._queue.put((source_id, source_name, result))

    async def handle_result_extras(
        self,
        source_id: str,
        source_name: str,
        result: AnalysisResult,
    ) -> None:
        """Scenario hook for extra per-result side effects.
        场景钩子：用于附加的逐结果副作用处理。"""
        del source_id, source_name, result

    def normalize_message(self, message: Any) -> Any:
        """Normalize message objects before broadcasting.
        广播前规范化消息对象。

        Core keeps this generic and returns the original object. Backend
        subclasses can adapt plain dicts into framework-specific models.
        core 保持该逻辑通用，直接返回原对象；backend 子类可将 dict 转为
        框架特定的消息模型。
        """
        return message

    async def _broadcast(self, message: Any) -> None:
        """Send a normalized message through the configured broadcaster.
        通过配置的 broadcaster 发送规范化后的消息。"""
        await self._broadcaster.broadcast(message)

    async def _aggregate_loop(self) -> None:
        """Drain queued results periodically and emit a summary message.
        周期性清空队列并发送汇总消息。"""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(self._interval)

                items: list[tuple[str, str, AnalysisResult]] = []
                while not self._queue.empty():
                    try:
                        items.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if not items:
                    continue

                summary = self._build_summary(items)
                if summary is not None:
                    await self._broadcast(self.normalize_message(summary))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("{} aggregation error: {}", self.__class__.__name__, exc)

    @classmethod
    def _build_summary(
        cls,
        items: list[tuple[str, str, AnalysisResult]],
    ) -> dict[str, Any] | None:
        """Build a generic cross-source summary payload.
        构建通用的跨视频源汇总载荷。"""
        payload = cls._build_summary_payload(items)
        return payload

    @staticmethod
    def _build_summary_payload(
        items: list[tuple[str, str, AnalysisResult]],
    ) -> dict[str, Any] | None:
        """Build the summary payload as a plain dict.
        以普通字典形式构建汇总载荷。"""
        if not items:
            return None

        per_source: dict[str, dict[str, Any]] = defaultdict(
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

        parts: list[str] = []
        total_detections = 0
        total_frames = 0
        for info in per_source.values():
            total_detections += int(info["detections"])
            total_frames += int(info["frames"])
            labels_str = ", ".join(sorted(info["labels"])) if info["labels"] else "none"
            parts.append(
                f"[{info['name']}] {info['frames']} frames, "
                f"{info['detections']} detections ({labels_str}), "
                f"{info['ocr_texts']} OCR texts"
            )

        if total_detections > 50:
            level = "alert"
        elif total_detections > 20:
            level = "warning"
        else:
            level = "info"

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_name": "[Agent]",
            "source_id": "__agent__",
            "level": level,
            "message": (
                f"Summary ({len(per_source)} source(s), {total_frames} total frames): "
                + " | ".join(parts)
            ),
        }