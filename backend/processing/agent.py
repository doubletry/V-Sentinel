"""Backend analysis agent built on the reusable core template.
基于可复用 core 模板构建的 backend 分析代理。

The generic queueing and periodic aggregation lifecycle now lives in
``core.analysis_agent.BaseAnalysisAgent``. This backend subclass only keeps
backend-specific concerns:
* adapting dict messages to ``AnalysisMessage``
* persisting vehicle-visit records
* generating Chinese daily summaries

通用的入队与周期聚合生命周期现已下沉到
``core.analysis_agent.BaseAnalysisAgent``。本 backend 子类仅保留
backend 特有职责：
* 将 dict 消息适配为 ``AnalysisMessage``
* 持久化车辆到访记录
* 生成中文每日总结
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.db.database import get_vehicle_visits_since, save_vehicle_visit
from backend.models.schemas import AnalysisMessage
from core.analysis_agent import BaseAnalysisAgent
from core.base_processor import AnalysisResult
from core.constants import DAILY_SUMMARY_HOUR, DAILY_SUMMARY_MINUTE, LABEL_EN_TO_ZH

if TYPE_CHECKING:
    from backend.api.ws import WSManager


class AnalysisAgent(BaseAnalysisAgent):
    """Backend-specific analysis agent.
    backend 专用分析代理。"""

    def __init__(
        self,
        ws_manager: "WSManager",
        summary_interval: float = 10.0,
    ) -> None:
        super().__init__(broadcaster=ws_manager, summary_interval=summary_interval)
        self._ws_manager = ws_manager
        self._daily_task: asyncio.Task | None = None
        self._last_summary_time: str = datetime.now(timezone.utc).isoformat()

    async def start(self) -> None:
        """Start periodic aggregation and the daily summary scheduler.
        启动周期聚合与每日总结调度。"""
        await super().start()
        if self._daily_task is not None and not self._daily_task.done():
            return
        self._daily_task = asyncio.create_task(
            self._daily_summary_loop(), name="daily-summary"
        )

    async def stop(self) -> None:
        """Stop periodic aggregation and the daily summary scheduler.
        停止周期聚合与每日总结调度。"""
        if self._daily_task is not None and not self._daily_task.done():
            self._daily_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._daily_task), timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        await super().stop()

    def normalize_message(self, message: Any) -> AnalysisMessage:
        """Convert dict-like messages into backend AnalysisMessage models.
        将 dict 类消息转换为 backend 的 AnalysisMessage 模型。"""
        if isinstance(message, AnalysisMessage):
            return message
        if isinstance(message, dict):
            return AnalysisMessage(**message)
        raise TypeError(f"Unsupported message type: {type(message)!r}")

    async def handle_result_extras(
        self,
        source_id: str,
        source_name: str,
        result: AnalysisResult,
    ) -> None:
        """Persist scene-specific vehicle-visit records.
        持久化场景相关的车辆到访记录。"""
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

    @classmethod
    def _build_summary(
        cls,
        items: list[tuple[str, str, AnalysisResult]],
    ) -> AnalysisMessage | None:
        """Build the generic periodic summary as AnalysisMessage.
        将通用周期汇总构建为 AnalysisMessage。"""
        payload = cls._build_summary_payload(items)
        if payload is None:
            return None
        return AnalysisMessage(**payload)

    async def _daily_summary_loop(self) -> None:
        """Generate a daily Chinese summary at the configured local time.
        在配置的本地时间生成中文每日总结。"""
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
        """Query persisted vehicle visits and broadcast a Chinese summary.
        查询持久化车辆到访记录并广播中文总结。"""
        since = self._last_summary_time
        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_summary_time = now_iso

        try:
            visits = await get_vehicle_visits_since(since)
        except Exception as exc:
            logger.error("Failed to query vehicle visits for daily summary: {}", exc)
            return

        summary_text = self._build_daily_summary_text(visits, since, now_iso)
        await self._broadcast(
            AnalysisMessage(
                timestamp=now_iso,
                source_name="[每日总结]",
                source_id="__daily_summary__",
                level="info",
                message=summary_text,
            )
        )
        logger.info("Daily summary broadcast: {} visit(s)", len(visits))

    @staticmethod
    def _translate_label(label: str) -> str:
        """Translate English labels to Chinese for summaries.
        将英文标签翻译为中文，用于总结。"""
        return LABEL_EN_TO_ZH.get(label, label)

    @classmethod
    def _build_daily_summary_text(
        cls,
        visits: list[dict[str, Any]],
        since_iso: str,
        until_iso: str,
    ) -> str:
        """Build a Chinese daily summary from persisted visit records.
        基于持久化到访记录构建中文每日总结。"""
        try:
            since_str = datetime.fromisoformat(since_iso).strftime("%Y-%m-%d %H:%M")
        except Exception:
            since_str = since_iso

        try:
            until_str = datetime.fromisoformat(until_iso).strftime("%Y-%m-%d %H:%M")
        except Exception:
            until_str = until_iso

        if not visits:
            return f"【每日总结】{since_str} ~ {until_str}：统计期间无车辆到访记录。"

        per_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for visit in visits:
            key = visit.get("source_name") or visit.get("source_id", "未知")
            per_source[key].append(visit)

        parts: list[str] = [
            f"【每日总结】{since_str} ~ {until_str}，共 {len(visits)} 辆车到访："
        ]
        for source_name, source_visits in per_source.items():
            parts.append(f"\n▸ 摄像头「{source_name}」：{len(source_visits)} 辆车")
            for index, visit in enumerate(source_visits, start=1):
                plate = visit.get("plate") or "未识别"
                confirmed = [
                    cls._translate_label(label)
                    for label in visit.get("confirmed_actions", [])
                ]
                missing = [
                    cls._translate_label(label)
                    for label in visit.get("missing_actions", [])
                ]
                confirmed_str = "、".join(confirmed) if confirmed else "无"
                missing_str = "、".join(missing) if missing else "无"
                status = "✅ 合规" if not missing else "⚠️ 缺少动作"
                parts.append(
                    f"  {index}. 车牌: {plate} | 已确认动作: {confirmed_str} | "
                    f"缺少动作: {missing_str} | {status}"
                )

        return "\n".join(parts)