from __future__ import annotations

from typing import TYPE_CHECKING

from backend.models.schemas import ROI
from backend.processing.base import BaseVideoProcessor
from core.example.processor import ExampleProcessor as _CoreExampleProcessor

if TYPE_CHECKING:
    from backend.api.ws import WSManager
    from backend.processing.truck.agent import AnalysisAgent
    from backend.vengine.client import AsyncVEngineClient


class ExampleProcessor(BaseVideoProcessor, _CoreExampleProcessor):
    """Backend adapter for the example scene plugin.
    example 场景插件的 backend 适配层。"""

    def __init__(
        self,
        source_id: str,
        source_name: str,
        rtsp_url: str,
        rois: list[ROI],
        vengine_client: "AsyncVEngineClient",
        ws_manager: "WSManager",
        app_settings: dict[str, str],
        agent: "AnalysisAgent | None" = None,
    ) -> None:
        super().__init__(
            source_id=source_id,
            source_name=source_name,
            rtsp_url=rtsp_url,
            rois=rois,
            vengine_client=vengine_client,
            ws_manager=ws_manager,
            app_settings=app_settings,
            agent=agent,
        )
