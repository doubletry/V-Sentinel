"""Standalone BaseVideoProcessor for the core minimal package.

This module duplicates the essential parts of ``backend.processing.base`` so
that it can run without importing the full backend.  The public API stays
identical, allowing processors written against this module to be dropped
into the full V-Sentinel backend without any changes.
"""

from __future__ import annotations

import asyncio
import base64
import math
import queue
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse, quote

import cv2
import numpy as np
import av
from loguru import logger

from core.constants import (
    DRAW_CLASSIFICATION_COLOR,
    DRAW_DETECTION_COLOR,
    DRAW_FONT_SCALE,
    DRAW_FONT_THICKNESS,
    FRAME_SAMPLE_INTERVAL,
    PUSH_PRESET,
    RTSP_MAX_RECONNECT_ATTEMPTS,
    RTSP_RECONNECT_DELAY,
)

FALLBACK_PUBLISH_FPS = 1
INPUT_RTSP_TRANSPORT = "tcp"
LOW_LATENCY_PROBESIZE = "32"
LOW_LATENCY_ANALYZEDURATION = "0"
STREAM_TIMEOUT_MICROSECONDS = "5000000"
OUTPUT_QUEUE_TIMEOUT_SEC = 0.2
MAX_REASONABLE_SOURCE_FPS = 120.0
OBSERVED_FPS_ESTIMATE_WINDOW_SEC = 1.0
FPS_CHANGE_THRESHOLD = 0.01
GOP_DIVISOR = 2
PUSH_STARTUP_CHECK_DELAY = 0.3  # seconds to wait after spawning ffmpeg to verify it is alive / 创建 ffmpeg 后等待验证存活的秒数
PUSH_RETRY_BASE_COOLDOWN = 2.0  # initial cooldown seconds after push failure / 推流失败后的初始冷却秒数
PUSH_RETRY_MAX_COOLDOWN = 30.0  # maximum cooldown between retries / 重试之间的最大冷却秒数
MAX_STDERR_LOG_CHARS = 500  # truncation limit for logged ffmpeg stderr / 日志中 ffmpeg stderr 的截断长度

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
        self._push_fps: float = 0.0
        self._push_retry_after: float = 0.0  # monotonic time before which retries are skipped / 重试冷却截止时间
        self._push_consecutive_failures: int = 0  # consecutive failure counter / 连续失败计数
        self._output_queue: queue.Queue[
            tuple[np.ndarray, AnalysisResult, str] | None
        ] = queue.Queue(maxsize=2)
        self._output_stop = threading.Event()
        self._output_thread: threading.Thread | None = None
        self._publish_state_lock = threading.Lock()
        self._source_fps: float | None = None
        self._publish_fps: float = self._default_publish_fps()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the processing task."""
        if self._task is not None and not self._task.done():
            logger.warning("Processor already running for {}", self.source_id)
            return
        self._stop_event.clear()
        self._output_stop.clear()
        # Reset push retry state so a fresh start is not blocked by stale
        # cooldown from a previous run.
        # 重置推流重试状态，避免上次运行残留的冷却期阻塞新启动。
        self._push_consecutive_failures = 0
        self._push_retry_after = 0.0
        self._start_output_worker()
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
        self._stop_output_worker()
        self._close_push_process()
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
            self._stop_output_worker()

    # ── Frame Reader (runs in thread) ─────────────────────────────────────

    def _frame_reader(self, loop: asyncio.AbstractEventLoop) -> None:
        """Read frames from RTSP using PyAV with low-latency options.
        使用 PyAV 和低延迟参数从 RTSP 读取帧。"""
        import time as _time

        logger.info("Frame reader started for {}", self.rtsp_url)
        reconnect_attempts = 0
        max_attempts = RTSP_MAX_RECONNECT_ATTEMPTS  # 0 = unlimited
        frame_counter = 0  # for FRAME_SAMPLE_INTERVAL skipping

        while not self._stop_event.is_set():
            stream_ok = False
            container: av.container.InputContainer | None = None
            try:
                container = av.open(
                    self.rtsp_url,
                    mode="r",
                    options={
                        "rtsp_transport": INPUT_RTSP_TRANSPORT,
                        "fflags": "nobuffer",
                        "flags": "low_delay",
                        "probesize": LOW_LATENCY_PROBESIZE,
                        "analyzeduration": LOW_LATENCY_ANALYZEDURATION,
                        "avioflags": "direct",
                        "flush_packets": "1",
                        "max_delay": "0",
                        "stimeout": STREAM_TIMEOUT_MICROSECONDS,
                    },
                    timeout=(5.0, 5.0),
                )
                video_stream = next(
                    (stream for stream in container.streams if stream.type == "video"),
                    None,
                )
                if video_stream is None:
                    raise RuntimeError(
                        f"No video track found in stream {self.rtsp_url}"
                    )
                video_stream.thread_type = "AUTO"
                source_fps = self._stream_fps(video_stream)
                self._update_publish_fps(source_fps)
                observed_first_frame_at: float | None = None
                observed_frame_count = 0

                for frame in container.decode(video=0):
                    if self._stop_event.is_set():
                        break
                    stream_ok = True
                    reconnect_attempts = 0
                    if source_fps is None:
                        now = _time.monotonic()
                        if observed_first_frame_at is None:
                            observed_first_frame_at = now
                            observed_frame_count = 1
                        else:
                            observed_frame_count += 1
                            observed_fps = self._observed_fps(
                                observed_frame_count,
                                now - observed_first_frame_at,
                            )
                            if observed_fps is not None:
                                # Stop re-estimating after the first stable
                                # observed FPS is obtained.
                                source_fps = observed_fps
                                self._update_publish_fps(source_fps)
                    frame_counter += 1
                    if (
                        FRAME_SAMPLE_INTERVAL > 1
                        and (frame_counter % FRAME_SAMPLE_INTERVAL) != 0
                    ):
                        continue
                    rgb = frame.to_ndarray(format="rgb24")
                    if _jpeg is not None:
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
                if not stream_ok and not self._stop_event.is_set():
                    logger.warning("PyAV reader ended before yielding frames for {}", self.rtsp_url)
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.exception("Frame reader error for {}: {}", self.rtsp_url, exc)
            finally:
                try:
                    if container is not None:
                        container.close()
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
    def _stream_fps(video_stream: Any) -> float | None:
        """Best-effort FPS extraction from a PyAV video stream.
        尽力从 PyAV 视频流中提取 FPS。

        Returns:
            A positive FPS value if one can be extracted, else ``None``.
            若能提取到有效正数 FPS 则返回该值，否则返回 ``None``。"""
        codec_context = getattr(video_stream, "codec_context", None)
        # In low-delay mode PyAV can leave average_rate empty and expose an
        # inflated guessed/base rate, while codec_context.framerate keeps the
        # encoder-declared cadence (for example 25 instead of a guessed 50).
        # 在低延迟模式下 average_rate 可能为空，而 guessed/base rate 可能偏大；
        # codec_context.framerate 通常更接近编码器声明的真实帧率。
        for rate in (
            getattr(video_stream, "average_rate", None),
            getattr(codec_context, "framerate", None) if codec_context else None,
            getattr(video_stream, "base_rate", None),
            getattr(video_stream, "guessed_rate", None),
        ):
            if rate is None:
                continue
            try:
                value = float(rate)
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if math.isfinite(value) and 0 < value <= MAX_REASONABLE_SOURCE_FPS:
                return value
        return None

    @staticmethod
    def _observed_fps(frame_count: int, elapsed_seconds: float) -> float | None:
        """Estimate rounded FPS from observed decoded frames over time.
        基于一段时间内观察到的解码帧估算取整后的 FPS。"""
        if (
            frame_count < 2
            or not math.isfinite(elapsed_seconds)
            or elapsed_seconds < OBSERVED_FPS_ESTIMATE_WINDOW_SEC
        ):
            return None
        # FPS is derived from intervals between decoded frames, so N frames
        # over a window only contain N-1 frame gaps.
        estimated_fps = round((frame_count - 1) / elapsed_seconds)
        if 0 < estimated_fps <= MAX_REASONABLE_SOURCE_FPS:
            return float(estimated_fps)
        return None

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
        self,
        frame: np.ndarray | None,
        max_width: int = 1920,
        max_height: int = 1080,
    ) -> str | None:
        """Encode a message image as a base64 JPEG, capped at Full HD by default.
        将消息图像编码为 base64 JPEG，默认限制在 Full HD 尺寸内。"""
        if frame is None:
            return None

        h, w = frame.shape[:2]
        if h <= 0 or w <= 0:
            return None
        if w > max_width or h > max_height:
            scale = min(max_width / w, max_height / h)
            resized_width = min(max_width, max(1, int(round(w * scale))))
            resized_height = min(max_height, max(1, int(round(h * scale))))
            frame = cv2.resize(
                frame,
                (resized_width, resized_height),
                interpolation=cv2.INTER_AREA,
            )

        if _jpeg is not None:
            encoded = _jpeg.encode(frame, quality=85, pixel_format=TJPF_RGB)
        else:
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
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
            self._enqueue_output(frame, result, output_path)

    def _should_display_result(self, result: AnalysisResult) -> bool:
        """Return whether a result should be drawn/pushed to the output stream."""
        del result
        return True

    def _start_output_worker(self) -> None:
        """Start the unified output worker thread if it is not running."""
        if self._output_thread is not None and self._output_thread.is_alive():
            return
        self._output_thread = threading.Thread(
            target=self._output_worker,
            name=f"output-{self.source_id}",
            daemon=True,
        )
        self._output_thread.start()

    def _stop_output_worker(self) -> None:
        """Stop the unified output worker thread."""
        self._output_stop.set()
        self._force_enqueue(self._output_queue, None)
        if self._output_thread is not None:
            self._output_thread.join(timeout=2.0)
            self._output_thread = None
        self._drain_queue(self._output_queue)

    def _enqueue_output(
        self, frame: np.ndarray, result: AnalysisResult, output_rtsp_path: str
    ) -> None:
        """Queue a frame/result pair for the unified output worker."""
        self._force_enqueue(self._output_queue, (frame, result, output_rtsp_path))

    def _display_output_path(self) -> str:
        """Return the RTSP output path used for processed frames.
        返回处理结果帧使用的 RTSP 输出路径。"""
        return f"{self._stream_path()}_processed"

    def _default_publish_fps(self) -> float:
        """Fallback publish FPS before the input stream reports a frame rate.
        输入流未报告帧率前使用的默认推流 FPS。"""
        return float(FALLBACK_PUBLISH_FPS)

    def _update_publish_fps(self, source_fps: float | None) -> None:
        """Refresh effective publish FPS from source FPS.
        根据源流 FPS 刷新有效推流 FPS。"""
        if source_fps is None or not math.isfinite(source_fps) or source_fps <= 0:
            publish_fps = self._default_publish_fps()
        else:
            publish_fps = float(source_fps)
        with self._publish_state_lock:
            self._source_fps = source_fps
            self._publish_fps = publish_fps
        source_fps_display = (
            f"{source_fps:.3f}" if source_fps is not None else "unknown"
        )
        logger.info(
            "Using source FPS {} and publish FPS {:.3f} for {}",
            source_fps_display,
            publish_fps,
            self.source_id,
        )

    def _current_publish_fps(self) -> float:
        """Return the current effective publish FPS with a safe fallback.
        返回当前有效推流 FPS，并在异常值时安全回退。"""
        with self._publish_state_lock:
            target_fps = self._publish_fps
        if target_fps <= 0:
            logger.warning(
                "Invalid publish FPS {:.3f} for {}, falling back to {}",
                target_fps,
                self.source_id,
                FALLBACK_PUBLISH_FPS,
            )
            return float(FALLBACK_PUBLISH_FPS)
        return target_fps

    @staticmethod
    def _force_enqueue(
        target_queue: "queue.Queue[Any]",
        item: Any,
    ) -> None:
        """Insert an item into a bounded queue, dropping one stale item if needed.
        向有界队列插入条目；若队列已满则丢弃一个旧条目后重试。"""
        try:
            target_queue.put_nowait(item)
        except queue.Full:
            try:
                target_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                target_queue.put_nowait(item)
            except queue.Full:
                logger.debug("Dropping stale queued item because {} queue stayed full", target_queue)

    @staticmethod
    def _drain_queue(target_queue: "queue.Queue[Any]") -> None:
        """Drain any remaining items from a queue after its worker stops.
        在线程停止后清空残留队列项。"""
        while not target_queue.empty():
            try:
                target_queue.get_nowait()
            except queue.Empty:
                break

    def _output_worker(self) -> None:
        """Draw queued results and repeat the latest output frame at steady cadence.
        消费输出队列，完成绘制并以稳定节奏重复推送最新结果帧。"""
        latest_frame: np.ndarray | None = None
        latest_path: str | None = None
        next_deadline = time.monotonic()
        while not self._output_stop.is_set():
            try:
                if latest_frame is None or latest_path is None:
                    try:
                        item = self._output_queue.get(timeout=OUTPUT_QUEUE_TIMEOUT_SEC)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    latest_frame, latest_path = self._prepare_output_item(item)
                    if latest_frame is None:
                        continue
                    self._push_frame(latest_frame.copy(), latest_path)
                    next_deadline = time.monotonic() + (1.0 / self._current_publish_fps())
                    continue

                now = time.monotonic()
                wait_for = max(0.0, next_deadline - now)
                try:
                    item = self._output_queue.get(timeout=wait_for)
                except queue.Empty:
                    self._push_frame(latest_frame.copy(), latest_path)
                    frame_interval = 1.0 / self._current_publish_fps()
                    next_deadline += frame_interval
                    now = time.monotonic()
                    if next_deadline < now:
                        logger.debug(
                            "Publisher fell behind by {:.3f}s for {}",
                            now - next_deadline,
                            self.source_id,
                        )
                        next_deadline = now + frame_interval
                    continue
                if item is None:
                    break
                latest_frame, latest_path = self._prepare_output_item(item)
                if latest_frame is None:
                    continue
                stop_after_coalesce = False
                while True:
                    now = time.monotonic()
                    remaining = next_deadline - now
                    if remaining <= 0:
                        break
                    try:
                        item = self._output_queue.get(timeout=remaining)
                    except queue.Empty:
                        break
                    if item is None:
                        stop_after_coalesce = True
                        break
                    latest_frame, latest_path = self._prepare_output_item(item)
                    if latest_frame is None:
                        continue
                if stop_after_coalesce:
                    break
                self._push_frame(latest_frame.copy(), latest_path)
                next_deadline = time.monotonic() + (1.0 / self._current_publish_fps())
            except Exception as exc:
                logger.error(
                    "Output worker error for {}: {}", self.source_id, exc
                )

    def _prepare_output_item(
        self,
        item: tuple[np.ndarray, AnalysisResult, str],
    ) -> tuple[np.ndarray | None, str]:
        """Convert one queued output item into a rendered frame/path pair.
        将单个输出队列项转换为已渲染的帧与路径。"""
        frame, result, output_rtsp_path = item
        return self._render_output_frame(frame, result, output_rtsp_path), output_rtsp_path

    def _render_output_frame(
        self,
        frame: np.ndarray,
        result: AnalysisResult,
        output_rtsp_path: str,
    ) -> np.ndarray | None:
        """Render a processed frame before it is pushed.
        在推流前渲染处理后的结果帧。"""
        display_frame = result.annotated_frame
        if display_frame is None:
            try:
                display_frame = self.draw_on_frame(frame, result)
            except Exception as exc:
                logger.debug("Display draw error for {}: {}", output_rtsp_path, exc)
                return None
        display_frame = self._ensure_even_dims(display_frame)
        if display_frame.shape[0] == 0 or display_frame.shape[1] == 0:
            return None
        return display_frame

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

    def _build_push_rtsp_url(self, output_rtsp_path: str) -> str:
        """Build the RTSP push URL, injecting MediaMTX credentials when configured.
        构造 RTSP 推流 URL，已配置 MediaMTX 账号密码时会注入到 URL 中。"""
        base = str(
            self.app_settings.get("mediamtx_rtsp_addr", "rtsp://localhost:8554")
        ).rstrip("/")
        username = str(self.app_settings.get("mediamtx_username", "") or "")
        password = str(self.app_settings.get("mediamtx_password", "") or "")
        if username:
            parsed = urlparse(base)
            host = parsed.hostname or ""
            if host:
                userinfo = quote(username, safe="")
                if password:
                    userinfo += ":" + quote(password, safe="")
                netloc = userinfo + "@" + host
                if parsed.port is not None:
                    netloc += f":{parsed.port}"
                base = urlunparse(
                    (
                        parsed.scheme,
                        netloc,
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                ).rstrip("/")
        return f"{base}/{output_rtsp_path}"

    def _push_frame(self, frame: np.ndarray, output_rtsp_path: str) -> None:
        """Push annotated frame to MediaMTX via a persistent ffmpeg subprocess.
        通过持久化 ffmpeg 子进程将标注帧推送到 MediaMTX。"""
        frame = self._ensure_even_dims(frame)
        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            return

        rtsp_url = self._build_push_rtsp_url(output_rtsp_path)

        with self._push_lock:
            # Respect retry cooldown after previous failures.
            # 失败后遵守重试冷却期。
            if time.monotonic() < self._push_retry_after:
                return

            try:
                target_fps = self._current_publish_fps()
                # Keep keyframes about twice per second so new RTSP readers can
                # lock onto the stream faster under low-latency UDP delivery.
                # GOP_DIVISOR = 2 means ~0.5s keyframe spacing.
                # 约每 0.5 秒一个关键帧，帮助低延迟 UDP 读者更快起播。
                gop = max(1, int(round(target_fps / GOP_DIVISOR)))
                # Re-create ffmpeg process when path or dimensions change.
                # 当路径或尺寸变化时重建 ffmpeg 进程。
                need_new_proc = (
                    self._push_proc is None
                    or self._push_proc.poll() is not None
                    or self._push_path != output_rtsp_path
                    or self._push_width != w
                    or self._push_height != h
                    or abs(self._push_fps - target_fps) > FPS_CHANGE_THRESHOLD
                )
                if need_new_proc:
                    self._close_push_process()
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-fflags", "nobuffer",
                        "-flags", "low_delay",
                        "-flush_packets", "1",
                        "-f", "rawvideo",
                        "-pix_fmt", "rgb24",
                        "-s", f"{w}x{h}",
                        "-r", f"{target_fps:.3f}",
                        "-i", "pipe:0",
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-preset", PUSH_PRESET,
                        "-tune", "zerolatency",
                        "-g", str(gop),
                        "-bf", "0",
                        "-muxdelay", "0",
                        "-muxpreload", "0",
                        "-f", "rtsp",
                        "-rtsp_transport", "tcp",
                        rtsp_url,
                    ]
                    self._push_proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    self._push_path = output_rtsp_path
                    self._push_width = w
                    self._push_height = h
                    self._push_fps = target_fps

                    # Give ffmpeg a moment to initialize and verify it is alive.
                    # 等待 ffmpeg 启动并验证其存活。
                    time.sleep(PUSH_STARTUP_CHECK_DELAY)
                    if self._push_proc.poll() is not None:
                        stderr_text = self._read_push_stderr()
                        logger.warning(
                            "ffmpeg exited immediately for {} (code {}): {}",
                            rtsp_url,
                            self._push_proc.returncode,
                            stderr_text,
                        )
                        self._close_push_process()
                        self._record_push_failure()
                        return

                if self._push_proc is not None and self._push_proc.stdin is not None:
                    self._push_proc.stdin.write(frame.tobytes())
                    self._push_proc.stdin.flush()
                    # Reset failure counter on successful write.
                    # 写入成功后重置失败计数。
                    self._push_consecutive_failures = 0
                    self._push_retry_after = 0.0
            except (BrokenPipeError, OSError) as exc:
                stderr_text = self._read_push_stderr()
                logger.warning(
                    "Push error for {}: {} | stderr: {}", rtsp_url, exc, stderr_text
                )
                self._close_push_process()
                self._record_push_failure()
            except Exception as exc:
                logger.warning("Push error for {}: {}", rtsp_url, exc)
                self._close_push_process()
                self._record_push_failure()

    def _record_push_failure(self) -> None:
        """Increment consecutive failure count and schedule a retry cooldown.
        增加连续失败计数并设置重试冷却期。"""
        self._push_consecutive_failures += 1
        cooldown = min(
            PUSH_RETRY_BASE_COOLDOWN * self._push_consecutive_failures,
            PUSH_RETRY_MAX_COOLDOWN,
        )
        self._push_retry_after = time.monotonic() + cooldown
        logger.info(
            "Push retry cooldown {:.1f}s (attempt {}) for {}",
            cooldown,
            self._push_consecutive_failures,
            self.source_id,
        )

    def _read_push_stderr(self) -> str:
        """Read available stderr from the ffmpeg push process (non-blocking).
        非阻塞地读取 ffmpeg 推流进程的 stderr 输出。"""
        if self._push_proc is None or self._push_proc.stderr is None:
            return ""
        try:
            # Only read stderr if the process has already exited, to avoid
            # blocking on a still-running process.
            # 仅在进程已退出时读取 stderr，以避免阻塞仍在运行的进程。
            if self._push_proc.poll() is None:
                return "(process still running)"
            data = self._push_proc.stderr.read()
            if data:
                return data.decode("utf-8", errors="replace").strip()[-MAX_STDERR_LOG_CHARS:]
            return ""
        except Exception:
            return ""

    def _close_push_process(self) -> None:
        """Terminate the persistent ffmpeg push subprocess.
        终止持久化 ffmpeg 推流子进程。"""
        if self._push_proc is not None:
            try:
                if self._push_proc.stdin is not None:
                    self._push_proc.stdin.close()
                if self._push_proc.stderr is not None:
                    self._push_proc.stderr.close()
                self._push_proc.terminate()
                self._push_proc.wait(timeout=3.0)
            except Exception:
                try:
                    self._push_proc.kill()
                except Exception:
                    pass
            self._push_proc = None
            self._push_path = None
            self._push_width = 0
            self._push_height = 0
            self._push_fps = 0.0

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
