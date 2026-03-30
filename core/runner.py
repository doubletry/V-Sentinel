"""Standalone runner for core processors.
核心处理器的独立运行器。

Usage::

    from core.runner import run_processor
    from my_processor import MyProcessor

    run_processor(
        MyProcessor,
        rtsp_input="rtsp://localhost:8554/cam1",
        mediamtx_rtsp_addr="rtsp://localhost:8554",
    )

The runner:
1. Creates the processor with provided settings.
2. Optionally creates and connects an ``AsyncVEngineClient`` so your
   processor can call real V-Engine gRPC services.
3. Starts the asyncio event loop.
4. Reads frames from the input RTSP URL.
5. Calls ``process_frame`` for each frame.
6. Pushes annotated frames to the output RTSP stream on MediaMTX.

运行器：
1. 使用提供的设置创建处理器。
2. 可选地创建并连接 ``AsyncVEngineClient``，使处理器可调用真实的
   V-Engine gRPC 服务。
3. 启动 asyncio 事件循环。
4. 从输入 RTSP URL 读取帧。
5. 对每帧调用 ``process_frame``。
6. 将标注后的帧推送到 MediaMTX 上的输出 RTSP 流。
"""

from __future__ import annotations

import asyncio
import signal
from typing import Type

from loguru import logger

from core.base_processor import BaseVideoProcessor, ROI, ROIPoint


def run_processor(
    processor_class: Type[BaseVideoProcessor],
    *,
    rtsp_input: str,
    source_id: str = "standalone",
    source_name: str = "standalone",
    rois: list[dict] | None = None,
    mediamtx_rtsp_addr: str = "rtsp://localhost:8554",
    vengine_host: str = "localhost",
    detection_port: str = "50051",
    classification_port: str = "50052",
    action_port: str = "50053",
    ocr_port: str = "50054",
    upload_port: str = "50050",
    detection_enabled: str = "true",
    classification_enabled: str = "true",
    action_enabled: str = "true",
    ocr_enabled: str = "true",
    upload_enabled: str = "true",
    vengine_client: object | None = None,
    auto_connect_vengine: bool = True,
) -> None:
    """Run a processor as a standalone process.
    以独立进程方式运行处理器。

    Parameters
    ----------
    processor_class:
        A subclass of ``BaseVideoProcessor``.
        ``BaseVideoProcessor`` 的子类。
    rtsp_input:
        RTSP URL of the input video stream.
        输入视频流的 RTSP URL。
    source_id:
        Identifier for this source (used in logging and stream keys).
        此源的标识符（用于日志和流键）。
    source_name:
        Human-readable name.
        人类可读的名称。
    rois:
        Optional list of ROI dicts, each with ``type``, ``tag``, and
        ``points`` (list of ``{x, y}`` dicts with normalized 0-1 coords).
        可选的 ROI 字典列表，每个含 ``type``、``tag`` 和 ``points``
        （归一化 0-1 坐标的 ``{x, y}`` 字典列表）。
    mediamtx_rtsp_addr:
        Base RTSP address for pushing annotated output frames.
        用于推送标注输出帧的 RTSP 基地址。
    vengine_host:
        Host for V-Engine gRPC services.
        V-Engine gRPC 服务主机。
    detection_port / classification_port / ...:
        Per-service gRPC ports.
        各服务的 gRPC 端口。
    detection_enabled / classification_enabled / ...:
        Per-service enable flags ("true"/"false").
        各服务启用标志（"true"/"false"）。
    vengine_client:
        Pre-built gRPC client instance (optional).
        预构建的 gRPC 客户端实例（可选）。
    auto_connect_vengine:
        When ``True`` (default) and *vengine_client* is not provided,
        automatically create and connect an ``AsyncVEngineClient`` using
        the provided host/port settings so your processor can call real
        V-Engine gRPC services.
        当为 ``True``（默认）且未提供 *vengine_client* 时，
        自动创建并连接 ``AsyncVEngineClient``，
        使处理器可以调用真实的 V-Engine gRPC 服务。
    """
    # Build ROI objects from dicts / 从字典构建 ROI 对象
    roi_objects: list[ROI] = []
    for idx, roi_dict in enumerate(rois or []):
        points = [
            ROIPoint(x=float(p["x"]), y=float(p["y"]))
            for p in roi_dict.get("points", [])
        ]
        roi_objects.append(
            ROI(
                id=roi_dict.get("id", f"roi-{idx}"),
                type=roi_dict.get("type", "polygon"),
                points=points,
                tag=roi_dict.get("tag", ""),
            )
        )

    app_settings = {
        "mediamtx_rtsp_addr": mediamtx_rtsp_addr,
        "vengine_host": vengine_host,
        "detection_port": detection_port,
        "classification_port": classification_port,
        "action_port": action_port,
        "ocr_port": ocr_port,
        "upload_port": upload_port,
        "detection_enabled": detection_enabled,
        "classification_enabled": classification_enabled,
        "action_enabled": action_enabled,
        "ocr_enabled": ocr_enabled,
        "upload_enabled": upload_enabled,
    }

    async def _main() -> None:
        # Auto-create and connect the V-Engine client if not provided.
        # 若未提供，自动创建并连接 V-Engine 客户端。
        nonlocal vengine_client
        auto_created_client = None
        if vengine_client is None and auto_connect_vengine:
            from core.vengine_client import AsyncVEngineClient
            auto_created_client = AsyncVEngineClient()
            await auto_created_client.connect(app_settings)
            vengine_client = auto_created_client
            logger.info("Auto-created and connected AsyncVEngineClient")

        processor = processor_class(
            source_id=source_id,
            source_name=source_name,
            rtsp_url=rtsp_input,
            rois=roi_objects,
            vengine_client=vengine_client,
            app_settings=app_settings,
        )

        loop = asyncio.get_running_loop()

        # Graceful shutdown on SIGINT / SIGTERM / 收到 SIGINT / SIGTERM 时优雅关闭
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.ensure_future(processor.stop())
            )

        logger.info(
            "Starting {} for input={}", processor_class.__name__, rtsp_input
        )
        await processor.start()

        # Wait until the processor finishes (stop event or stream end)
        # 等待处理器完成（停止事件或流结束）
        while processor.status == "running":
            await asyncio.sleep(0.5)

        # Close auto-created client / 关闭自动创建的客户端
        if auto_created_client is not None:
            await auto_created_client.close()

        logger.info("Processor finished (status={})", processor.status)

    asyncio.run(_main())
