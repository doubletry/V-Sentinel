from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from backend.db.database import get_source, list_sources
from backend.models.schemas import ProcessorStatus
from backend.processing.truck.agent import AnalysisAgent
from backend.processing.base import BaseVideoProcessor
from backend.processing.registry import resolve_processor_class

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager


class ProcessorManager:
    """Manages the lifecycle of all running video processors.
    管理所有运行中视频处理器的生命周期。

    Processors are keyed by ``source_id``. Each is an asyncio Task.
    An ``AnalysisAgent`` aggregates results from all processors.
    处理器以 ``source_id`` 为键。每个都是一个 asyncio 任务。
    ``AnalysisAgent`` 汇总所有处理器的结果。
    """

    def __init__(
        self,
        vengine_client: "AsyncVEngineClient",
        ws_manager: "WSManager",
        app_settings: dict[str, str],
    ) -> None:
        self._vengine = vengine_client
        self._ws_manager = ws_manager
        self._app_settings = app_settings
        self._processors: dict[str, BaseVideoProcessor] = {}
        self._lock = asyncio.Lock()
        self._agent = AnalysisAgent(ws_manager=ws_manager)

    async def start_agent(self) -> None:
        """Start the analysis agent (called once during app startup).
        启动分析代理（应用启动时调用一次）。"""
        await self._agent.start()

    async def stop_agent(self) -> None:
        """Stop the analysis agent (called during shutdown).
        停止分析代理（关闭时调用）。"""
        await self._agent.stop()

    async def start_processor(self, source_id: str) -> dict:
        """Start a processor for the given source_id.
        为指定的 source_id 启动处理器。

        Returns a status dict. Raises ``ValueError`` if source not found.
        返回状态字典。如果未找到视频源则抛出 ``ValueError``。
        """
        async with self._lock:
            if source_id in self._processors:
                proc = self._processors[source_id]
                if proc.status == "running":
                    return {
                        "status": "already_running",
                        "source_id": source_id,
                    }

            source = await get_source(source_id)
            if source is None:
                raise ValueError(f"Source not found: {source_id}")

            plugin_name = self._app_settings.get("processor_plugin", "truck")
            processor_cls = resolve_processor_class(plugin_name)

            processor = processor_cls(
                source_id=source.id,
                source_name=source.name,
                rtsp_url=source.rtsp_url,
                rois=source.rois,
                vengine_client=self._vengine,
                ws_manager=self._ws_manager,
                app_settings=self._app_settings,
                agent=self._agent,
            )
            await processor.start()
            self._processors[source_id] = processor
            logger.info(
                "ProcessorManager: started {} processor for {}",
                plugin_name,
                source_id,
            )
            return {
                "status": "started",
                "source_id": source_id,
                "source_name": source.name,
                "processor_plugin": plugin_name,
            }

    async def stop_processor(self, source_id: str) -> dict:
        """Stop the processor for the given source_id.
        停止指定 source_id 的处理器。"""
        async with self._lock:
            proc = self._processors.pop(source_id, None)
            if proc is None:
                return {"status": "not_running", "source_id": source_id}
            await proc.stop()
            logger.info("ProcessorManager: stopped processor for {}", source_id)
            return {"status": "stopped", "source_id": source_id}

    async def start_all_processors(self) -> dict:
        """Start processors for all configured video sources.
        为所有已配置的视频源启动处理器。"""
        sources = await list_sources()
        if not sources:
            return {
                "status": "no_sources",
                "total": 0,
                "started": 0,
                "already_running": 0,
                "failed": [],
            }

        started = 0
        already_running = 0
        failed: list[dict[str, str]] = []

        for source in sources:
            try:
                result = await self.start_processor(source.id)
                if result["status"] == "started":
                    started += 1
                elif result["status"] == "already_running":
                    already_running += 1
            except Exception as exc:
                failed.append({"source_id": source.id, "reason": str(exc)})

        return {
            "status": "started_all" if not failed else "partial",
            "total": len(sources),
            "started": started,
            "already_running": already_running,
            "failed": failed,
        }

    async def stop_all_processors(self) -> dict:
        """Stop all currently running processors.
        停止所有当前运行中的处理器。"""
        async with self._lock:
            source_ids = list(self._processors.keys())

        if not source_ids:
            return {"status": "not_running", "stopped": 0}

        stopped = 0
        failed: list[dict[str, str]] = []
        for source_id in source_ids:
            try:
                result = await self.stop_processor(source_id)
                if result["status"] == "stopped":
                    stopped += 1
            except Exception as exc:
                failed.append({"source_id": source_id, "reason": str(exc)})

        return {
            "status": "stopped_all" if not failed else "partial",
            "stopped": stopped,
            "failed": failed,
        }

    async def stop_all(self) -> None:
        """Stop all running processors (called during shutdown).
        停止所有运行中的处理器（关闭时调用）。"""
        await self.stop_all_processors()
        logger.info("ProcessorManager: all processors stopped")

    def get_all_status(self) -> list[ProcessorStatus]:
        """Return status of all currently tracked processors.
        返回所有当前跟踪的处理器状态。"""
        statuses: list[ProcessorStatus] = []
        for source_id, proc in self._processors.items():
            statuses.append(
                ProcessorStatus(
                    source_id=source_id,
                    source_name=proc.source_name,
                    rtsp_url=proc.rtsp_url,
                    status=proc.status,
                    started_at=proc.started_at,
                )
            )
        return statuses
