from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from backend.db.database import get_source
from backend.models.schemas import ProcessorStatus
from backend.processing.example import ExampleProcessor

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager
    from backend.config import Settings


class ProcessorManager:
    """Manages the lifecycle of all running video processors.

    Processors are keyed by ``source_id``. Each is an asyncio Task.
    """

    def __init__(
        self,
        vengine_client: "AsyncVEngineClient",
        ws_manager: "WSManager",
        config: "Settings",
    ) -> None:
        self._vengine = vengine_client
        self._ws_manager = ws_manager
        self._config = config
        self._processors: dict[str, ExampleProcessor] = {}
        self._lock = asyncio.Lock()

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
                config=self._config,
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

    async def stop_all(self) -> None:
        """Stop all running processors (called during shutdown)."""
        async with self._lock:
            source_ids = list(self._processors.keys())

        await asyncio.gather(
            *[self.stop_processor(sid) for sid in source_ids],
            return_exceptions=True,
        )
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
