from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from backend.db.database import get_source, list_sources
from backend.models.schemas import ProcessorStatus
from backend.processing.agent import AnalysisAgent
from backend.processing.example import ExampleProcessor

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager


class ProcessorManager:
    """Manages the lifecycle of all running video processors.

    Processors are keyed by ``source_id``. Each is an asyncio Task.
    An ``AnalysisAgent`` aggregates results from all processors.
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
        self._processors: dict[str, ExampleProcessor] = {}
        self._lock = asyncio.Lock()
        self._agent = AnalysisAgent(ws_manager=ws_manager)

    async def start_agent(self) -> None:
        """Start the analysis agent (called once during app startup)."""
        await self._agent.start()

    async def stop_agent(self) -> None:
        """Stop the analysis agent (called during shutdown)."""
        await self._agent.stop()

    async def start_processor(self, source_id: str) -> dict:
        """Start a processor for the given source_id.

        Returns a status dict. Raises ``ValueError`` if source not found.
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

            processor = ExampleProcessor(
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
            logger.info("ProcessorManager: started processor for {}", source_id)
            return {
                "status": "started",
                "source_id": source_id,
                "source_name": source.name,
            }

    async def stop_processor(self, source_id: str) -> dict:
        """Stop the processor for the given source_id."""
        async with self._lock:
            proc = self._processors.pop(source_id, None)
            if proc is None:
                return {"status": "not_running", "source_id": source_id}
            await proc.stop()
            logger.info("ProcessorManager: stopped processor for {}", source_id)
            return {"status": "stopped", "source_id": source_id}

    async def start_all_processors(self) -> dict:
        """Start processors for all configured video sources."""
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
        """Stop all currently running processors."""
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
        """Stop all running processors (called during shutdown)."""
        await self.stop_all_processors()
        logger.info("ProcessorManager: all processors stopped")

    def get_all_status(self) -> list[ProcessorStatus]:
        """Return status of all currently tracked processors."""
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
