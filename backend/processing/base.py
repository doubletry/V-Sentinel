from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from loguru import logger

from backend.models.schemas import AnalysisMessage, ROI

OPTIONS = {
    "analyzeduration": "10000000",  # 设置analyzeduration选项为10秒
    "probesize": "5000000",  # 设置probesize选项为5000000字节
    "rtsp_transport": "udp",  # 设置RTSP传输协议, 可以是"tcp"或"udp"
    "max_delay": "10",  # 设置最大延迟
    "stimeout": "1000000",  # 设置超时时间, 单位是微秒
    # "buffer_size": "设置缓冲区大小, 单位是字节。",
    # "allowed_media_types": '设置允许的媒体类型, 例如["audio", "video"]',
    # "muxdelay": "设置最大复用延迟。",
    # "probesize2": "设置探测大小。",
}

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager
    from backend.processing.agent import AnalysisAgent


@dataclass
class AnalysisResult:
    """Result from a single frame processing pass."""

    detections: list[dict] = field(default_factory=list)
    classifications: list[dict] = field(default_factory=list)
    ocr_texts: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    messages: list[AnalysisMessage] = field(default_factory=list)
    annotated_frame: np.ndarray | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BaseVideoProcessor(ABC):
    """Abstract base class for video stream processors.

    Subclass this and implement ``process_frame`` to add custom AI logic.

    Architecture:
    - A background thread (via ``asyncio.to_thread``) reads RTSP frames
      using PyAV and puts JPEG-encoded frames into an asyncio.Queue.
    - The asyncio event loop calls ``process_frame`` for each frame,
      which may ``await`` any number of gRPC calls concurrently.
    - Annotated frames are pushed back to MediaMTX in a thread pool.
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
        self.source_id = source_id
        self.source_name = source_name
        self.rtsp_url = rtsp_url
        self.rois = rois
        self.vengine = vengine_client
        self.ws_manager = ws_manager
        self.app_settings = app_settings
        self.agent = agent

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._frame_queue: asyncio.Queue[tuple[np.ndarray, bytes] | None] = (
            asyncio.Queue(maxsize=2)
        )
        self.started_at: str | None = None
        self.status: str = "stopped"

        # Persistent RTSP output state (managed by _push_frame / _close_push_container)
        self._push_lock = threading.Lock()
        self._push_container = None  # av.container.OutputContainer | None
        self._push_stream = None     # av.stream.Stream | None
        self._push_path: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the processing task."""
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
        """Stop the processing task gracefully."""
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        # Close the persistent RTSP push container
        self._close_push_container()
        self.status = "stopped"
        logger.info("Stopped processor for source {}", self.source_id)

    # ── Main Loop ──────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main processing loop: pull frames → process → push results."""
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
                    # Signal from reader that stream ended
                    logger.info("Frame reader finished for {}", self.source_id)
                    break

                frame, encoded = item
                h, w = frame.shape[:2]
                shape = (h, w, frame.shape[2] if frame.ndim == 3 else 1)

                # Convert ROI points from normalized to pixel coordinates
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
                if self.agent is not None:
                    await self.agent.submit(
                        self.source_id, self.source_name, result
                    )
                else:
                    # Fallback: broadcast messages directly
                    for msg in result.messages:
                        await self.ws_manager.broadcast(msg)

                # Push annotated frame back to MediaMTX
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
            # Cancel the reader thread
            self._stop_event.set()
            reader_task.cancel()
            logger.debug("run_loop exited for {}", self.source_id)

    # ── Frame Reader (runs in thread) ─────────────────────────────────────

    def _frame_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        """Read frames from RTSP stream using PyAV (blocking I/O, runs in thread).

        Parameters
        ----------
        loop:
            The running asyncio event loop (passed from ``_run_loop`` so we
            don't need to call ``asyncio.get_event_loop()`` inside a worker
            thread which would raise ``RuntimeError`` on Python 3.10+).
        """
        import av
        from turbojpeg import TurboJPEG

        jpeg = TurboJPEG()

        logger.info("Frame reader thread started for {}", self.rtsp_url)
        try:
            container = av.open(
                self.rtsp_url,
                options=OPTIONS,
            )
            video_stream = container.streams.video[0]

            for packet in container.demux(video_stream):
                if self._stop_event.is_set():
                    break
                for av_frame in packet.decode():
                    if self._stop_event.is_set():
                        break
                    # Convert to numpy RGB → BGR for TurboJPEG
                    rgb = av_frame.to_ndarray(format="rgb24")
                    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                    encoded = jpeg.encode(bgr, quality=85)

                    # Put into queue with backpressure: drop old frame if full
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
            # Signal end of stream
            try:
                loop.call_soon_threadsafe(self._frame_queue.put_nowait, None)
            except Exception:
                pass
            logger.info("Frame reader thread exited for {}", self.rtsp_url)

    # ── Abstract Method ────────────────────────────────────────────────────

    @abstractmethod
    async def process_frame(
        self,
        frame: np.ndarray,
        encoded: bytes,
        shape: tuple[int, int, int],
        roi_pixel_points: list[list[dict]],
    ) -> AnalysisResult:
        """Process a single frame. Subclass implements custom AI logic."""
        ...

    # ── Drawing & Pushing ─────────────────────────────────────────────────

    def draw_on_frame(
        self,
        frame: np.ndarray,
        result: AnalysisResult,
    ) -> np.ndarray:
        """Default drawing implementation — draws detections and OCR on frame."""
        out = frame.copy()
        for det in result.detections:
            x1, y1 = int(det.get("x_min", 0)), int(det.get("y_min", 0))
            x2, y2 = int(det.get("x_max", 0)), int(det.get("y_max", 0))
            label = det.get("label", "")
            conf = det.get("confidence", 0.0)
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                out,
                f"{label} {conf:.2f}",
                (x1, max(y1 - 5, 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
        for text_block in result.ocr_texts:
            pts = text_block.get("points", [])
            if pts:
                poly = np.array([[int(p["x"]), int(p["y"])] for p in pts], np.int32)
                cv2.polylines(out, [poly], True, (255, 0, 0), 2)
                cv2.putText(
                    out,
                    text_block.get("text", ""),
                    (poly[0][0], max(poly[0][1] - 5, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 0, 0),
                    1,
                    cv2.LINE_AA,
                )
        return out

    def _push_frame(self, frame: np.ndarray, output_rtsp_path: str) -> None:
        """Push annotated frame to MediaMTX via a persistent RTSP connection.

        The RTSP container and stream are kept open across calls so that
        continuous video is published instead of one-frame-per-connection.
        Thread-safe via ``_push_lock``.
        """
        import av

        with self._push_lock:
            try:
                # Lazily open the RTSP output container (or reopen if path changed)
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
                logger.debug("Frame push error for {}: {}", output_rtsp_path, exc)
                # Connection broken – close so next call re-opens
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

    # ── Utility ────────────────────────────────────────────────────────────

    def _stream_key(self) -> str:
        """Derive a MediaMTX stream key from the RTSP URL."""
        # e.g. rtsp://localhost:8554/camera1 → camera1
        return self.rtsp_url.rstrip("/").rsplit("/", 1)[-1]

    def _normalize_rois_to_pixels(
        self, width: int, height: int
    ) -> list[list[dict]]:
        """Convert normalized ROI points (0-1) to pixel coordinates."""
        result: list[list[dict]] = []
        for roi in self.rois:
            pts = [
                {"x": int(p.x * width), "y": int(p.y * height)}
                for p in roi.points
            ]
            result.append(pts)
        return result
