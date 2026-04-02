"""Backend truck-scene analysis agent.
backend truck 场景分析代理。

This subclass keeps backend-only integrations (message model adaptation and
database persistence) while the truck-scene summary orchestration lives in
``core.truck.agent.TruckAnalysisAgent``.
该子类仅保留 backend 特有集成（消息模型适配、数据库持久化），而
truck 场景总结编排下沉到 ``core.truck.agent.TruckAnalysisAgent``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.db.database import get_vehicle_visits_since, save_vehicle_visit
from backend.models.schemas import AnalysisMessage
from core.truck.agent import TruckAnalysisAgent

if TYPE_CHECKING:
    from backend.api.ws import WSManager


class AnalysisAgent(TruckAnalysisAgent):
    """Backend-specific truck analysis agent.
    backend 专用 truck 分析代理。"""

    def __init__(
        self,
        ws_manager: "WSManager",
        summary_interval: float = 10.0,
    ) -> None:
        super().__init__(broadcaster=ws_manager, summary_interval=summary_interval)

    def normalize_message(self, message: Any) -> AnalysisMessage:
        """Convert dict-like messages into backend AnalysisMessage models.
        将 dict 类消息转换为 backend 的 AnalysisMessage 模型。"""
        if isinstance(message, AnalysisMessage):
            return message
        if isinstance(message, dict):
            return AnalysisMessage(**message)
        raise TypeError(f"Unsupported message type: {type(message)!r}")

    @classmethod
    def _build_summary(
        cls,
        items: list[tuple[str, str, Any]],
    ) -> AnalysisMessage | None:
        """Build the generic periodic summary as AnalysisMessage.
        将通用周期汇总构建为 AnalysisMessage。"""
        payload = cls._build_summary_payload(items)
        if payload is None:
            return None
        return AnalysisMessage(**payload)

    async def persist_visit(
        self,
        source_id: str,
        source_name: str,
        visit: dict[str, Any],
    ) -> None:
        """Persist truck-scene vehicle-visit records.
        持久化 truck 场景车辆到访记录。"""
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

    async def load_vehicle_visits_since(self, since_iso: str) -> list[dict[str, Any]]:
        """Load persisted truck-scene visit records for daily summary.
        加载用于每日总结的持久化 truck 场景到访记录。"""
        return await get_vehicle_visits_since(since_iso)
