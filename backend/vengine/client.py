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

    All channels are shared across all camera processors.
    HTTP/2 multiplexing handles concurrent requests automatically.

    Service addresses are read from the DB-backed ``app_settings`` table.
    The ``reconnect_from_settings`` method allows hot-reloading addresses.
    """

    def __init__(self, config: "Settings") -> None:
        self._config = config
        self._channels: dict[str, grpc.aio.Channel] = {}
        self._stubs: dict[str, object] = {}

    # ── Address resolution ────────────────────────────────────────────────────

    @staticmethod
    def _build_addresses(app_settings: dict[str, str]) -> dict[str, str]:
        """Build ``{service: host:port}`` from DB settings dict."""
        host = app_settings.get("vengine_host", "localhost")
        return {
            "detection": f"{host}:{app_settings.get('detection_port', '50051')}",
            "classification": f"{host}:{app_settings.get('classification_port', '50052')}",
            "action": f"{host}:{app_settings.get('action_port', '50053')}",
            "ocr": f"{host}:{app_settings.get('ocr_port', '50054')}",
            "upload": f"{host}:{app_settings.get('upload_port', '50050')}",
        }

    # ── Connect / reconnect ───────────────────────────────────────────────────

    async def connect(self, app_settings: dict[str, str] | None = None) -> None:
        """Create grpc.aio channels and stubs for all services.

        If *app_settings* is ``None``, defaults from ``config.DEFAULT_APP_SETTINGS``
        are used (typically during first startup before DB is ready).
        """
        from backend.config import DEFAULT_APP_SETTINGS

        if app_settings is None:
            app_settings = DEFAULT_APP_SETTINGS

        addrs = self._build_addresses(app_settings)
        self._create_channels_and_stubs(addrs)
        logger.info("AsyncVEngineClient connected to all V-Engine services")

    async def reconnect_from_settings(self, app_settings: dict[str, str]) -> None:
        """Close existing channels and reconnect with new addresses."""
        await self.close()
        await self.connect(app_settings)
        logger.info("AsyncVEngineClient reconnected with updated settings")

    def _create_channels_and_stubs(self, addrs: dict[str, str]) -> None:
        self._channels["detection"] = grpc.aio.insecure_channel(addrs["detection"])
        self._channels["classification"] = grpc.aio.insecure_channel(addrs["classification"])
        self._channels["action"] = grpc.aio.insecure_channel(addrs["action"])
        self._channels["ocr"] = grpc.aio.insecure_channel(addrs["ocr"])
        self._channels["upload"] = grpc.aio.insecure_channel(addrs["upload"])

        self._stubs["detection"] = detection_service_pb2_grpc.ObjectDetectionStub(
            self._channels["detection"]
        )
        self._stubs[
            "classification"
        ] = classification_service_pb2_grpc.ImageClassificationStub(
            self._channels["classification"]
        )
        self._stubs["action"] = action_service_pb2_grpc.ActionRecognitionStub(
            self._channels["action"]
        )
        self._stubs[
            "ocr"
        ] = ocr_service_pb2_grpc.OpticalCharacterRecognitionStub(
            self._channels["ocr"]
        )
        self._stubs["upload"] = upload_service_pb2_grpc.UploadStub(
            self._channels["upload"]
        )

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

    # ── Detection ─────────────────────────────────────────────────────────────

    async def detect(
        self,
        image_bytes: bytes,
        shape: tuple[int, ...],
        model_name: str,
        conf: float = 0.5,
        nms: float = 0.7,
        roi_points: list[dict] | None = None,
    ) -> list[dict]:
        """Async object detection.

        Returns list of {x_min, y_min, x_max, y_max, confidence, class_id, label}.
        """
        try:
            image_roi = (
                self._make_roi_polygon(roi_points)
                if roi_points
                else base_pb2.Polygon()
            )
            image = base_pb2.Image(
                data=image_bytes,
                id=0,
                shape=base_pb2.ShapeInfo(dims=list(shape)),
                region_of_interest=image_roi,
            )
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

    # ── Classification ────────────────────────────────────────────────────────

    async def classify(
        self,
        image_bytes: bytes,
        shape: tuple[int, ...],
        model_name: str,
        roi_points: list[dict] | None = None,
    ) -> list[dict]:
        """Async image classification.

        Returns list of {label, confidence, class_id}.
        """
        try:
            image_roi = (
                self._make_roi_polygon(roi_points)
                if roi_points
                else base_pb2.Polygon()
            )
            image = base_pb2.Image(
                data=image_bytes,
                id=0,
                shape=base_pb2.ShapeInfo(dims=list(shape)),
                region_of_interest=image_roi,
            )
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

    # ── OCR ───────────────────────────────────────────────────────────────────

    async def ocr(
        self,
        image_bytes: bytes,
        shape: tuple[int, ...],
        model_name: str,
        conf: float = 0.5,
        roi_points: list[dict] | None = None,
    ) -> list[dict]:
        """Async OCR.

        Returns list of {text, confidence, points}.
        """
        try:
            image_roi = (
                self._make_roi_polygon(roi_points)
                if roi_points
                else base_pb2.Polygon()
            )
            image = base_pb2.Image(
                data=image_bytes,
                id=0,
                shape=base_pb2.ShapeInfo(dims=list(shape)),
                region_of_interest=image_roi,
            )
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

    # ── Action Recognition ────────────────────────────────────────────────────

    async def recognize_action(
        self,
        frames_bytes: list[bytes],
        shapes: list[tuple[int, ...]],
        model_name: str,
        roi_points: list[dict] | None = None,
    ) -> list[dict]:
        """Async action recognition.

        Returns list of {label, confidence, class_id}.
        """
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

    # ── Upload ────────────────────────────────────────────────────────────────

    async def upload_image(self, image_bytes: bytes, filename: str = "image.jpg") -> list[dict]:
        """Async image upload.

        Returns list of {key, hit, id, size}.
        """
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
        """Async video upload.

        Returns list of {key, hit, id, size}.
        """
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
