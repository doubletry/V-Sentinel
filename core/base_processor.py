"""Standalone BaseVideoProcessor for the core minimal package.

This module duplicates the essential parts of ``backend.processing.base`` so
that it can run without importing the full backend.  The public API stays
identical, allowing processors written against this module to be dropped
into the full V-Sentinel backend without any changes.
"""

from __future__ import annotations

import asyncio
import base64
import queue
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Callable, cast
from urllib.parse import urlparse

import cv2
import numpy as np
from loguru import logger

from core.constants import (
    DRAW_CLASSIFICATION_COLOR,
    DRAW_DETECTION_COLOR,
    DRAW_FONT_SCALE,
    DRAW_FONT_THICKNESS,
    FRAME_SAMPLE_INTERVAL,
    PUSH_FPS,
    PUSH_PRESET,
    RTSP_MAX_RECONNECT_ATTEMPTS,
    RTSP_RECONNECT_DELAY,
    RTSP_TRANSPORT,
)

try:
    from turbojpeg import TurboJPEG, TJPF_RGB
    _jpeg = TurboJPEG()
except (ImportError, RuntimeError) as _exc:
    _jpeg = None
    TJPF_RGB = None  # type: ignore[assignment]
    import warnings
    warnings.warn(
        f"TurboJPEG unavailable ({_exc}), falling back to cv2.imencode",
        stacklevel=1,
    )


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
        self._processing_tasks: set[asyncio.Task] = set()
        self._max_inflight_frames = max(
            1, int(self.app_settings.get("max_inflight_frames", "3"))
        )
        self.status: str = "stopped"

        # Persistent RTSP push state (ffmpeg subprocess)
        # 持久化 RTSP 推流状态（ffmpeg 子进程）
        self._push_lock = threading.Lock()
        self._push_proc: subprocess.Popen | None = None
        self._push_path: str | None = None
        self._push_width: int = 0
        self._push_height: int = 0
        self._display_queue: queue.Queue[
            tuple[np.ndarray, AnalysisResult, str] | None
        ] = queue.Queue(maxsize=2)
        self._display_stop = threading.Event()
        self._display_thread: threading.Thread | None = None
        self._publish_stop = threading.Event()
        self._publish_thread: threading.Thread | None = None
        self._publish_state_lock = threading.Lock()
        self._publish_frame: np.ndarray | None = None
        self._publish_path: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the processing task."""
        if self._task is not None and not self._task.done():
            logger.warning("Processor already running for {}", self.source_id)
            return
        self._stop_event.clear()
        self._display_stop.clear()
        self._publish_stop.clear()
        self._start_display_worker()
        self._start_publish_worker()
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
        if self._processing_tasks:
            for task in list(self._processing_tasks):
                task.cancel()
            try:
                await asyncio.gather(*self._processing_tasks, return_exceptions=True)
            except Exception:
                pass
            self._processing_tasks.clear()
        self._stop_publish_worker()
        self._stop_display_worker()
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
                await self._wait_for_processing_slot()
                task = asyncio.create_task(
                    self._process_frame_item(frame, encoded),
                    name=f"process-frame-{self.source_id}",
                )
                self._processing_tasks.add(task)
                task.add_done_callback(self._processing_tasks.discard)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("run_loop error for {}: {}", self.source_id, exc)
            self.status = "error"
        finally:
            self._stop_event.set()
            reader_task.cancel()
            if self._processing_tasks:
                await asyncio.gather(
                    *list(self._processing_tasks), return_exceptions=True
                )
                self._processing_tasks.clear()
            self._stop_publish_worker()
            self._stop_display_worker()

    # ── Frame Reader (runs in thread) ─────────────────────────────────────

    def _frame_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        """Read frames from RTSP stream using ffmpeg subprocess (blocking I/O,
        runs in thread).  Automatically reconnects on stream failure.
        使用 ffmpeg 子进程从 RTSP 流读取帧（阻塞 I/O，在线程中运行）。
        流失败时自动重连。

        ffmpeg decodes the RTSP stream and outputs raw RGB24 pixels to stdout.
        Using TCP transport avoids the green-frame / mosaic artifacts caused by
        UDP packet loss.  Images are encoded once as RGB JPEG; downstream code
        reuses the encoded bytes without re-encoding.
        ffmpeg 解码 RTSP 流并将原始 RGB24 像素输出到 stdout。
        使用 TCP 传输避免 UDP 丢包导致的绿帧/马赛克。图像仅编码一次为 RGB JPEG；
        下游代码复用编码字节，无需重新编码。
        """
        import time as _time

        logger.info("Frame reader started for {}", self.rtsp_url)
        reconnect_attempts = 0
        max_attempts = RTSP_MAX_RECONNECT_ATTEMPTS  # 0 = unlimited
        frame_counter = 0  # for FRAME_SAMPLE_INTERVAL skipping

        while not self._stop_event.is_set():
            # Step 1 — probe stream dimensions
            probe_w, probe_h = 1920, 1080
            try:
                probe_cmd = [
                    "ffprobe",
                    "-v", "error",
                    "-rtsp_transport", RTSP_TRANSPORT,
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "csv=p=0:s=x",
                    self.rtsp_url,
                ]
                probe_out = subprocess.check_output(
                    probe_cmd, timeout=10, stderr=subprocess.DEVNULL
                ).decode().strip()
                if "x" in probe_out:
                    parts = probe_out.split("x")
                    probe_w, probe_h = int(parts[0]), int(parts[1])
            except Exception as exc:
                logger.warning(
                    "ffprobe failed for {} (using {}x{}): {}",
                    self.rtsp_url, probe_w, probe_h, exc,
                )

            probe_w -= probe_w % 2
            probe_h -= probe_h % 2
            frame_bytes = probe_w * probe_h * 3

            logger.info(
                "Frame reader: {}x{} ({} bytes/frame) for {}",
                probe_w, probe_h, frame_bytes, self.rtsp_url,
            )
            self._prewarm_display_stream(
                np.zeros((probe_h, probe_w, 3), dtype=np.uint8),
                self._display_output_path(),
            )

            # Step 2 — launch ffmpeg reader
            # Minimize buffering / probing so the first processed frame and the
            # prewarmed processed RTSP path come up with lower startup latency.
            # 降低缓冲和探测开销，使第一帧 processed 结果和预热 RTSP 路径更快上线。
            cmd = [
                "ffmpeg",
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-probesize", "32",
                "-analyzeduration", "0",
                "-rtsp_transport", RTSP_TRANSPORT,
                "-i", self.rtsp_url,
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "-s", f"{probe_w}x{probe_h}",
                "-an",
                "-sn",
                "-vf", f"scale={probe_w}:{probe_h}",
                "pipe:1",
            ]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                # Use unbuffered stdout so Python can incrementally consume
                # large rawvideo frames instead of waiting on a giant buffered
                # read, which delays processed-stream startup.
                # 使用无缓冲 stdout，避免大 rawvideo 帧在缓冲读中长期阻塞，
                # 从而拖慢 processed 流启动。
                bufsize=0,
            )

            stream_ok = False
            try:
                while not self._stop_event.is_set():
                    raw = self._read_exact(cast(BinaryIO, proc.stdout), frame_bytes)
                    if len(raw) != frame_bytes:
                        if not self._stop_event.is_set():
                            logger.warning(
                                "Frame reader got {} bytes (expected {}), stream may have ended",
                                len(raw), frame_bytes,
                            )
                        break

                    stream_ok = True
                    reconnect_attempts = 0  # reset on successful read

                    # Frame sampling: skip frames according to interval
                    # 帧采样：按间隔跳过帧
                    frame_counter += 1
                    if FRAME_SAMPLE_INTERVAL > 1 and (frame_counter % FRAME_SAMPLE_INTERVAL) != 0:
                        continue

                    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(
                        (probe_h, probe_w, 3)
                    )

                    if _jpeg is not None:
                        from turbojpeg import TJPF_RGB
                        encoded = _jpeg.encode(rgb, quality=85, pixel_format=TJPF_RGB)
                    else:
                        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                        ok, buf = cv2.imencode(
                            ".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85]
                        )
                        encoded = buf.tobytes() if ok else b""

                    loop.call_soon_threadsafe(
                        self._enqueue_frame_from_reader, rgb, encoded
                    )
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.exception("Frame reader error for {}: {}", self.rtsp_url, exc)
            finally:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

            # Reconnect logic
            if self._stop_event.is_set():
                break

            reconnect_attempts += 1
            if max_attempts > 0 and reconnect_attempts > max_attempts:
                logger.error(
                    "RTSP reconnect limit ({}) reached for {}",
                    max_attempts, self.rtsp_url,
                )
                break

            logger.warning(
                "RTSP stream lost for {}, reconnecting in {:.1f}s (attempt {}{})",
                self.rtsp_url,
                RTSP_RECONNECT_DELAY,
                reconnect_attempts,
                f"/{max_attempts}" if max_attempts > 0 else "",
            )
            _time.sleep(RTSP_RECONNECT_DELAY)

        # Send sentinel when reader fully exits
        try:
            loop.call_soon_threadsafe(self._enqueue_reader_sentinel)
        except Exception:
            pass
        logger.info("Frame reader exited for {}", self.rtsp_url)

    @staticmethod
    def _read_exact(
        stream: BinaryIO,
        expected_bytes: int,
        chunk_size: int = 65536,
    ) -> bytes:
        """Read exactly *expected_bytes* from a pipe unless EOF occurs.
        从管道中精确读取 *expected_bytes*，除非遇到 EOF。"""
        chunks: list[bytes] = []
        remaining = expected_bytes
        while remaining > 0:
            chunk = stream.read(min(chunk_size, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    # ── Abstract method ───────────────────────────────────────────────────

    def _enqueue_frame_from_reader(self, frame: np.ndarray, encoded: bytes) -> None:
        """Enqueue the latest decoded frame, dropping the oldest if needed."""
        if self._frame_queue.full():
            try:
                self._frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._frame_queue.put_nowait((frame, encoded))
        except asyncio.QueueFull:
            pass

    def _enqueue_reader_sentinel(self) -> None:
        """Enqueue the reader completion sentinel, dropping one frame if needed."""
        if self._frame_queue.full():
            try:
                self._frame_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._frame_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

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

    # ── Reusable inference helpers / 可复用推理辅助方法 ───────────────────

    @staticmethod
    def _bbox_to_roi_points(
        bbox: list[int] | tuple[int, int, int, int],
        width: int,
        height: int,
    ) -> list[dict[str, int]]:
        """Convert an [x1, y1, x2, y2] bbox to ROI polygon points.
        将 [x1, y1, x2, y2] 检测框转换为 ROI 多边形点。"""
        x1, y1, x2, y2 = bbox
        x1 = max(int(x1), 0)
        y1 = max(int(y1), 0)
        x2 = min(int(x2), width)
        y2 = min(int(y2), height)
        return [
            {"x": x1, "y": y1},
            {"x": x2, "y": y1},
            {"x": x2, "y": y2},
            {"x": x1, "y": y2},
        ]

    async def _do_detect(
        self,
        *,
        shape: tuple[int, ...],
        model_name: str,
        conf: float = 0.5,
        model_roi: list[dict] | None = None,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
        images: list[dict] | None = None,
        on_item: Callable[[dict], dict | None] | None = None,
    ) -> dict[str, list[dict]]:
        """Run reusable detection and optionally map each detection result.
        执行可复用检测，并可选地映射每个检测结果。"""
        if self.vengine is None:
            return {"detections": []}

        detect_kwargs: dict[str, object] = {
            "shape": shape,
            "model_name": model_name,
            "conf": conf,
        }
        if model_roi is not None:
            detect_kwargs["model_roi"] = model_roi
        if image_bytes is not None:
            detect_kwargs["image_bytes"] = image_bytes
        if image_key is not None:
            detect_kwargs["image_key"] = image_key
        if images is not None:
            detect_kwargs["images"] = images

        raw = await self.vengine.detect(**detect_kwargs)
        detections: list[dict] = []
        for item in raw:
            mapped = on_item(item) if on_item is not None else item
            if mapped is not None:
                detections.append(mapped)
        return {"detections": detections}

    async def _do_ocr(
        self,
        ocr_rois: list[dict],
        *,
        model_name: str,
        conf: float = 0.3,
        on_item: Callable[[dict], None] | None = None,
    ) -> dict[str, list[dict]]:
        """Run reusable batched OCR and optionally post-process each result.
        执行可复用的批量 OCR，并可选地对每个结果做后处理。"""
        if self.vengine is None or not ocr_rois:
            return {"ocr_texts": []}

        raw = await self.vengine.ocr(
            shape=None,
            model_name=model_name,
            conf=conf,
            images=ocr_rois,
        )
        ocr_texts: list[dict] = []
        for item in raw:
            if on_item is not None:
                on_item(item)
            ocr_texts.append(item)
        return {"ocr_texts": ocr_texts}

    async def _do_classify(
        self,
        cls_rois: list[dict],
        *,
        model_name: str,
        on_item: Callable[[dict], dict | None] | None = None,
    ) -> dict[str, list[dict]]:
        """Run reusable batched classification and map results if needed.
        执行可复用的批量分类，并在需要时映射结果。"""
        if self.vengine is None or not cls_rois:
            return {"classifications": []}

        raw = await self.vengine.classify(
            shape=None,
            model_name=model_name,
            images=cls_rois,
        )
        classifications: list[dict] = []
        for item in raw:
            mapped = on_item(item) if on_item is not None else item
            if mapped is not None:
                classifications.append(mapped)
        return {"classifications": classifications}

    def _encode_thumbnail(
        self, frame: np.ndarray | None, max_width: int = 320
    ) -> str | None:
        """Encode a frame as a base64 JPEG thumbnail (RGB channel order).
        将帧编码为 base64 JPEG 缩略图（RGB 通道顺序）。"""
        if frame is None:
            return None

        h, w = frame.shape[:2]
        if w > max_width:
            scale = max_width / w
            frame = cv2.resize(
                frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA
            )

        if _jpeg is not None:
            encoded = _jpeg.encode(frame, quality=60, pixel_format=TJPF_RGB)
        else:
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if not ok:
                return None
            encoded = buf.tobytes()
        return base64.b64encode(encoded).decode()

    # ── Drawing helpers ───────────────────────────────────────────────────

    def draw_on_frame(
        self, frame: np.ndarray, result: AnalysisResult
    ) -> np.ndarray:
        """Draw detections and per-person classification labels on a frame copy.
        在帧副本上绘制检测框和每个人的分类标签。

        Detection bounding boxes are drawn in green.  If ``result.classifications``
        contains entries with a ``person_bbox`` key, the classification label is
        rendered on the matching person's bounding box in yellow.  This allows
        each person to display their own action label rather than a generic
        detection label.
        检测框用绿色绘制。如果 ``result.classifications`` 中包含
        ``person_bbox`` 键的条目，分类标签会以黄色渲染在对应人的检测框上。
        这样每个人都能显示自己的动作标签，而非通用的检测标签。
        """
        out = frame.copy()

        # Index classification labels by person_bbox for fast lookup.
        # 按 person_bbox 索引分类标签以快速查找。
        cls_by_bbox: dict[tuple[int, int, int, int], dict] = {}
        for cls in result.classifications:
            pbbox = cls.get("person_bbox")
            if pbbox and len(pbbox) == 4:
                key = (int(pbbox[0]), int(pbbox[1]), int(pbbox[2]), int(pbbox[3]))
                cls_by_bbox[key] = cls

        for det in result.detections:
            x1, y1 = int(det.get("x_min", 0)), int(det.get("y_min", 0))
            x2, y2 = int(det.get("x_max", 0)), int(det.get("y_max", 0))
            det_label = det.get("label", "")
            conf = det.get("confidence", 0.0)

            # Check if this detection's bbox matches a classification result
            # (for person detections, show the action label instead).
            # 检查该检测框是否匹配分类结果（对行人检测，显示动作标签）。
            bbox_key = (x1, y1, x2, y2)
            cls_match = cls_by_bbox.get(bbox_key)

            if cls_match:
                # Person with classification — draw in classification color
                # with the action label.
                # 有分类结果的行人——用分类颜色绘制动作标签。
                stable = cls_match.get("stable_label", "")
                raw = cls_match.get("raw_label", "")
                display_label = stable or raw or det_label
                cls_conf = cls_match.get("confidence", conf)
                cv2.rectangle(out, (x1, y1), (x2, y2), DRAW_CLASSIFICATION_COLOR, 2)
                cv2.putText(
                    out,
                    f"{display_label} {cls_conf:.2f}",
                    (x1, max(y1 - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    DRAW_FONT_SCALE,
                    DRAW_CLASSIFICATION_COLOR,
                    DRAW_FONT_THICKNESS,
                    cv2.LINE_AA,
                )
            else:
                # Regular detection — draw in detection color.
                # 普通检测——用检测颜色绘制。
                cv2.rectangle(out, (x1, y1), (x2, y2), DRAW_DETECTION_COLOR, 2)
                cv2.putText(
                    out,
                    f"{det_label} {conf:.2f}",
                    (x1, max(y1 - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    DRAW_FONT_SCALE,
                    DRAW_DETECTION_COLOR,
                    DRAW_FONT_THICKNESS,
                    cv2.LINE_AA,
                )
        return out

    # ── RTSP Push (persistent) ────────────────────────────────────────────

    async def _wait_for_processing_slot(self) -> None:
        """Limit frame-level inference concurrency to keep latency bounded."""
        if len(self._processing_tasks) < self._max_inflight_frames:
            return
        done, _ = await asyncio.wait(
            self._processing_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            try:
                await task
            except BaseException:
                pass

    async def _process_frame_item(self, frame: np.ndarray, encoded: bytes) -> None:
        """Process one frame and hand off any display work asynchronously."""
        h, w = frame.shape[:2]
        shape = (h, w, frame.shape[2] if frame.ndim == 3 else 1)
        roi_pixel_points = self._normalize_rois_to_pixels(w, h)
        self._prewarm_display_stream(frame, self._display_output_path())

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

        await self._handle_result(frame, result)

    async def _handle_result(self, frame: np.ndarray, result: AnalysisResult) -> None:
        """Default per-result handling: enqueue for drawing/pushing if needed."""
        if self._should_display_result(result):
            output_path = self._display_output_path()
            self._enqueue_display(frame, result, output_path)

    def _should_display_result(self, result: AnalysisResult) -> bool:
        """Return whether a result should be drawn/pushed to the output stream."""
        del result
        return True

    def _start_display_worker(self) -> None:
        """Start the dedicated display worker thread if it is not running."""
        if self._display_thread is not None and self._display_thread.is_alive():
            return
        self._display_thread = threading.Thread(
            target=self._display_worker,
            name=f"display-{self.source_id}",
            daemon=True,
        )
        self._display_thread.start()

    def _stop_display_worker(self) -> None:
        """Signal the display worker to stop and wait briefly for exit."""
        self._display_stop.set()
        try:
            self._display_queue.put_nowait(None)
        except queue.Full:
            try:
                self._display_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._display_queue.put_nowait(None)
            except queue.Full:
                pass
        if self._display_thread is not None:
            self._display_thread.join(timeout=2.0)
            self._display_thread = None

    def _start_publish_worker(self) -> None:
        """Start the steady RTSP publisher thread if it is not running."""
        if self._publish_thread is not None and self._publish_thread.is_alive():
            return
        self._publish_thread = threading.Thread(
            target=self._publish_worker,
            name=f"publisher-{self.source_id}",
            daemon=True,
        )
        self._publish_thread.start()

    def _stop_publish_worker(self) -> None:
        """Stop the steady RTSP publisher thread."""
        self._publish_stop.set()
        if self._publish_thread is not None:
            self._publish_thread.join(timeout=2.0)
            self._publish_thread = None
        with self._publish_state_lock:
            self._publish_frame = None
            self._publish_path = None

    def _enqueue_display(
        self, frame: np.ndarray, result: AnalysisResult, output_rtsp_path: str
    ) -> None:
        """Queue a frame/result pair for the dedicated draw+push worker."""
        item = (frame, result, output_rtsp_path)
        try:
            self._display_queue.put_nowait(item)
        except queue.Full:
            try:
                self._display_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._display_queue.put_nowait(item)
            except queue.Full:
                pass

    def _display_worker(self) -> None:
        """Dedicated worker that draws result overlays and pushes frames."""
        while not self._display_stop.is_set():
            try:
                item = self._display_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            frame, result, output_rtsp_path = item
            display_frame = result.annotated_frame
            if display_frame is None:
                try:
                    display_frame = self.draw_on_frame(frame, result)
                except Exception as exc:
                    logger.debug("Display draw error for {}: {}", output_rtsp_path, exc)
                    continue
            self._set_publish_frame(display_frame, output_rtsp_path)

    def _display_output_path(self) -> str:
        """Return the RTSP output path used for processed frames.
        返回处理结果帧使用的 RTSP 输出路径。"""
        return f"{self._stream_path()}_processed"

    def _make_processing_overlay(self, frame: np.ndarray) -> np.ndarray:
        """Create a placeholder frame while inference is still warming up.
        在推理尚未返回时创建占位结果帧。"""
        out = frame.copy()
        cv2.putText(
            out,
            "Processing...",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            DRAW_DETECTION_COLOR,
            DRAW_FONT_THICKNESS,
            cv2.LINE_AA,
        )
        return out

    def _prewarm_display_stream(
        self, frame: np.ndarray, output_rtsp_path: str
    ) -> None:
        """Set a placeholder frame so the steady publisher can prewarm the path.
        设置占位帧，使恒定节奏发布线程可提前预热 processed 路径。"""
        self._set_publish_frame(self._make_processing_overlay(frame), output_rtsp_path)

    def _set_publish_frame(self, frame: np.ndarray, output_rtsp_path: str) -> None:
        """Update the latest frame that the steady publisher should stream.
        更新恒定节奏发布线程应持续输出的最新帧。"""
        frame = self._ensure_even_dims(frame)
        if frame.shape[0] == 0 or frame.shape[1] == 0:
            return
        with self._publish_state_lock:
            self._publish_frame = frame.copy()
            self._publish_path = output_rtsp_path

    def _publish_worker(self) -> None:
        """Publish the latest frame at a steady cadence to keep RTSP healthy.
        以稳定节奏重复推送最新帧，保持 RTSP 输出持续可解码。"""
        target_fps = PUSH_FPS
        if target_fps <= 0:
            logger.warning(
                "Invalid PUSH_FPS={} (must be > 0), falling back to 1",
                target_fps,
            )
            target_fps = 1
        frame_interval = 1.0 / target_fps
        next_deadline = time.monotonic()
        while not self._publish_stop.is_set():
            with self._publish_state_lock:
                frame = None if self._publish_frame is None else self._publish_frame.copy()
                path = self._publish_path
            if frame is not None and path:
                self._push_frame(frame, path)
            now = time.monotonic()
            next_deadline += frame_interval
            # Resync when we overrun the target cadence so the publisher does
            # not spin in a busy loop while still returning to a steady rate.
            # 当一次发布明显超期时重置节奏，避免发布线程进入忙等循环。
            if next_deadline < now:
                logger.debug(
                    "Publisher fell behind by {:.3f}s for {}",
                    now - next_deadline,
                    self.source_id,
                )
                next_deadline = now + frame_interval
            sleep_for = max(0.0, next_deadline - now)
            if self._publish_stop.wait(sleep_for):
                break

    @staticmethod
    def _ensure_even_dims(frame: np.ndarray) -> np.ndarray:
        """Crop frame to even width/height required by yuv420p encoding.
        将帧裁剪为 yuv420p 编码所需的偶数宽高。"""
        h, w = frame.shape[:2]
        new_h = h - (h % 2)
        new_w = w - (w % 2)
        if new_h != h or new_w != w:
            frame = frame[:new_h, :new_w]
        return frame

    def _push_frame(self, frame: np.ndarray, output_rtsp_path: str) -> None:
        """Push annotated frame to MediaMTX via a persistent ffmpeg subprocess.
        通过持久化 ffmpeg 子进程将标注帧推送到 MediaMTX。

        Uses ``ffmpeg -f rawvideo`` to accept raw RGB24 frames on stdin and
        encode them as H.264 over RTSP.  The subprocess is kept alive across
        frames; it is re-created only when the output path or frame dimensions
        change.
        使用 ``ffmpeg -f rawvideo`` 在 stdin 上接收原始 RGB24 帧，编码为 H.264
        通过 RTSP 推流。子进程跨帧保持活跃；仅在输出路径或帧尺寸变化时重建。
        """
        frame = self._ensure_even_dims(frame)
        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            return

        with self._push_lock:
            try:
                # Re-create ffmpeg process when path or dimensions change.
                # 当路径或尺寸变化时重建 ffmpeg 进程。
                if (
                    self._push_proc is None
                    or self._push_proc.poll() is not None
                    or self._push_path != output_rtsp_path
                    or self._push_width != w
                    or self._push_height != h
                ):
                    self._close_push_container()
                    rtsp_url = (
                        f"{self.app_settings.get('mediamtx_rtsp_addr', 'rtsp://localhost:8554')}"
                        f"/{output_rtsp_path}"
                    )
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-f", "rawvideo",
                        "-pix_fmt", "rgb24",
                        "-s", f"{w}x{h}",
                        "-r", str(PUSH_FPS),
                        "-i", "pipe:0",
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-preset", PUSH_PRESET,
                        "-tune", "zerolatency",
                        "-g", str(PUSH_FPS),
                        "-bf", "0",
                        "-f", "rtsp",
                        "-rtsp_transport", "tcp",
                        rtsp_url,
                    ]
                    self._push_proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._push_path = output_rtsp_path
                    self._push_width = w
                    self._push_height = h

                # Write raw RGB frame bytes to ffmpeg stdin.
                # 将原始 RGB 帧字节写入 ffmpeg 的 stdin。
                if self._push_proc.stdin is not None:
                    self._push_proc.stdin.write(frame.tobytes())
                    self._push_proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                logger.warning("Push error for {}: {}", output_rtsp_path, exc)
                self._close_push_container()
            except Exception as exc:
                logger.warning("Push error for {}: {}", output_rtsp_path, exc)
                self._close_push_container()

    def _close_push_container(self) -> None:
        """Terminate the persistent ffmpeg push subprocess.
        终止持久化的 ffmpeg 推流子进程。"""
        if self._push_proc is not None:
            try:
                if self._push_proc.stdin is not None:
                    self._push_proc.stdin.close()
                self._push_proc.terminate()
                self._push_proc.wait(timeout=3)
            except Exception:
                try:
                    self._push_proc.kill()
                except Exception:
                    pass
            self._push_proc = None
            self._push_path = None
            self._push_width = 0
            self._push_height = 0

    # ── Utility ───────────────────────────────────────────────────────────

    def _stream_path(self) -> str:
        """Return the full MediaMTX route path for the input RTSP URL.
        返回输入 RTSP URL 对应的完整 MediaMTX 路由路径。"""
        raw = self.rtsp_url.rstrip("/")
        try:
            parsed = urlparse(raw)
            path = parsed.path.strip("/")
            if path:
                return path
        except Exception:
            pass
        return raw.rsplit("/", 1)[-1]

    def _stream_key(self) -> str:
        """Return the last path segment of the input RTSP URL.
        返回输入 RTSP URL 的最后一个路径段。"""
        return self._stream_path().rsplit("/", 1)[-1]

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
