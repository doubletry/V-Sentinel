"""Async gRPC client for all V-Engine services — core (standalone) version.
V-Engine 全服务异步 gRPC 客户端 — core（独立）版本。

This is the **canonical** implementation of ``AsyncVEngineClient``.  The backend
module ``backend.vengine.client`` re-exports this class so there is only one
source of truth.
这是 ``AsyncVEngineClient`` 的**规范**实现。后台模块
``backend.vengine.client`` 重新导出此类，以确保只有一个代码来源。

The client is configured purely via a ``dict[str, str]`` of application
settings (``app_settings``), identical to the ones stored in the V-Sentinel
DB.  No pydantic ``Settings`` object is required.
客户端完全通过 ``dict[str, str]`` 的应用设置（``app_settings``）进行配置，
与 V-Sentinel 数据库中存储的设置相同。不需要 pydantic ``Settings`` 对象。
"""
from __future__ import annotations

import secrets
import time

import grpc.aio
from loguru import logger

from core.proto import (
    base_pb2,
    detection_service_pb2,
    detection_service_pb2_grpc,
    classification_service_pb2,
    classification_service_pb2_grpc,
    action_service_pb2,
    action_service_pb2_grpc,
    ocr_service_pb2,
    ocr_service_pb2_grpc,
    upload_service_pb2,
    upload_service_pb2_grpc,
)

# Default application settings used when none are provided.
# 未提供设置时使用的默认应用设置。
_DEFAULT_APP_SETTINGS: dict[str, str] = {
    "vengine_host": "localhost",
    "detection_port": "50051",
    "classification_port": "50052",
    "action_port": "50053",
    "ocr_port": "50054",
    "upload_port": "50050",
    "detection_enabled": "true",
    "classification_enabled": "true",
    "action_enabled": "true",
    "ocr_enabled": "true",
    "upload_enabled": "true",
}


class AsyncVEngineClient:
    """Async gRPC client for all V-Engine services.
    V-Engine 全服务异步 gRPC 客户端。

    All channels are shared across all camera processors.
    HTTP/2 multiplexing handles concurrent requests automatically.
    所有通道在所有摄像头处理器间共享。HTTP/2 多路复用自动处理并发请求。

    Service addresses are read from an ``app_settings`` dict.
    The ``reconnect_from_settings`` method allows hot-reloading addresses.
    服务地址从 ``app_settings`` 字典中读取。
    ``reconnect_from_settings`` 方法允许热重载地址。

    Individual services can be disabled via ``<service>_enabled`` settings.
    When a service is disabled, no channel is created and calling its methods
    returns an empty result gracefully.
    可通过 ``<service>_enabled`` 设置禁用单个服务。禁用后不创建通道，
    调用其方法时会优雅地返回空结果。
    """

    # Names of all V-Engine services / 所有 V-Engine 服务名称
    SERVICE_NAMES = ("detection", "classification", "action", "ocr", "upload")

    def __init__(self) -> None:
        self._channels: dict[str, grpc.aio.Channel] = {}
        self._stubs: dict[str, object] = {}
        self._enabled: dict[str, bool] = {s: True for s in self.SERVICE_NAMES}

    # ── Address resolution / 地址解析 ────────────────────────────────────────

    @staticmethod
    def _build_addresses(app_settings: dict[str, str]) -> dict[str, str]:
        """Build ``{service: host:port}`` from settings dict.
        从设置字典构建 ``{服务名: 主机:端口}`` 映射。"""
        host = app_settings.get("vengine_host", "localhost")
        return {
            "detection": f"{host}:{app_settings.get('detection_port', '50051')}",
            "classification": f"{host}:{app_settings.get('classification_port', '50052')}",
            "action": f"{host}:{app_settings.get('action_port', '50053')}",
            "ocr": f"{host}:{app_settings.get('ocr_port', '50054')}",
            "upload": f"{host}:{app_settings.get('upload_port', '50050')}",
        }

    @staticmethod
    def _parse_enabled(app_settings: dict[str, str]) -> dict[str, bool]:
        """Parse ``<service>_enabled`` flags from settings.
        从设置解析各服务启用/禁用标志。"""
        def _is_true(val: str) -> bool:
            return str(val).strip().lower() in ("true", "1", "yes")

        return {
            "detection": _is_true(app_settings.get("detection_enabled", "true")),
            "classification": _is_true(app_settings.get("classification_enabled", "true")),
            "action": _is_true(app_settings.get("action_enabled", "true")),
            "ocr": _is_true(app_settings.get("ocr_enabled", "true")),
            "upload": _is_true(app_settings.get("upload_enabled", "true")),
        }

    def is_service_enabled(self, service: str) -> bool:
        """Check whether a specific V-Engine service is enabled.
        检查指定的 V-Engine 服务是否已启用。"""
        return self._enabled.get(service, False)

    # ── Connect / reconnect / 连接与重连 ─────────────────────────────────────

    async def connect(self, app_settings: dict[str, str] | None = None) -> None:
        """Create grpc.aio channels and stubs for enabled services only.
        仅为已启用的服务创建 gRPC 通道和存根。

        If *app_settings* is ``None``, defaults are used.
        若 *app_settings* 为 ``None``，则使用默认设置。
        """
        if app_settings is None:
            app_settings = _DEFAULT_APP_SETTINGS

        self._enabled = self._parse_enabled(app_settings)
        addrs = self._build_addresses(app_settings)
        self._create_channels_and_stubs(addrs)

        enabled_list = [s for s, e in self._enabled.items() if e]
        disabled_list = [s for s, e in self._enabled.items() if not e]
        logger.info(
            "AsyncVEngineClient connected — enabled: {}, disabled: {}",
            enabled_list or "(none)",
            disabled_list or "(none)",
        )

    async def reconnect_from_settings(self, app_settings: dict[str, str]) -> None:
        """Close existing channels and reconnect with new addresses/flags.
        关闭现有通道并使用新地址/标志重新连接。"""
        await self.close()
        await self.connect(app_settings)
        logger.info("AsyncVEngineClient reconnected with updated settings")

    def _create_channels_and_stubs(self, addrs: dict[str, str]) -> None:
        """Create gRPC channels and stubs for enabled services only.
        仅为已启用的服务创建 gRPC 通道和存根。"""
        stub_map = {
            "detection": detection_service_pb2_grpc.ObjectDetectionStub,
            "classification": classification_service_pb2_grpc.ImageClassificationStub,
            "action": action_service_pb2_grpc.ActionRecognitionStub,
            "ocr": ocr_service_pb2_grpc.OpticalCharacterRecognitionStub,
            "upload": upload_service_pb2_grpc.UploadStub,
        }
        for service, stub_cls in stub_map.items():
            if self._enabled.get(service, False):
                channel = grpc.aio.insecure_channel(addrs[service])
                self._channels[service] = channel
                self._stubs[service] = stub_cls(channel)
            else:
                logger.debug("Skipping disabled service: {}", service)

    async def close(self) -> None:
        """Close all gRPC channels. 关闭所有 gRPC 通道。"""
        for name, channel in self._channels.items():
            try:
                await channel.close()
                logger.debug("Closed gRPC channel: {}", name)
            except Exception as exc:  # pragma: no cover
                logger.warning("Error closing channel {}: {}", name, exc)

    # ── Helpers / 辅助方法 ───────────────────────────────────────────────────

    def _make_header(self, client_id: str = "v-sentinel") -> base_pb2.RequestHeader:
        """Create a gRPC request header. 创建 gRPC 请求头。"""
        return base_pb2.RequestHeader(
            request_timestamp=time.time(),
            request_id=secrets.token_hex(8),
            client_id=client_id,
        )

    def _make_roi_polygon(
        self, roi_points: list[dict]
    ) -> base_pb2.Polygon:
        """Convert ROI points [{x, y}, ...] to Polygon (pixel coords).
        将 ROI 点 [{x, y}, ...] 转换为 Polygon（像素坐标）。"""
        points = [base_pb2.Point(x=int(p["x"]), y=int(p["y"])) for p in roi_points]
        return base_pb2.Polygon(points=points)

    def _make_image(
        self,
        shape: tuple[int, ...],
        image_roi: list[dict] | None = None,
        *,
        image_id: int = 0,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
    ) -> base_pb2.Image:
        """Build a ``base_pb2.Image`` from either raw bytes **or** a cache key.
        从原始字节**或**缓存键构建 ``base_pb2.Image``。

        *image_roi* is an optional per-image ROI that goes into
        ``Image.region_of_interest`` (used for pre-processing crops, e.g.
        classification and OCR).  This is distinct from model_roi which
        goes into ``InferenceParams.region_of_interest``.
        *image_roi* 是可选的逐图 ROI，放入 ``Image.region_of_interest``
        （用于预处理裁剪，如分类和 OCR）。这与放入
        ``InferenceParams.region_of_interest`` 的 model_roi 不同。

        Exactly one of *image_bytes* / *image_key* must be provided.
        必须且仅提供 *image_bytes* / *image_key* 其中之一。
        """
        if image_bytes is None and image_key is None:
            raise ValueError("Provide either image_bytes or image_key")
        if image_bytes is not None and image_key is not None:
            raise ValueError("Provide only one of image_bytes or image_key, not both")

        roi_polygon = (
            self._make_roi_polygon(image_roi) if image_roi else base_pb2.Polygon()
        )
        kwargs: dict = {
            "id": image_id,
            "shape": base_pb2.ShapeInfo(dims=list(shape)),
            "region_of_interest": roi_polygon,
        }
        if image_bytes is not None:
            kwargs["data"] = image_bytes
        else:
            kwargs["key"] = image_key
        return base_pb2.Image(**kwargs)

    def _make_images(
        self,
        *,
        shape: tuple[int, ...] | None = None,
        image_roi: list[dict] | None = None,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
        images: list[dict] | None = None,
    ) -> list[base_pb2.Image]:
        """Build one or more ``base_pb2.Image`` objects.
        构建一个或多个 ``base_pb2.Image`` 对象。

        *image_roi* sets ``Image.region_of_interest`` for per-image
        pre-processing crops.  This is independent of model_roi which
        goes into ``InferenceParams.region_of_interest``.
        *image_roi* 设置 ``Image.region_of_interest`` 用于逐图预处理裁剪。
        这与放入 ``InferenceParams.region_of_interest`` 的 model_roi 无关。

        When ``images`` is provided, each item may contain:
        ``shape`` plus exactly one of ``image_bytes``/``image_key``.
        For convenience, ``roi`` and ``key`` are accepted as aliases for
        ``image_roi`` and ``image_key``.
        当提供 ``images`` 时，每个元素都应包含 ``shape``，并且必须在
        ``image_bytes`` / ``image_key`` 中二选一。为方便起见，也接受
        ``roi`` 和 ``key`` 作为 ``image_roi`` 与 ``image_key`` 的别名。
        """
        if images is not None:
            built_images: list[base_pb2.Image] = []
            for idx, item in enumerate(images):
                built_images.append(
                    self._make_image(
                        tuple(item["shape"]),
                        item.get("image_roi", item.get("roi_points", item.get("roi"))),
                        image_id=idx,
                        image_bytes=item.get("image_bytes", item.get("data")),
                        image_key=item.get("image_key", item.get("key")),
                    )
                )
            return built_images

        if shape is None:
            raise ValueError("Provide shape when images are not supplied")

        return [
            self._make_image(
                shape,
                image_roi,
                image_id=0,
                image_bytes=image_bytes,
                image_key=image_key,
            )
        ]

    def _make_sequences(
        self,
        *,
        frames_bytes: list[bytes] | None = None,
        shapes: list[tuple[int, ...]] | None = None,
        image_roi: list[dict] | None = None,
        image_key: str | None = None,
        image_keys: list[str] | None = None,
        images: list[dict] | None = None,
        sequences: list[dict | list[dict]] | None = None,
    ) -> list[base_pb2.ImageSequence]:
        """Build one or more ``base_pb2.ImageSequence`` objects.
        构建一个或多个 ``base_pb2.ImageSequence`` 对象。"""
        if sequences is not None:
            built_sequences: list[base_pb2.ImageSequence] = []
            for seq_idx, sequence in enumerate(sequences):
                sequence_images = (
                    sequence.get("images", []) if isinstance(sequence, dict) else sequence
                )
                built_sequences.append(
                    base_pb2.ImageSequence(
                        images=self._make_images(images=sequence_images),
                        id=(
                            int(sequence.get("sequence_id", seq_idx))
                            if isinstance(sequence, dict)
                            else seq_idx
                        ),
                    )
                )
            return built_sequences

        if images is not None:
            return [base_pb2.ImageSequence(images=self._make_images(images=images), id=0)]

        if shapes is None:
            raise ValueError("Provide shapes when images/sequences are not supplied")

        if image_keys is None and image_key is not None:
            image_keys = [image_key] * len(shapes)

        if image_keys is not None:
            if len(image_keys) != len(shapes):
                raise ValueError("image_keys and shapes must have the same length")
            seq_images = [
                self._make_image(
                    shape,
                    image_roi,
                    image_id=idx,
                    image_key=key,
                )
                for idx, (key, shape) in enumerate(zip(image_keys, shapes))
            ]
        else:
            if frames_bytes is None:
                raise ValueError("Provide frames_bytes or image_keys")
            if len(frames_bytes) != len(shapes):
                raise ValueError("frames_bytes and shapes must have the same length")
            seq_images = [
                self._make_image(
                    shape,
                    image_roi,
                    image_id=idx,
                    image_bytes=data,
                )
                for idx, (data, shape) in enumerate(zip(frames_bytes, shapes))
            ]

        return [base_pb2.ImageSequence(images=seq_images, id=0)]

    # ── Upload + cache key / 上传与缓存键 ────────────────────────────────────

    async def upload_and_get_key(self, image_bytes: bytes, filename: str = "frame.jpg") -> str | None:
        """Upload an image to the cache and return its key.
        上传图像到缓存并返回其键。

        Returns ``None`` if upload service is disabled or on failure.
        若上传服务被禁用或失败，则返回 ``None``。

        The latest V-Engine proto sends uploads as ``repeated base.Image``
        without a filename field.  ``filename`` is accepted only for backward
        compatibility and is ignored by the RPC payload.
        最新版 V-Engine proto 使用 ``repeated base.Image`` 上传，不再包含
        文件名字段。这里保留 ``filename`` 参数仅用于向后兼容，RPC 负载中不会使用。
        """
        if not self._enabled.get("upload", False):
            return None
        results = await self.upload_image(image_bytes, filename)
        if results:
            return results[0].get("key")
        return None

    # ── Detection / 检测 ──────────────────────────────────────────────────────

    async def detect(
        self,
        shape: tuple[int, ...] | None,
        model_name: str,
        conf: float = 0.5,
        nms: float = 0.7,
        model_roi: list[dict] | None = None,
        *,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
        images: list[dict] | None = None,
    ) -> list[dict]:
        """Async object detection. 异步目标检测。

        Pass either single-image args (*shape* + *image_bytes*/*image_key*), or
        ``images=[{shape, image_bytes|image_key}, ...]`` for a batched request.
        既支持单图参数（*shape* + *image_bytes*/*image_key*），也支持
        ``images=[{shape, image_bytes|image_key}, ...]`` 的批量请求。

        *model_roi* is the user-drawn region of interest placed in
        ``InferenceParams.region_of_interest``.  The server runs detection on
        the full image, then filters results to keep only boxes inside this
        ROI (post-processing).  There is only **one** model_roi per request.
        *model_roi* 是用户绘制的感兴趣区域，放入
        ``InferenceParams.region_of_interest``。服务端在完整图像上运行检测，
        然后过滤结果仅保留 ROI 内的检测框（后处理）。
        每次请求只有**一个** model_roi。

        Returns list of {x_min, y_min, x_max, y_max, confidence, class_id, label}.
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("detection", False):
            return []
        try:
            request_images = self._make_images(
                shape=shape,
                image_bytes=image_bytes,
                image_key=image_key,
                images=images,
            )
            if not request_images:
                return []
            model_roi_polygon = (
                self._make_roi_polygon(model_roi) if model_roi else base_pb2.Polygon()
            )
            params = detection_service_pb2.DetectionParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    region_of_interest=model_roi_polygon,
                    # Detection uses model_roi: the server runs detection on the
                    # full image, then filters results to keep only boxes inside
                    # the ROI (post-processing).
                    # 检测使用 model_roi：服务端在完整图像上运行检测，然后过滤结果
                    # 仅保留 ROI 内的检测框（后处理）。
                    use_model_roi=bool(model_roi),
                ),
                confidence_threshold=conf,
                nms_iou_threshold=nms,
            )
            request = detection_service_pb2.DetectionRequest(
                request_header=self._make_header(),
                images=request_images,
                params=params,
            )
            response = await self._stubs["detection"].Predict(request)
            results: list[dict] = []
            is_batch = len(request_images) > 1
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for det_result in response.results:
                    for box in det_result.boxes:
                        item = {
                            "x_min": box.x_min,
                            "y_min": box.y_min,
                            "x_max": box.x_max,
                            "y_max": box.y_max,
                            "confidence": box.confidence,
                            "class_id": box.class_id,
                            "label": box.label,
                        }
                        if is_batch:
                            item["image_id"] = det_result.image_id
                        results.append(item)
            return results
        except grpc.aio.AioRpcError as exc:
            logger.error("Detection gRPC error: {} - {}", exc.code(), exc.details())
            return []
        except Exception as exc:
            logger.error("Detection unexpected error: {}", exc)
            return []

    # ── Classification / 分类 ────────────────────────────────────────────────

    async def classify(
        self,
        shape: tuple[int, ...] | None,
        model_name: str,
        image_roi: list[dict] | None = None,
        *,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
        images: list[dict] | None = None,
    ) -> list[dict]:
        """Async image classification. 异步图像分类。

        Pass either single-image args (*shape* + *image_bytes*/*image_key*), or
        ``images=[{shape, image_bytes|image_key, roi?}, ...]`` for a
        batched request.
        既支持单图参数（*shape* + *image_bytes*/*image_key*），也支持
        ``images=[{shape, image_bytes|image_key, roi?}, ...]`` 的批量请求。

        *image_roi* (single-image) or per-item ``roi`` (batch) is the
        per-image crop region placed in ``Image.region_of_interest``.
        The server crops the input image to this region before feeding it
        to the classifier (pre-processing).
        *image_roi*（单图）或每项的 ``roi``（批量）是逐图裁剪区域，
        放入 ``Image.region_of_interest``。服务端在将图像送入分类器前
        裁剪到此区域（前处理）。

        Returns list of {label, confidence, class_id}. Batched responses also
        include ``image_id`` to identify which input image/ROI produced the
        result.
        返回 {label, confidence, class_id} 列表。批量请求时还会附带 ``image_id``，
        以标识结果对应的输入图像/ROI。
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("classification", False):
            return []
        try:
            request_images = self._make_images(
                shape=shape,
                image_roi=image_roi,
                image_bytes=image_bytes,
                image_key=image_key,
                images=images,
            )
            if not request_images:
                return []
            params = classification_service_pb2.ClassificationParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    # Classification uses image_roi: the server crops the input
                    # image to the ROI region before feeding it to the model
                    # (pre-processing).
                    # 分类使用 image_roi：服务端在将图像送入模型前裁剪到 ROI 区域
                    #（前处理）。
                    use_image_roi=any(bool(img.region_of_interest.points) for img in request_images),
                )
            )
            request = classification_service_pb2.ClassificationRequest(
                request_header=self._make_header(),
                images=request_images,
                params=params,
            )
            response = await self._stubs["classification"].Predict(request)
            results: list[dict] = []
            is_batch = len(request_images) > 1
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.results:
                    item = {
                        "label": res.label,
                        "confidence": res.confidence,
                        "class_id": res.class_id,
                    }
                    if is_batch:
                        item["image_id"] = res.image_id
                    results.append(item)
            return results
        except grpc.aio.AioRpcError as exc:
            logger.error(
                "Classification gRPC error: {} - {}", exc.code(), exc.details()
            )
            return []
        except Exception as exc:
            logger.error("Classification unexpected error: {}", exc)
            return []

    # ── OCR / 文字识别 ──────────────────────────────────────────────────────

    async def ocr(
        self,
        shape: tuple[int, ...] | None,
        model_name: str,
        conf: float = 0.5,
        image_roi: list[dict] | None = None,
        *,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
        images: list[dict] | None = None,
    ) -> list[dict]:
        """Async OCR. 异步文字识别。

        Pass either single-image args (*shape* + *image_bytes*/*image_key*), or
        ``images=[{shape, image_bytes|image_key, roi?}, ...]`` for a
        batched request.
        既支持单图参数（*shape* + *image_bytes*/*image_key*），也支持
        ``images=[{shape, image_bytes|image_key, roi?}, ...]`` 的批量请求。

        *image_roi* (single-image) or per-item ``roi`` (batch) is the
        per-image crop region placed in ``Image.region_of_interest``.
        The server crops the input image to this region before OCR
        (pre-processing).
        *image_roi*（单图）或每项的 ``roi``（批量）是逐图裁剪区域，
        放入 ``Image.region_of_interest``。服务端在 OCR 前裁剪到此区域
        （前处理）。

        Returns list of {text, confidence, points}. Batched responses also
        include ``image_id`` to identify which input image produced the result.
        返回 {text, confidence, points} 列表。批量请求时还会附带 ``image_id``。
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("ocr", False):
            return []
        try:
            request_images = self._make_images(
                shape=shape,
                image_roi=image_roi,
                image_bytes=image_bytes,
                image_key=image_key,
                images=images,
            )
            if not request_images:
                return []
            params = ocr_service_pb2.OCRParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    use_image_roi=any(bool(img.region_of_interest.points) for img in request_images),
                ),
                confidence_threshold=conf,
            )
            request = ocr_service_pb2.OCRRequest(
                request_header=self._make_header(),
                images=request_images,
                params=params,
            )
            response = await self._stubs["ocr"].Predict(request)
            results: list[dict] = []
            is_batch = len(request_images) > 1
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for ocr_result in response.results:
                    for block in ocr_result.blocks:
                        item = {
                            "text": block.text,
                            "confidence": block.confidence,
                            "points": [
                                {"x": p.x, "y": p.y} for p in block.points
                            ],
                            "language": block.language,
                        }
                        if is_batch:
                            item["image_id"] = ocr_result.image_id
                        results.append(item)
            return results
        except grpc.aio.AioRpcError as exc:
            logger.error("OCR gRPC error: {} - {}", exc.code(), exc.details())
            return []
        except Exception as exc:
            logger.error("OCR unexpected error: {}", exc)
            return []

    # ── Action Recognition / 行为识别 ────────────────────────────────────────

    async def recognize_action(
        self,
        model_name: str,
        frames_bytes: list[bytes] | None = None,
        shapes: list[tuple[int, ...]] | None = None,
        image_roi: list[dict] | None = None,
        *,
        image_key: str | None = None,
        image_keys: list[str] | None = None,
        images: list[dict] | None = None,
        sequences: list[dict | list[dict]] | None = None,
    ) -> list[dict]:
        """Async action recognition. 异步行为识别。

        Supports the legacy single-sequence API (*frames_bytes* + *shapes*), a
        single-sequence ``images=[...]`` API, and a batched
        ``sequences=[{images:[...]}, ...]`` API. Cache keys may be supplied via
        ``image_keys`` / ``image_key`` or inside the ``images`` items.
        支持原有单序列 API（*frames_bytes* + *shapes*），也支持单序列
        ``images=[...]`` 以及批量 ``sequences=[{images:[...]}, ...]``。

        *image_roi* is the per-image crop region placed in
        ``Image.region_of_interest`` (pre-processing).
        *image_roi* 是逐图裁剪区域，放入 ``Image.region_of_interest``（前处理）。

        Returns list of {label, confidence, class_id}. Batched sequence
        responses also include ``sequence_id``.
        返回 {label, confidence, class_id} 列表。批量序列请求时还会附带
        ``sequence_id``。
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("action", False):
            return []
        try:
            request_sequences = self._make_sequences(
                frames_bytes=frames_bytes,
                shapes=shapes,
                image_roi=image_roi,
                image_key=image_key,
                image_keys=image_keys,
                images=images,
                sequences=sequences,
            )
            if not request_sequences:
                return []
            params = action_service_pb2.ActionParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    use_image_roi=any(
                        bool(img.region_of_interest.points)
                        for sequence in request_sequences
                        for img in sequence.images
                    ),
                )
            )
            request = action_service_pb2.ActionRequest(
                request_header=self._make_header(),
                sequences=request_sequences,
                params=params,
            )
            response = await self._stubs["action"].Predict(request)
            results: list[dict] = []
            is_batch = len(request_sequences) > 1
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.results:
                    item = {
                        "label": res.label,
                        "confidence": res.confidence,
                        "class_id": res.class_id,
                    }
                    if is_batch:
                        item["sequence_id"] = res.sequence_id
                    results.append(item)
            return results
        except grpc.aio.AioRpcError as exc:
            logger.error("Action gRPC error: {} - {}", exc.code(), exc.details())
            return []
        except Exception as exc:
            logger.error("Action unexpected error: {}", exc)
            return []

    # ── Upload / 上传 ────────────────────────────────────────────────────────

    async def upload_image(self, image_bytes: bytes, filename: str = "image.jpg") -> list[dict]:
        """Async image upload. 异步图像上传。

        Returns list of {key, hit, id, size}.
        Returns empty list when service is disabled.
        服务禁用时返回空列表。

        The latest upload proto accepts ``repeated base.Image`` and no longer
        includes a filename field.  ``filename`` remains in the Python API for
        backward compatibility but is not transmitted.
        最新上传 proto 接收 ``repeated base.Image``，不再包含文件名字段。
        Python API 中保留 ``filename`` 仅为了向后兼容，但不会实际发送。
        """
        if not self._enabled.get("upload", False):
            return []
        try:
            request = upload_service_pb2.UploadImageRequest(
                request_header=self._make_header(),
                images=[
                    base_pb2.Image(
                        data=image_bytes,
                        id=0,
                        enable_cache=True,
                    )
                ],
            )
            response = await self._stubs["upload"].UploadImage(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.cache_infos:
                    results.append(
                        {
                            "key": res.key,
                            "hit": res.hit,
                            "id": res.id,
                            "size": res.size,
                        }
                    )
            return results
        except grpc.aio.AioRpcError as exc:
            logger.error("Upload image gRPC error: {} - {}", exc.code(), exc.details())
            return []
        except Exception as exc:
            logger.error("Upload image unexpected error: {}", exc)
            return []

    async def upload_video(self, video_bytes: bytes, filename: str = "video.mp4") -> list[dict]:
        """Async video upload. 异步视频上传。

        Returns list of {key, hit, id, size}.
        Returns empty list when service is disabled.
        服务禁用时返回空列表。

        The latest upload proto accepts ``repeated base.Video`` and no longer
        includes a filename field.  ``filename`` remains in the Python API for
        backward compatibility but is not transmitted.
        最新上传 proto 接收 ``repeated base.Video``，不再包含文件名字段。
        Python API 中保留 ``filename`` 仅为了向后兼容，但不会实际发送。
        """
        if not self._enabled.get("upload", False):
            return []
        try:
            request = upload_service_pb2.UploadVideoRequest(
                request_header=self._make_header(),
                videos=[
                    base_pb2.Video(
                        data=video_bytes,
                        id=0,
                    )
                ],
            )
            response = await self._stubs["upload"].UploadVideo(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.cache_infos:
                    results.append(
                        {
                            "key": res.key,
                            "hit": res.hit,
                            "id": res.id,
                            "size": res.size,
                        }
                    )
            return results
        except grpc.aio.AioRpcError as exc:
            logger.error("Upload video gRPC error: {} - {}", exc.code(), exc.details())
            return []
        except Exception as exc:
            logger.error("Upload video unexpected error: {}", exc)
            return []

    # ── Model Management / 模型管理 ──────────────────────────────────────────

    async def load_model(
        self,
        service: str,
        model_name: str,
        model_version: str,
        device_id: int = 0,
        set_default: bool = False,
    ) -> dict:
        """Load a model on the specified V-Engine service.
        在指定的 V-Engine 服务上加载模型。

        Returns a summary containing request echo fields and response status.
        返回包含请求回显字段和响应状态的摘要。
        """
        try:
            stub = self._stubs.get(service)
            if stub is None:
                return {"error": f"Unknown service: {service}"}
            request = base_pb2.LoadModelRequest(
                request_header=self._make_header(),
                model_name=model_name,
                model_version=model_version,
                device_id=device_id,
                set_as_default=set_default,
            )
            response = await stub.LoadModel(request)
            return {
                "model_name": model_name,
                "model_version": model_version,
                "device_id": device_id,
                "set_as_default": set_default,
                "status_code": response.response_header.status_code,
                "error_message": response.response_header.error_message,
                # Backward-compatible aliases / 向后兼容别名
                "name": model_name,
                "version": model_version,
            }
        except grpc.aio.AioRpcError as exc:
            logger.error("LoadModel gRPC error: {} - {}", exc.code(), exc.details())
            return {"error": str(exc.details())}
        except Exception as exc:
            logger.error("LoadModel unexpected error: {}", exc)
            return {"error": str(exc)}

    async def unload_model(
        self,
        service: str,
        model_name: str,
        model_version: str,
        device_id: int = 0,
    ) -> dict:
        """Unload a model from the specified V-Engine service.
        从指定的 V-Engine 服务卸载模型。"""
        try:
            stub = self._stubs.get(service)
            if stub is None:
                return {"error": f"Unknown service: {service}"}
            request = base_pb2.UnloadModelRequest(
                request_header=self._make_header(),
                model_name=model_name,
                model_version=model_version,
                device_id=device_id,
            )
            response = await stub.UnloadModel(request)
            return {
                "model_name": model_name,
                "model_version": model_version,
                "device_id": device_id,
                "status_code": response.response_header.status_code,
                "error_message": response.response_header.error_message,
                # Backward-compatible aliases / 向后兼容别名
                "name": model_name,
                "version": model_version,
            }
        except grpc.aio.AioRpcError as exc:
            logger.error("UnloadModel gRPC error: {} - {}", exc.code(), exc.details())
            return {"error": str(exc.details())}
        except Exception as exc:
            logger.error("UnloadModel unexpected error: {}", exc)
            return {"error": str(exc)}

    async def list_models(self, service: str, name_filter: str = "") -> list[dict]:
        """List loaded models on the specified V-Engine service.
        列出指定 V-Engine 服务上已加载的模型。"""
        try:
            stub = self._stubs.get(service)
            if stub is None:
                return []
            request = base_pb2.ListModelsRequest(
                request_header=self._make_header(),
                model_name_filter=name_filter,
            )
            response = await stub.ListModels(request)
            models: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for mi in response.models:
                    models.append(
                        {
                            "model_name": mi.model_name,
                            "model_version": mi.model_version,
                            "device_id": mi.device_id,
                            "is_default": mi.is_default,
                            "status": mi.status,
                            # Backward-compatible aliases / 向后兼容别名
                            "name": mi.model_name,
                            "version": mi.model_version,
                        }
                    )
            return models
        except grpc.aio.AioRpcError as exc:
            logger.error("ListModels gRPC error: {} - {}", exc.code(), exc.details())
            return []
        except Exception as exc:
            logger.error("ListModels unexpected error: {}", exc)
            return []

    async def health_check(self, service: str) -> dict:
        """Health check for a V-Engine service.
        V-Engine 服务健康检查。"""
        try:
            stub = self._stubs.get(service)
            if stub is None:
                return {"error": f"Unknown service: {service}"}
            request = base_pb2.HealthCheckRequest()
            response = await stub.HealthCheck(request)
            return {
                "status": response.status,
                "uptime_seconds": response.uptime_seconds,
                "loaded_model_count": response.loaded_model_count,
            }
        except grpc.aio.AioRpcError as exc:
            logger.error(
                "HealthCheck gRPC error for {}: {} - {}", service, exc.code(), exc.details()
            )
            return {"error": str(exc.details())}
        except Exception as exc:
            logger.error("HealthCheck unexpected error: {}", exc)
            return {"error": str(exc)}
