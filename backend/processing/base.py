"""Backend-specific video processor — extends core.BaseVideoProcessor.
后台专用视频处理器 — 扩展 core.BaseVideoProcessor。

This module re-exports ``AnalysisResult`` from the core package and provides
``BaseVideoProcessor`` which adds backend-only integration:
  * ``WSManager`` for WebSocket broadcast
  * ``AnalysisAgent`` for cross-camera aggregation
  * ``started_at`` timestamp tracking

All shared processing logic (lifecycle, frame reading, RTSP push, drawing,
ROI normalisation) lives in ``core.base_processor`` — **the single source
of truth**.  Updating core automatically updates the backend.
所有共享的处理逻辑（生命周期、帧读取、RTSP 推流、绘制、ROI 归一化）
位于 ``core.base_processor`` — **唯一的代码来源**。
更新 core 即自动更新后台。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

# Re-export core classes so existing imports from backend.processing.base
# continue to work without changes.
# 重导出 core 类，使现有的 backend.processing.base 导入无需修改。
from core.base_processor import AnalysisResult  # noqa: F401
from core.base_processor import BaseVideoProcessor as _CoreBaseVideoProcessor

from backend.models.schemas import ROI

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager
    from backend.processing.agent import AnalysisAgent


class BaseVideoProcessor(_CoreBaseVideoProcessor):
    """Backend-aware video processor that extends the core base class.
    扩展 core 基类的后台感知视频处理器。

    Adds:
    * ``ws_manager``  — WebSocket broadcast for real-time messages
    * ``agent``       — Cross-camera aggregation agent
    * ``started_at``  — ISO timestamp when processing started
    * ``_run_loop``   — Overridden to route results through agent/broadcast

    All other behaviour (frame reading, RTSP push, drawing, ROI handling)
    is inherited from ``core.base_processor.BaseVideoProcessor``.
    所有其他行为（帧读取、RTSP 推流、绘制、ROI 处理）
    继承自 ``core.base_processor.BaseVideoProcessor``。
    """

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
        # Convert Pydantic ROI objects to core ROI dataclasses
        # 将 Pydantic ROI 对象转换为 core ROI 数据类
        from core.base_processor import ROI as CoreROI, ROIPoint as CoreROIPoint
        core_rois = [
            CoreROI(
                id=r.id,
                type=r.type,
                points=[CoreROIPoint(x=p.x, y=p.y) for p in r.points],
                tag=r.tag,
            )
            for r in rois
        ]
        super().__init__(
            source_id=source_id,
            source_name=source_name,
            rtsp_url=rtsp_url,
            rois=core_rois,
            vengine_client=vengine_client,
            app_settings=app_settings,
        )
        self.ws_manager = ws_manager
        self.agent = agent
        self.started_at: str | None = None

    # ── Lifecycle overrides / 生命周期重写 ──────────────────────────────────

    async def start(self) -> None:
        """Start the processing task with timestamp tracking.
        启动处理任务并记录时间戳。"""
        if self._task is not None and not self._task.done():
            logger.warning("Processor for {} is already running", self.source_id)
            return
        self._stop_event.clear()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.status = "running"
        self._task = asyncio.create_task(
            self._run_loop(), name=f"processor-{self.source_id}"
        )
        logger.info("Started processor for source {}", self.source_id)

    async def stop(self) -> None:
        """Stop the processing task gracefully.
        优雅停止处理任务。"""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        # Close the persistent RTSP push container / 关闭持久 RTSP 推流容器
        self._close_push_container()
        self.status = "stopped"
        logger.info("Stopped processor for source {}", self.source_id)

    # ── Main Loop (with agent/broadcast integration) / 主循环（含代理/广播集成）

    async def _run_loop(self) -> None:
        """Main processing loop with agent aggregation and WebSocket broadcast.
        包含代理聚合和 WebSocket 广播的主处理循环。"""
        loop = asyncio.get_running_loop()
        reader_task = loop.run_in_executor(None, self._frame_reader, loop)

        try:
            while not self._stop_event.is_set():
                try:
                    item = await asyncio.wait_for(
                        self._frame_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    logger.info("Frame reader finished for {}", self.source_id)
                    break

                frame, encoded = item
                h, w = frame.shape[:2]
                shape = (h, w, frame.shape[2] if frame.ndim == 3 else 1)

                # Convert ROI points from normalized to pixel coordinates
                # 将 ROI 点从归一化坐标转换为像素坐标
                roi_pixel_points = self._normalize_rois_to_pixels(w, h)

                try:
                    result = await self.process_frame(
                        frame=frame,
                        encoded=encoded,
                        shape=shape,
                        roi_pixel_points=roi_pixel_points,
                    )
                except Exception as exc:
                    logger.error(
                        "process_frame error for {}: {}", self.source_id, exc
                    )
                    result = AnalysisResult()

                # Route results through agent (aggregator) or broadcast directly
                # 通过代理（聚合器）路由结果，或直接广播
                if self.agent is not None:
                    await self.agent.submit(
                        self.source_id, self.source_name, result
                    )
                else:
                    for msg in result.messages:
                        await self.ws_manager.broadcast(msg)

                # Push annotated frame back to MediaMTX
                # 将标注帧推回 MediaMTX
                if result.annotated_frame is not None:
                    output_path = f"{self._stream_key()}_processed"
                    await asyncio.to_thread(
                        self._push_frame, result.annotated_frame, output_path
                    )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Processor run_loop error for {}: {}", self.source_id, exc)
            self.status = "error"
        finally:
            self._stop_event.set()
            reader_task.cancel()
            logger.debug("run_loop exited for {}", self.source_id)
