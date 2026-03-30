from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING

import grpc.aio
from loguru import logger

from backend.proto import (
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

if TYPE_CHECKING:
    from backend.config import Settings


class AsyncVEngineClient:
    """Async gRPC client for all V-Engine services.
    V-Engine 全服务异步 gRPC 客户端。

    All channels are shared across all camera processors.
    HTTP/2 multiplexing handles concurrent requests automatically.
    所有通道在所有摄像头处理器间共享。HTTP/2 多路复用自动处理并发请求。

    Service addresses are read from the DB-backed ``app_settings`` table.
    The ``reconnect_from_settings`` method allows hot-reloading addresses.
    服务地址从数据库 ``app_settings`` 表中读取。
    ``reconnect_from_settings`` 方法允许热重载地址。

    Individual services can be disabled via ``<service>_enabled`` settings.
    When a service is disabled, no channel is created and calling its methods
    returns an empty result gracefully.
    可通过 ``<service>_enabled`` 设置禁用单个服务。禁用后不创建通道，
    调用其方法时会优雅地返回空结果。
    """

    # Names of all V-Engine services / 所有 V-Engine 服务名称
    SERVICE_NAMES = ("detection", "classification", "action", "ocr", "upload")

    def __init__(self, config: "Settings") -> None:
        self._config = config
        self._channels: dict[str, grpc.aio.Channel] = {}
        self._stubs: dict[str, object] = {}
        self._enabled: dict[str, bool] = {s: True for s in self.SERVICE_NAMES}

    # ── Address resolution / 地址解析 ────────────────────────────────────────

    @staticmethod
    def _build_addresses(app_settings: dict[str, str]) -> dict[str, str]:
        """Build ``{service: host:port}`` from DB settings dict.
        从数据库设置字典构建 ``{服务名: 主机:端口}`` 映射。"""
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
        """Parse ``<service>_enabled`` flags from DB settings.
        从数据库设置解析各服务启用/禁用标志。"""
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

        If *app_settings* is ``None``, defaults from ``config.DEFAULT_APP_SETTINGS``
        are used (typically during first startup before DB is ready).
        若 *app_settings* 为 ``None``，则使用默认设置（通常在数据库就绪前首次启动时）。
        """
        from backend.config import DEFAULT_APP_SETTINGS

        if app_settings is None:
            app_settings = DEFAULT_APP_SETTINGS

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
        # Mapping: service name → (stub class, channel address)
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
        """Close all gRPC channels."""
        for name, channel in self._channels.items():
            try:
                await channel.close()
                logger.debug("Closed gRPC channel: {}", name)
            except Exception as exc:  # pragma: no cover
                logger.warning("Error closing channel {}: {}", name, exc)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _make_header(self, client_id: str = "v-sentinel") -> base_pb2.RequestHeader:
        return base_pb2.RequestHeader(
            request_timestamp=time.time(),
            request_id=secrets.token_hex(8),
            client_id=client_id,
        )

    def _make_roi_polygon(
        self, roi_points: list[dict]
    ) -> base_pb2.Polygon:
        """Convert ROI points [{x, y}, ...] to base_pb2.Polygon (pixel coords)."""
        points = [base_pb2.Point(x=float(p["x"]), y=float(p["y"])) for p in roi_points]
        return base_pb2.Polygon(points=points)

    def _make_image(
        self,
        shape: tuple[int, ...],
        roi_points: list[dict] | None = None,
        *,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
    ) -> base_pb2.Image:
        """Build a ``base_pb2.Image`` from either raw bytes **or** a cache key.

        Exactly one of *image_bytes* / *image_key* must be provided.
        """
        if image_bytes is None and image_key is None:
            raise ValueError("Provide either image_bytes or image_key")
        if image_bytes is not None and image_key is not None:
            raise ValueError("Provide only one of image_bytes or image_key, not both")

        image_roi = (
            self._make_roi_polygon(roi_points) if roi_points else base_pb2.Polygon()
        )
        kwargs: dict = {
            "id": 0,
            "shape": base_pb2.ShapeInfo(dims=list(shape)),
            "region_of_interest": image_roi,
        }
        if image_bytes is not None:
            kwargs["data"] = image_bytes
        else:
            kwargs["key"] = image_key
        return base_pb2.Image(**kwargs)

    # ── Upload + cache key / 上传与缓存键 ────────────────────────────────────

    async def upload_and_get_key(self, image_bytes: bytes, filename: str = "frame.jpg") -> str | None:
        """Upload an image to the cache and return its key.
        上传图像到缓存并返回其键。

        Returns ``None`` if upload service is disabled or on failure.
        若上传服务被禁用或失败，则返回 ``None``。
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
        shape: tuple[int, ...],
        model_name: str,
        conf: float = 0.5,
        nms: float = 0.7,
        roi_points: list[dict] | None = None,
        *,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
    ) -> list[dict]:
        """Async object detection. 异步目标检测。

        Pass either *image_bytes* (raw JPEG) or *image_key* (cache key from upload).
        传入 *image_bytes*（原始 JPEG）或 *image_key*（上传后的缓存键）。
        Returns list of {x_min, y_min, x_max, y_max, confidence, class_id, label}.
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("detection", False):
            return []
        try:
            image = self._make_image(shape, roi_points, image_bytes=image_bytes, image_key=image_key)
            params = detection_service_pb2.DetectionParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    use_image_roi=bool(roi_points),
                ),
                confidence_threshold=conf,
                nms_iou_threshold=nms,
            )
            request = detection_service_pb2.DetectionRequest(
                request_header=self._make_header(),
                images=[image],
                params=params,
            )
            response = await self._stubs["detection"].Predict(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for det_result in response.results:
                    for box in det_result.boxes:
                        results.append(
                            {
                                "x_min": box.x_min,
                                "y_min": box.y_min,
                                "x_max": box.x_max,
                                "y_max": box.y_max,
                                "confidence": box.confidence,
                                "class_id": box.class_id,
                                "label": box.label,
                            }
                        )
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
        shape: tuple[int, ...],
        model_name: str,
        roi_points: list[dict] | None = None,
        *,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
    ) -> list[dict]:
        """Async image classification. 异步图像分类。

        Returns list of {label, confidence, class_id}.
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("classification", False):
            return []
        try:
            image = self._make_image(shape, roi_points, image_bytes=image_bytes, image_key=image_key)
            params = classification_service_pb2.ClassificationParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    use_image_roi=bool(roi_points),
                )
            )
            request = classification_service_pb2.ClassificationRequest(
                request_header=self._make_header(),
                images=[image],
                params=params,
            )
            response = await self._stubs["classification"].Predict(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.results:
                    results.append(
                        {
                            "label": res.label,
                            "confidence": res.confidence,
                            "class_id": res.class_id,
                        }
                    )
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
        shape: tuple[int, ...],
        model_name: str,
        conf: float = 0.5,
        roi_points: list[dict] | None = None,
        *,
        image_bytes: bytes | None = None,
        image_key: str | None = None,
    ) -> list[dict]:
        """Async OCR. 异步文字识别。

        Returns list of {text, confidence, points}.
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("ocr", False):
            return []
        try:
            image = self._make_image(shape, roi_points, image_bytes=image_bytes, image_key=image_key)
            params = ocr_service_pb2.OCRParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    use_image_roi=bool(roi_points),
                ),
                confidence_threshold=conf,
            )
            request = ocr_service_pb2.OCRRequest(
                request_header=self._make_header(),
                images=[image],
                params=params,
            )
            response = await self._stubs["ocr"].Predict(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for ocr_result in response.results:
                    for block in ocr_result.blocks:
                        results.append(
                            {
                                "text": block.text,
                                "confidence": block.confidence,
                                "points": [
                                    {"x": p.x, "y": p.y} for p in block.points
                                ],
                                "language": block.language,
                            }
                        )
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
        frames_bytes: list[bytes],
        shapes: list[tuple[int, ...]],
        model_name: str,
        roi_points: list[dict] | None = None,
    ) -> list[dict]:
        """Async action recognition. 异步行为识别。

        Returns list of {label, confidence, class_id}.
        Returns empty list when service is disabled.
        服务禁用时返回空列表。
        """
        if not self._enabled.get("action", False):
            return []
        try:
            images = [
                base_pb2.Image(
                    data=data,
                    id=idx,
                    shape=base_pb2.ShapeInfo(dims=list(shape)),
                )
                for idx, (data, shape) in enumerate(zip(frames_bytes, shapes))
            ]
            if roi_points:
                roi_polygon = self._make_roi_polygon(roi_points)
                for img in images:
                    img.region_of_interest = roi_polygon

            sequence = base_pb2.ImageSequence(images=images, sequence_id=0)
            params = action_service_pb2.ActionParams(
                base=base_pb2.InferenceParams(
                    model_name=model_name,
                    use_image_roi=bool(roi_points),
                )
            )
            request = action_service_pb2.ActionRequest(
                request_header=self._make_header(),
                sequences=[sequence],
                params=params,
            )
            response = await self._stubs["action"].Predict(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.results:
                    results.append(
                        {
                            "label": res.label,
                            "confidence": res.confidence,
                            "class_id": res.class_id,
                        }
                    )
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
        """
        if not self._enabled.get("upload", False):
            return []
        try:
            request = upload_service_pb2.UploadImageRequest(
                request_header=self._make_header(),
                data=image_bytes,
                filename=filename,
            )
            response = await self._stubs["upload"].UploadImage(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.results:
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
        """
        if not self._enabled.get("upload", False):
            return []
        try:
            request = upload_service_pb2.UploadVideoRequest(
                request_header=self._make_header(),
                data=video_bytes,
                filename=filename,
            )
            response = await self._stubs["upload"].UploadVideo(request)
            results: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for res in response.results:
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

    # ── Model Management ──────────────────────────────────────────────────────

    async def load_model(
        self,
        service: str,
        model_name: str,
        model_version: str,
        device_id: int = 0,
        set_default: bool = False,
    ) -> dict:
        """Load a model on the specified V-Engine service.

        Returns {name, version, device_id, is_default, status}.
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
                set_default=set_default,
            )
            response = await stub.LoadModel(request)
            mi = response.model_info
            return {
                "name": mi.name,
                "version": mi.version,
                "device_id": mi.device_id,
                "is_default": mi.is_default,
                "status": mi.status,
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
        """Unload a model from the specified V-Engine service."""
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
            mi = response.model_info
            return {
                "name": mi.name,
                "version": mi.version,
                "device_id": mi.device_id,
                "is_default": mi.is_default,
                "status": mi.status,
            }
        except grpc.aio.AioRpcError as exc:
            logger.error("UnloadModel gRPC error: {} - {}", exc.code(), exc.details())
            return {"error": str(exc.details())}
        except Exception as exc:
            logger.error("UnloadModel unexpected error: {}", exc)
            return {"error": str(exc)}

    async def list_models(self, service: str, name_filter: str = "") -> list[dict]:
        """List loaded models on the specified V-Engine service."""
        try:
            stub = self._stubs.get(service)
            if stub is None:
                return []
            request = base_pb2.ListModelsRequest(
                request_header=self._make_header(),
                name_filter=name_filter,
            )
            response = await stub.ListModels(request)
            models: list[dict] = []
            if response.response_header.status_code == base_pb2.StatusCode.STATUS_OK:
                for mi in response.models:
                    models.append(
                        {
                            "name": mi.name,
                            "version": mi.version,
                            "device_id": mi.device_id,
                            "is_default": mi.is_default,
                            "status": mi.status,
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
        """Health check for a V-Engine service."""
        try:
            stub = self._stubs.get(service)
            if stub is None:
                return {"error": f"Unknown service: {service}"}
            request = base_pb2.HealthCheckRequest(
                request_header=self._make_header()
            )
            response = await stub.HealthCheck(request)
            return {
                "service_name": response.service_name,
                "version": response.version,
                "status_code": response.response_header.status_code,
            }
        except grpc.aio.AioRpcError as exc:
            logger.error(
                "HealthCheck gRPC error for {}: {} - {}", service, exc.code(), exc.details()
            )
            return {"error": str(exc.details())}
        except Exception as exc:
            logger.error("HealthCheck unexpected error: {}", exc)
            return {"error": str(exc)}
