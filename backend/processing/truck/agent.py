"""Backend truck-scene analysis agent.
backend truck 场景分析代理。

This subclass keeps backend-only integrations (message model adaptation and
database persistence) while the truck-scene summary orchestration lives in
``core.truck.agent.TruckAnalysisAgent``.
该子类仅保留 backend 特有集成（消息模型适配、数据库持久化），而
truck 场景总结编排下沉到 ``core.truck.agent.TruckAnalysisAgent``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.db.database import get_vehicle_visits_since, save_vehicle_visit
from backend.models.schemas import AnalysisMessage
from core.truck.agent import TruckAnalysisAgent

if TYPE_CHECKING:
    from backend.api.ws import WSManager
    from core.email_client import AsyncEmailClient


class AnalysisAgent(TruckAnalysisAgent):
    """Backend-specific truck analysis agent.
    backend 专用 truck 分析代理。"""

    def __init__(
        self,
        ws_manager: "WSManager",
        email_client: "AsyncEmailClient | None" = None,
        summary_interval: float = 10.0,
    ) -> None:
        async def _persist_visit(
            source_id: str,
            source_name: str,
            visit: dict[str, str],
        ) -> None:
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

        async def _load_visits_since(since_iso: str) -> list[dict[str, str]]:
            return await get_vehicle_visits_since(since_iso)

        async def _load_app_settings() -> dict[str, str]:
            from backend.db.database import get_all_settings

            return await get_all_settings()

        async def _send_daily_summary_email(
            summary_text: str,
            until_iso: str,
            visits: list[dict[str, str]],
        ) -> None:
            from backend.db.database import get_all_settings

            app_settings = await get_all_settings()
            await email_client.send_daily_summary_email(
                app_settings=app_settings,
                summary_text=summary_text,
                until_iso=until_iso,
                visits=visits,
            )

        def _message_factory(message: object) -> AnalysisMessage:
            if isinstance(message, AnalysisMessage):
                return message
            if isinstance(message, dict):
                return AnalysisMessage(**message)
            raise TypeError(f"Unsupported message type: {type(message)!r}")

        super().__init__(
            broadcaster=ws_manager,
            summary_interval=summary_interval,
            message_factory=_message_factory,
            persist_visit=_persist_visit,
            load_visits_since=_load_visits_since,
            load_app_settings=_load_app_settings,
            send_daily_summary_email=(
                _send_daily_summary_email if email_client is not None else None
            ),
        )
