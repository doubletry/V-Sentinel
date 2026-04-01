"""Analysis Agent — aggregates results from all camera processors.
分析代理 — 汇总所有摄像头处理器的结果。

Architecture:
- Each ``BaseVideoProcessor`` submits per-frame ``AnalysisResult`` into the
  agent's async queue via ``submit()``.
- A background task (``_aggregate_loop``) wakes every *interval* seconds,
  collects all queued results, and produces a cross-camera summary.
- Summaries are broadcast to the frontend via ``WSManager``.
- Individual per-camera messages are forwarded immediately.
- Vehicle visits are persisted to the database when vehicles leave.
- A daily summary task generates a Chinese-language summary at a configured
  time each day.

架构：
- 每个 ``BaseVideoProcessor`` 通过 ``submit()`` 将逐帧 ``AnalysisResult`` 提交到代理的异步队列。
- 后台任务（``_aggregate_loop``）每隔 *interval* 秒唤醒，收集所有排队结果并生成跨摄像头汇总。
- 汇总通过 ``WSManager`` 广播到前端。
- 单个摄像头的消息立即转发。
- 车辆离开时，到访记录持久化到数据库。
- 每日总结任务在配置的时间生成中文总结。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from loguru import logger

from backend.db.database import get_vehicle_visits_since, save_vehicle_visit
from backend.models.schemas import AnalysisMessage
from backend.processing.base import AnalysisResult
from core.constants import (
    DAILY_SUMMARY_HOUR,
    DAILY_SUMMARY_MINUTE,
    LABEL_EN_TO_ZH,
)

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
        self._daily_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        # ISO timestamp for the start of the current daily summary window
        # 当前每日总结窗口起始的 ISO 时间戳
        self._last_summary_time: str = datetime.now(timezone.utc).isoformat()

    # ── Lifecycle / 生命周期 ──────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background aggregation loop and daily summary scheduler.
        启动后台聚合循环和每日总结调度器。"""
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._aggregate_loop(), name="analysis-agent"
        )
        self._daily_task = asyncio.create_task(
            self._daily_summary_loop(), name="daily-summary"
        )
        logger.info("AnalysisAgent started (interval={}s)", self._interval)

    async def stop(self) -> None:
        """Stop the aggregation loop and daily summary gracefully.
        优雅地停止聚合循环和每日总结。"""
        self._stop_event.set()
        for task in (self._task, self._daily_task):
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
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
        Individual messages are forwarded immediately; vehicle visits are
        persisted to the database; the raw result is queued for periodic
        aggregation.
        由每个 ``BaseVideoProcessor`` 在 ``process_frame`` 后调用。
        单个消息立即转发；车辆到访记录持久化到数据库；原始结果排队等待定期聚合。
        """
        # Forward individual messages immediately / 立即转发单个消息
        for msg in result.messages:
            await self._ws_manager.broadcast(msg)

        # Persist vehicle visits if present / 如有车辆到访记录则持久化
        for visit in result.extra.get("visits", []):
            try:
                await save_vehicle_visit(
                    source_id=source_id,
                    source_name=source_name,
                    track_id=visit["track_id"],
                    enter_time=visit["enter_time"],
                    exit_time=visit["exit_time"],
                    plate=visit.get("plate", ""),
                    confirmed_actions=visit.get("confirmed_actions", []),
                    missing_actions=visit.get("missing_actions", []),
                )
            except Exception as exc:
                logger.error("Failed to save vehicle visit: {}", exc)

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

    # ── Daily Summary / 每日总结 ─────────────────────────────────────────

    async def _daily_summary_loop(self) -> None:
        """Sleep until the configured daily summary time, generate summary,
        then repeat.  Uses ``DAILY_SUMMARY_HOUR`` and ``DAILY_SUMMARY_MINUTE``
        from constants.
        休眠至配置的每日总结时间，生成总结，然后重复。
        使用 constants 中的 ``DAILY_SUMMARY_HOUR`` 和 ``DAILY_SUMMARY_MINUTE``。
        """
        try:
            while not self._stop_event.is_set():
                now = datetime.now()
                target = now.replace(
                    hour=DAILY_SUMMARY_HOUR,
                    minute=DAILY_SUMMARY_MINUTE,
                    second=0,
                    microsecond=0,
                )
                if target <= now:
                    target += timedelta(days=1)
                wait_secs = (target - now).total_seconds()
                logger.info(
                    "Daily summary scheduled at {} (in {:.0f}s)",
                    target.strftime("%Y-%m-%d %H:%M"),
                    wait_secs,
                )
                await asyncio.sleep(wait_secs)
                if self._stop_event.is_set():
                    break
                await self._generate_daily_summary()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Daily summary loop error: {}", exc)

    async def _generate_daily_summary(self) -> None:
        """Query vehicle visits since last summary and broadcast a Chinese
        summary message.
        查询上次总结以来的车辆到访记录并广播中文总结消息。
        """
        since = self._last_summary_time
        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_summary_time = now_iso

        try:
            visits = await get_vehicle_visits_since(since)
        except Exception as exc:
            logger.error("Failed to query vehicle visits for daily summary: {}", exc)
            return

        summary_text = self._build_daily_summary_text(visits, since, now_iso)
        msg = AnalysisMessage(
            timestamp=now_iso,
            source_name="[每日总结]",
            source_id="__daily_summary__",
            level="info",
            message=summary_text,
        )
        await self._ws_manager.broadcast(msg)
        logger.info("Daily summary broadcast: {} visit(s)", len(visits))

    @staticmethod
    def _translate_label(label: str) -> str:
        """Translate an English label to Chinese using the mapping table.
        使用对照表将英文标签翻译为中文。"""
        return LABEL_EN_TO_ZH.get(label, label)

    @classmethod
    def _build_daily_summary_text(
        cls,
        visits: list[dict],
        since_iso: str,
        until_iso: str,
    ) -> str:
        """Build a Chinese-language daily summary from visit records.
        从到访记录构建中文每日总结。"""
        # Parse time range for display
        try:
            since_dt = datetime.fromisoformat(since_iso)
            since_str = since_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            since_str = since_iso
        try:
            until_dt = datetime.fromisoformat(until_iso)
            until_str = until_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            until_str = until_iso

        if not visits:
            return f"【每日总结】{since_str} ~ {until_str}：统计期间无车辆到访记录。"

        # Group by source
        per_source: dict[str, list[dict]] = defaultdict(list)
        for v in visits:
            per_source[v.get("source_name") or v.get("source_id", "未知")].append(v)

        parts: list[str] = [
            f"【每日总结】{since_str} ~ {until_str}，"
            f"共 {len(visits)} 辆车到访："
        ]

        for source_name, source_visits in per_source.items():
            parts.append(f"\n▸ 摄像头「{source_name}」：{len(source_visits)} 辆车")
            for i, v in enumerate(source_visits, 1):
                plate = v.get("plate") or "未识别"
                confirmed = v.get("confirmed_actions", [])
                missing = v.get("missing_actions", [])
                confirmed_zh = [cls._translate_label(a) for a in confirmed]
                missing_zh = [cls._translate_label(a) for a in missing]
                confirmed_str = "、".join(confirmed_zh) if confirmed_zh else "无"
                missing_str = "、".join(missing_zh) if missing_zh else "无"

                status = "✅ 合规" if not missing else "⚠️ 缺少动作"
                parts.append(
                    f"  {i}. 车牌: {plate} | "
                    f"已确认动作: {confirmed_str} | "
                    f"缺少动作: {missing_str} | "
                    f"{status}"
                )

        return "\n".join(parts)
