from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from loguru import logger

from backend.models.schemas import AnalysisMessage, ROI

if TYPE_CHECKING:
    from backend.vengine.client import AsyncVEngineClient
    from backend.api.ws import WSManager


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
    ) -> None:
        self.source_id = source_id
        self.source_name = source_name
        self.rtsp_url = rtsp_url
        self.rois = rois
        self.vengine = vengine_client
        self.ws_manager = ws_manager
        self.app_settings = app_settings

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._frame_queue: asyncio.Queue[tuple[np.ndarray, bytes] | None] = (
            asyncio.Queue(maxsize=2)
        )
        self.started_at: str | None = None
        self.status: str = "stopped"

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
        self.status = "stopped"
        logger.info("Stopped processor for source {}", self.source_id)

    # ── Main Loop ──────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main processing loop: pull frames → process → push results."""
        loop = asyncio.get_running_loop()
        reader_task = loop.run_in_executor(None, self._frame_reader)

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

                # Broadcast messages
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

    def _frame_reader(self) -> None:
        """Read frames from RTSP stream using PyAV (blocking I/O, runs in thread)."""
        import av

        logger.info("Frame reader thread started for {}", self.rtsp_url)
        try:
            container = av.open(
                self.rtsp_url,
                options={
                    "rtsp_transport": "tcp",
                    "stimeout": "5000000",
                },
            )
            video_stream = container.streams.video[0]
            video_stream.codec_context.skip_frame = "NONKEY"

            loop = asyncio.get_event_loop()

            for packet in container.demux(video_stream):
                if self._stop_event.is_set():
                    break
                for av_frame in packet.decode():
                    if self._stop_event.is_set():
                        break
                    # Convert to numpy BGR
                    bgr = av_frame.to_ndarray(format="bgr24")
                    # JPEG encode
                    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if not ok:
                        continue
                    encoded = buf.tobytes()

                    # Put into queue with backpressure: drop old frame if full
                    if self._frame_queue.full():
                        try:
                            self._frame_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        loop.call_soon_threadsafe(
                            self._frame_queue.put_nowait, (bgr, encoded)
                        )
                    except asyncio.QueueFull:
                        pass

        except Exception as exc:
            if not self._stop_event.is_set():
                logger.error("Frame reader error for {}: {}", self.rtsp_url, exc)
        finally:
            # Signal end of stream
            try:
                loop = asyncio.get_event_loop()
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
        """Push annotated frame to MediaMTX via RTSP (blocking, runs in thread)."""
        import av

        rtsp_url = f"{self.app_settings.get('mediamtx_rtsp_addr', 'rtsp://localhost:8554')}/{output_rtsp_path}"
        try:
            container = av.open(rtsp_url, mode="w", format="rtsp")
            stream = container.add_stream("h264", rate=25)
            stream.width = frame.shape[1]
            stream.height = frame.shape[0]
            stream.pix_fmt = "yuv420p"

            av_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
            av_frame = av_frame.reformat(format=stream.pix_fmt)
            for packet in stream.encode(av_frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
            container.close()
        except Exception as exc:
            logger.debug("Frame push error for {}: {}", output_rtsp_path, exc)

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
