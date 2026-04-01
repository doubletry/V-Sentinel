"""Standalone BaseVideoProcessor for the core minimal package.

This module duplicates the essential parts of ``backend.processing.base`` so
that it can run without importing the full backend.  The public API stays
identical, allowing processors written against this module to be dropped
into the full V-Sentinel backend without any changes.
"""

from __future__ import annotations

import asyncio
import queue
import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from loguru import logger

from core.constants import (
    DRAW_CLASSIFICATION_COLOR,
    DRAW_DETECTION_COLOR,
    DRAW_FONT_SCALE,
    DRAW_FONT_THICKNESS,
    PUSH_FPS,
    PUSH_PRESET,
    RTSP_TRANSPORT,
)

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

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the processing task."""
        if self._task is not None and not self._task.done():
            logger.warning("Processor already running for {}", self.source_id)
            return
        self._stop_event.clear()
        self._display_stop.clear()
        self._start_display_worker()
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
            self._stop_display_worker()

    # ── Frame Reader (runs in thread) ─────────────────────────────────────

    def _frame_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        """Read frames from RTSP stream using ffmpeg subprocess (blocking I/O,
        runs in thread).
        使用 ffmpeg 子进程从 RTSP 流读取帧（阻塞 I/O，在线程中运行）。

        ffmpeg decodes the RTSP stream and outputs raw RGB24 pixels to stdout.
        Using TCP transport avoids the green-frame / mosaic artifacts caused by
        UDP packet loss.  Images are encoded once as RGB JPEG; downstream code
        reuses the encoded bytes without re-encoding.
        ffmpeg 解码 RTSP 流并将原始 RGB24 像素输出到 stdout。
        使用 TCP 传输避免 UDP 丢包导致的绿帧/马赛克。图像仅编码一次为 RGB JPEG；
        下游代码复用编码字节，无需重新编码。
        """
        logger.info("Frame reader started for {}", self.rtsp_url)

        # Step 1 — probe stream dimensions with ffprobe so we know how many
        # bytes to read per frame.  Fallback to a default if probing fails.
        # 第 1 步——用 ffprobe 探测流尺寸以确定每帧读取的字节数。探测失败则使用默认值。
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

        # Ensure even dims for downstream yuv420p encoding.
        # 确保偶数尺寸以适配下游 yuv420p 编码。
        probe_w -= probe_w % 2
        probe_h -= probe_h % 2

        frame_bytes = probe_w * probe_h * 3  # RGB24
        logger.info(
            "Frame reader: {}x{} ({} bytes/frame) for {}",
            probe_w, probe_h, frame_bytes, self.rtsp_url,
        )

        # Step 2 — launch ffmpeg reader.
        # 第 2 步——启动 ffmpeg 读取进程。
        cmd = [
            "ffmpeg",
            "-rtsp_transport", RTSP_TRANSPORT,
            "-i", self.rtsp_url,
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{probe_w}x{probe_h}",
            "-an",                        # no audio / 无音频
            "-sn",                        # no subtitles / 无字幕
            "-vf", f"scale={probe_w}:{probe_h}",
            "pipe:1",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=frame_bytes * 2,
        )

        try:
            while not self._stop_event.is_set():
                raw = proc.stdout.read(frame_bytes)  # type: ignore[union-attr]
                if len(raw) != frame_bytes:
                    # Stream ended or read error.
                    # 流结束或读取错误。
                    if not self._stop_event.is_set():
                        logger.warning(
                            "Frame reader got {} bytes (expected {}), stream may have ended",
                            len(raw), frame_bytes,
                        )
                    break

                rgb = np.frombuffer(raw, dtype=np.uint8).reshape(
                    (probe_h, probe_w, 3)
                )

                # Encode RGB directly — single encode, reused downstream
                # 直接编码 RGB — 仅编码一次，下游复用
                if _jpeg is not None:
                    from turbojpeg import TJPF_RGB
                    encoded = _jpeg.encode(rgb, quality=85, pixel_format=TJPF_RGB)
                else:
                    # Fallback: cv2.imencode expects BGR, so convert
                    # 回退：cv2.imencode 需要 BGR，因此转换
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
            try:
                loop.call_soon_threadsafe(self._enqueue_reader_sentinel)
            except Exception:
                pass
            logger.info("Frame reader exited for {}", self.rtsp_url)

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
            output_path = f"{self._stream_key()}_processed"
            self._enqueue_display(frame, result, output_path)

    def _should_display_result(self, result: AnalysisResult) -> bool:
        """Return whether a result should be drawn/pushed to the output stream."""
        return bool(
            result.annotated_frame is not None
            or result.detections
            or result.classifications
            or result.ocr_texts
            or result.actions
        )

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
            self._push_frame(display_frame, output_rtsp_path)

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
