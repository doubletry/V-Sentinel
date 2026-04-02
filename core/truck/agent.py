"""Truck-scene analysis agent built on the reusable core template.
卡车场景分析代理，构建在可复用 core 模板之上。

This module keeps truck-scene summary logic in ``core`` while leaving backend-
specific integrations (message model adaptation, persistence, email delivery)
to subclasses.
本模块将 truck 场景总结逻辑保留在 ``core`` 中，而将 backend 特有集成
（消息模型适配、持久化、邮件发送）留给子类实现。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from core.analysis_agent import BaseAnalysisAgent
from core.base_processor import AnalysisResult
from core.truck.constants import DAILY_SUMMARY_HOUR, DAILY_SUMMARY_MINUTE, LABEL_EN_TO_ZH

MessageFactory = Callable[[Any], Any]
PersistVisitHook = Callable[[str, str, dict[str, Any]], Awaitable[None]]
LoadVisitsHook = Callable[[str], Awaitable[list[dict[str, Any]]]]
SendDailySummaryEmailHook = Callable[[str, str], Awaitable[None]]
LoadAppSettingsHook = Callable[[], Awaitable[dict[str, str]]]


class TruckAnalysisAgent(BaseAnalysisAgent):
    """Truck-scene analysis agent with daily-summary orchestration.
    truck 场景分析代理，包含每日总结调度。"""

    def __init__(
        self,
        broadcaster: Any,
        summary_interval: float = 10.0,
        *,
        message_factory: MessageFactory | None = None,
        persist_visit: PersistVisitHook | None = None,
        load_visits_since: LoadVisitsHook | None = None,
        send_daily_summary_email: SendDailySummaryEmailHook | None = None,
        load_app_settings: LoadAppSettingsHook | None = None,
    ) -> None:
        super().__init__(broadcaster=broadcaster, summary_interval=summary_interval)
        self._daily_task: asyncio.Task | None = None
        self._last_summary_time: str = datetime.now(timezone.utc).isoformat()
        self._message_factory_hook = message_factory
        self._persist_visit_hook = persist_visit
        self._load_visits_since_hook = load_visits_since
        self._send_daily_summary_email_hook = send_daily_summary_email
        self._load_app_settings_hook = load_app_settings

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
                await asyncio.wait_for(self._daily_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        await super().stop()

    async def handle_result_extras(
        self,
        source_id: str,
        source_name: str,
        result: AnalysisResult,
    ) -> None:
        """Persist truck-scene visit records through subclass hook.
        通过子类钩子持久化 truck 场景到访记录。"""
        for visit in result.extra.get("visits", []):
            try:
                await self.persist_visit(source_id, source_name, visit)
            except Exception as exc:
                logger.error("Failed to persist vehicle visit: {}", exc)

    def normalize_message(self, message: Any) -> Any:
        """Normalize message objects for the configured broadcaster.
        为配置的 broadcaster 规范化消息对象。"""
        if self._message_factory_hook is None:
            return message
        return self._message_factory_hook(message)

    @classmethod
    def _build_summary(
        cls,
        _items: list[tuple[str, str, AnalysisResult]],
    ) -> None:
        """Suppress generic periodic summaries for truck scene.
        禁用 truck 场景的通用周期汇总消息。"""
        return None

    async def persist_visit(
        self,
        source_id: str,
        source_name: str,
        visit: dict[str, Any],
    ) -> None:
        """Scenario hook for visit persistence.
        场景钩子：持久化到访记录。"""
        if self._persist_visit_hook is None:
            return
        await self._persist_visit_hook(source_id, source_name, visit)

    async def load_vehicle_visits_since(self, since_iso: str) -> list[dict[str, Any]]:
        """Scenario hook for fetching persisted visit records.
        场景钩子：获取持久化的到访记录。"""
        if self._load_visits_since_hook is None:
            return []
        return await self._load_visits_since_hook(since_iso)

    async def send_daily_summary_email(self, summary_text: str, until_iso: str) -> None:
        """Scenario hook for sending the daily summary through email.
        场景钩子：通过邮件发送每日总结。"""
        if self._send_daily_summary_email_hook is None:
            return
        await self._send_daily_summary_email_hook(summary_text, until_iso)

    async def load_app_settings(self) -> dict[str, str]:
        """Scenario hook for fetching current app settings.
        场景钩子：获取当前应用设置。"""
        if self._load_app_settings_hook is None:
            return {}
        return await self._load_app_settings_hook()

    async def _get_daily_summary_target(self, now: datetime) -> datetime:
        """Return the next configured local send time.
        返回下一个配置的本地发送时间。"""
        settings = await self.load_app_settings()
        try:
            hour = min(
                23,
                max(0, int(settings.get("daily_summary_hour", str(DAILY_SUMMARY_HOUR)))),
            )
        except Exception:
            hour = DAILY_SUMMARY_HOUR
        try:
            minute = min(
                59,
                max(
                    0,
                    int(
                        settings.get(
                            "daily_summary_minute", str(DAILY_SUMMARY_MINUTE)
                        )
                    ),
                ),
            )
        except Exception:
            minute = DAILY_SUMMARY_MINUTE

        tz_name = self._normalize_timezone_name(settings.get("timezone"))
        tzinfo = self._get_zoneinfo(tz_name)
        local_now = now.astimezone(tzinfo)
        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < local_now:
            target += timedelta(days=1)
        return target.astimezone(timezone.utc)

    async def _daily_summary_loop(self) -> None:
        """Generate a daily Chinese summary at the configured local time.
        在配置的本地时间生成中文每日总结。"""
        try:
            while not self._stop_event.is_set():
                settings = await self.load_app_settings()
                tz_name = self._normalize_timezone_name(settings.get("timezone"))
                tzinfo = self._get_zoneinfo(tz_name)
                now = datetime.now(timezone.utc)
                target = await self._get_daily_summary_target(now)
                wait_secs = (target - now).total_seconds()
                logger.info(
                    "Daily summary scheduled at {} (in {:.0f}s)",
                    target.astimezone(tzinfo).strftime("%Y-%m-%d %H:%M"),
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
        app_settings = await self.load_app_settings()
        timezone_name = self._normalize_timezone_name(app_settings.get("timezone"))

        try:
            visits = await self.load_vehicle_visits_since(since)
        except Exception as exc:
            logger.error("Failed to query vehicle visits for daily summary: {}", exc)
            return

        summary_text = self._build_daily_summary_text(
            visits,
            since,
            now_iso,
            timezone_name=timezone_name,
        )
        await self._broadcast(
            self.normalize_message(
                {
                    "timestamp": now_iso,
                    "source_name": "[每日总结]",
                    "source_id": "__daily_summary__",
                    "level": "info",
                    "message": summary_text,
                }
            )
        )
        try:
            await self.send_daily_summary_email(summary_text, now_iso)
        except Exception as exc:
            logger.error("Failed to send daily summary email: {}", exc)
        logger.info("Daily summary broadcast: {} visit(s)", len(visits))

    @staticmethod
    def _translate_label(label: str) -> str:
        """Translate English labels to Chinese for summaries.
        将英文标签翻译为中文，用于总结。"""
        return LABEL_EN_TO_ZH.get(label, label)

    @classmethod
    def build_daily_summary_text(
        cls,
        visits: list[dict[str, Any]],
        since_iso: str,
        until_iso: str,
        timezone_name: str = "UTC",
    ) -> str:
        """Public wrapper for building a daily summary text.
        对外公开的每日总结文本构建入口。"""
        return cls._build_daily_summary_text(
            visits, since_iso, until_iso, timezone_name=timezone_name
        )

    @classmethod
    def _build_daily_summary_text(
        cls,
        visits: list[dict[str, Any]],
        since_iso: str,
        until_iso: str,
        timezone_name: str = "UTC",
    ) -> str:
        """Build a Chinese daily summary from persisted visit records.
        基于持久化到访记录构建中文每日总结。"""
        tzinfo = cls._get_zoneinfo(timezone_name)
        try:
            since_str = datetime.fromisoformat(since_iso).astimezone(tzinfo).strftime(
                "%Y-%m-%d %H:%M"
            )
        except Exception:
            since_str = since_iso

        try:
            until_str = datetime.fromisoformat(until_iso).astimezone(tzinfo).strftime(
                "%Y-%m-%d %H:%M"
            )
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
                enter_str = cls._format_visit_time(
                    visit.get("enter_time", ""), tzinfo=tzinfo
                )
                exit_str = cls._format_visit_time(
                    visit.get("exit_time", ""), tzinfo=tzinfo
                )
                parts.append(
                    (
                        f"  {index}. 车牌: {plate} | 到达时间: {enter_str} | "
                        f"离开时间: {exit_str} | 已确认动作: {confirmed_str} | "
                        f"缺少动作: {missing_str} | {status}"
                    )
                )

        return "\n".join(parts)

    @staticmethod
    def _format_visit_time(value: str, *, tzinfo: ZoneInfo) -> str:
        """Format a visit timestamp in the configured timezone.
        按配置时区格式化到访时间。"""
        try:
            return datetime.fromisoformat(value).astimezone(tzinfo).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception as exc:
            logger.debug("Failed to format visit timestamp {}: {}", value, exc)
            return value or "未知"

    @staticmethod
    def _normalize_timezone_name(value: Any) -> str:
        text = str(value or "").strip()
        return text or "UTC"

    @staticmethod
    def _get_zoneinfo(timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")
