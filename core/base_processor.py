"""Standalone BaseVideoProcessor for the core minimal package.

This module duplicates the essential parts of ``backend.processing.base`` so
that it can run without importing the full backend.  The public API stays
identical, allowing processors written against this module to be dropped
into the full V-Sentinel backend without any changes.
"""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from loguru import logger

try:
    from turbojpeg import TurboJPEG
    _jpeg = TurboJPEG()
except (ImportError, RuntimeError) as _exc:
    _jpeg = None
    import warnings
    warnings.warn(
        f"TurboJPEG unavailable ({_exc}), falling back to cv2.imencode",
        stacklevel=1,
    )

# PyAV RTSP reader options (identical to backend defaults)
RTSP_OPTIONS = {
    "analyzeduration": "10000000",
    "probesize": "5000000",
    "rtsp_transport": "udp",
    "max_delay": "10",
    "stimeout": "1000000",
}


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class ROIPoint:
    """A single normalized (0-1) ROI point."""
    x: float
    y: float


@dataclass
class ROI:
    """A region-of-interest with normalized points and a tag label."""
    id: str
    type: str  # "polygon" or "rectangle"
    points: list[ROIPoint] = field(default_factory=list)
    tag: str = ""


@dataclass
class AnalysisResult:
    """Result from a single frame processing pass."""
    detections: list[dict] = field(default_factory=list)
    classifications: list[dict] = field(default_factory=list)
    ocr_texts: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    annotated_frame: np.ndarray | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ── BaseVideoProcessor ───────────────────────────────────────────────────────


class BaseVideoProcessor(ABC):
    """Standalone base processor for independent development.

    The lifecycle is identical to the full backend version:
    * ``start()``  — begins reading RTSP frames and processing them.
    * ``stop()``   — gracefully shuts everything down.

    Subclass this and implement ``process_frame`` with your custom AI logic.
    """

    def __init__(
        self,
        source_id: str = "standalone",
        source_name: str = "standalone",
        rtsp_url: str = "",
        rois: list[ROI] | None = None,
        vengine_client: Any = None,
        app_settings: dict[str, str] | None = None,
    ) -> None:
        self.source_id = source_id
        self.source_name = source_name
        self.rtsp_url = rtsp_url
        self.rois: list[ROI] = rois or []
        self.vengine = vengine_client
        self.app_settings: dict[str, str] = app_settings or {}

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._frame_queue: asyncio.Queue[tuple[np.ndarray, bytes] | None] = (
            asyncio.Queue(maxsize=2)
        )
        self.status: str = "stopped"

        # Persistent RTSP push state
        self._push_lock = threading.Lock()
        self._push_container = None
        self._push_stream = None
        self._push_path: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the processing task."""
        if self._task is not None and not self._task.done():
            logger.warning("Processor already running for {}", self.source_id)
            return
        self._stop_event.clear()
        self.status = "running"
        self._task = asyncio.create_task(
            self._run_loop(), name=f"processor-{self.source_id}"
        )
        logger.info("Started processor for {}", self.source_id)

    async def stop(self) -> None:
        """Stop the processing task gracefully."""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._close_push_container()
        self.status = "stopped"
        logger.info("Stopped processor for {}", self.source_id)

    # ── Main Loop ──────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
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
                roi_pixel_points = self._normalize_rois_to_pixels(w, h)

                try:
                    result = await self.process_frame(
                        frame=frame,
                        encoded=encoded,
                        shape=shape,
                        roi_pixel_points=roi_pixel_points,
                    )
                except Exception as exc:
                    logger.error("process_frame error: {}", exc)
                    result = AnalysisResult()

                # Push annotated frame back to RTSP if available
                if result.annotated_frame is not None:
                    output_path = f"{self._stream_key()}_processed"
                    await asyncio.to_thread(
                        self._push_frame, result.annotated_frame, output_path
                    )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("run_loop error for {}: {}", self.source_id, exc)
            self.status = "error"
        finally:
            self._stop_event.set()
            reader_task.cancel()

    # ── Frame Reader (runs in thread) ─────────────────────────────────────

    def _frame_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        """Read frames from RTSP stream using PyAV (blocking I/O, runs in thread)."""
        import av

        logger.info("Frame reader started for {}", self.rtsp_url)
        try:
            container = av.open(self.rtsp_url, options=RTSP_OPTIONS)
            video_stream = container.streams.video[0]

            for packet in container.demux(video_stream):
                if self._stop_event.is_set():
                    break
                for av_frame in packet.decode():
                    if self._stop_event.is_set():
                        break
                    rgb = av_frame.to_ndarray(format="rgb24")

                    # Encode using TurboJPEG if available, else cv2
                    if _jpeg is not None:
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        encoded = _jpeg.encode(bgr, quality=85)
                    else:
                        ok, buf = cv2.imencode(
                            ".jpg", rgb, [cv2.IMWRITE_JPEG_QUALITY, 85]
                        )
                        encoded = buf.tobytes() if ok else b""

                    if self._frame_queue.full():
                        try:
                            self._frame_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        loop.call_soon_threadsafe(
                            self._frame_queue.put_nowait, (rgb, encoded)
                        )
                    except asyncio.QueueFull:
                        pass
        except Exception as exc:
            if not self._stop_event.is_set():
                logger.exception("Frame reader error for {}: {}", self.rtsp_url, exc)
        finally:
            try:
                loop.call_soon_threadsafe(self._frame_queue.put_nowait, None)
            except Exception:
                pass
            logger.info("Frame reader exited for {}", self.rtsp_url)

    # ── Abstract method ───────────────────────────────────────────────────

    @abstractmethod
    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process a single frame. Implement your AI logic here."""
        ...

    # ── Drawing helpers ───────────────────────────────────────────────────

    def draw_on_frame(
        self, frame: np.ndarray, result: AnalysisResult
    ) -> np.ndarray:
        """Draw detections and OCR results on a frame copy."""
        out = frame.copy()
        for det in result.detections:
            x1, y1 = int(det.get("x_min", 0)), int(det.get("y_min", 0))
            x2, y2 = int(det.get("x_max", 0)), int(det.get("y_max", 0))
            label = det.get("label", "")
            conf = det.get("confidence", 0.0)
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                out, f"{label} {conf:.2f}", (x1, max(y1 - 5, 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA,
            )
        return out

    # ── RTSP Push (persistent) ────────────────────────────────────────────

    def _push_frame(self, frame: np.ndarray, output_rtsp_path: str) -> None:
        """Push annotated frame to MediaMTX via a persistent RTSP connection."""
        import av

        with self._push_lock:
            try:
                if self._push_container is None or self._push_path != output_rtsp_path:
                    self._close_push_container()
                    rtsp_url = (
                        f"{self.app_settings.get('mediamtx_rtsp_addr', 'rtsp://localhost:8554')}"
                        f"/{output_rtsp_path}"
                    )
                    container = av.open(rtsp_url, mode="w", format="rtsp")
                    stream = container.add_stream("h264", rate=25)
                    stream.width = frame.shape[1]
                    stream.height = frame.shape[0]
                    stream.pix_fmt = "yuv420p"
                    self._push_container = container
                    self._push_stream = stream
                    self._push_path = output_rtsp_path

                av_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
                av_frame = av_frame.reformat(format=self._push_stream.pix_fmt)
                for packet in self._push_stream.encode(av_frame):
                    self._push_container.mux(packet)
            except Exception as exc:
                logger.debug("Push error for {}: {}", output_rtsp_path, exc)
                self._close_push_container()

    def _close_push_container(self) -> None:
        """Flush and close the persistent RTSP output container."""
        if self._push_container is not None:
            try:
                if self._push_stream is not None:
                    for packet in self._push_stream.encode():
                        self._push_container.mux(packet)
                self._push_container.close()
            except Exception:
                pass
            self._push_container = None
            self._push_stream = None
            self._push_path = None

    # ── Utility ───────────────────────────────────────────────────────────

    def _stream_key(self) -> str:
        return self.rtsp_url.rstrip("/").rsplit("/", 1)[-1]

    def _normalize_rois_to_pixels(
        self, width: int, height: int
    ) -> list[list[dict]]:
        result: list[list[dict]] = []
        for roi in self.rois:
            pts = [
                {"x": int(p.x * width), "y": int(p.y * height)}
                for p in roi.points
            ]
            result.append(pts)
        return result
