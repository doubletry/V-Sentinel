"""Standalone runner for core processors.

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
2. Starts the asyncio event loop.
3. Reads frames from the input RTSP URL.
4. Calls ``process_frame`` for each frame.
5. Pushes annotated frames to the output RTSP stream on MediaMTX.
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
    vengine_client: object | None = None,
) -> None:
    """Run a processor as a standalone process.

    Parameters
    ----------
    processor_class:
        A subclass of ``BaseVideoProcessor``.
    rtsp_input:
        RTSP URL of the input video stream.
    source_id:
        Identifier for this source (used in logging and stream keys).
    source_name:
        Human-readable name.
    rois:
        Optional list of ROI dicts, each with ``type``, ``tag``, and
        ``points`` (list of ``{x, y}`` dicts with normalized 0-1 coords).
    mediamtx_rtsp_addr:
        Base RTSP address for pushing annotated output frames.
    vengine_host:
        Host for V-Engine gRPC services.
    detection_port / classification_port / ...:
        Per-service gRPC ports.
    vengine_client:
        Pre-built gRPC client instance (optional).  When not provided the
        processor's ``self.vengine`` will be ``None`` and gRPC calls inside
        ``process_frame`` should be guarded accordingly.
    """
    # Build ROI objects from dicts
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
    }

    processor = processor_class(
        source_id=source_id,
        source_name=source_name,
        rtsp_url=rtsp_input,
        rois=roi_objects,
        vengine_client=vengine_client,
        app_settings=app_settings,
    )

    async def _main() -> None:
        loop = asyncio.get_running_loop()

        # Graceful shutdown on SIGINT / SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.ensure_future(processor.stop())
            )

        logger.info(
            "Starting {} for input={}", processor_class.__name__, rtsp_input
        )
        await processor.start()

        # Wait until the processor finishes (stop event or stream end)
        while processor.status == "running":
            await asyncio.sleep(0.5)

        logger.info("Processor finished (status={})", processor.status)

    asyncio.run(_main())
