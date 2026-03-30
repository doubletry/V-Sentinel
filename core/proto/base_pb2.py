# -*- coding: utf-8 -*-
# Stub protobuf classes for base.proto
# 基础 proto 的存根类（规范位置：core/proto/）
from __future__ import annotations


class StatusCode:
    STATUS_OK = 0
    STATUS_INVALID_REQUEST = 1
    STATUS_MODEL_NOT_FOUND = 2
    STATUS_INFERENCE_ERROR = 3
    STATUS_INTERNAL_ERROR = 4


class _SimpleMessage:
    """Minimal base class for stub protobuf-like message objects."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
        return f"{self.__class__.__name__}({attrs})"


class RequestHeader(_SimpleMessage):
    def __init__(
        self,
        request_timestamp: float = 0.0,
        request_id: str = "",
        client_id: str = "",
    ) -> None:
        self.request_timestamp = request_timestamp
        self.request_id = request_id
        self.client_id = client_id


class ResponseHeader(_SimpleMessage):
    def __init__(
        self,
        request_id: str = "",
        response_timestamp: float = 0.0,
        status_code: int = 0,
        error_message: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        self.request_id = request_id
        self.response_timestamp = response_timestamp
        self.status_code = status_code
        self.error_message = error_message
        self.latency_ms = latency_ms


class Point(_SimpleMessage):
    def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
        self.x = x
        self.y = y


class Polygon(_SimpleMessage):
    def __init__(self, points: list | None = None) -> None:
        self.points: list[Point] = points if points is not None else []


class ShapeInfo(_SimpleMessage):
    def __init__(self, dims: list | None = None) -> None:
        self.dims: list[int] = dims if dims is not None else []


class ImageCacheInfo(_SimpleMessage):
    def __init__(
        self,
        key: str = "",
        hit: bool = False,
        id: str = "",
        size: int = 0,
    ) -> None:
        self.key = key
        self.hit = hit
        self.id = id
        self.size = size


class Image(_SimpleMessage):
    def __init__(
        self,
        data: bytes = b"",
        key: str = "",
        id: int = 0,
        shape: ShapeInfo | None = None,
        region_of_interest: Polygon | None = None,
    ) -> None:
        self.data = data
        self.key = key
        self.id = id
        self.shape = shape if shape is not None else ShapeInfo()
        self.region_of_interest = region_of_interest if region_of_interest is not None else Polygon()


class ImageSequence(_SimpleMessage):
    def __init__(
        self,
        images: list | None = None,
        sequence_id: int = 0,
    ) -> None:
        self.images: list[Image] = images if images is not None else []
        self.sequence_id = sequence_id


class Video(_SimpleMessage):
    def __init__(self, data: bytes = b"", key: str = "") -> None:
        self.data = data
        self.key = key


class InferenceParams(_SimpleMessage):
    def __init__(
        self,
        model_name: str = "",
        model_version: str = "",
        region_of_interest: Polygon | None = None,
        use_image_roi: bool = False,
        use_model_roi: bool = False,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self.region_of_interest = region_of_interest if region_of_interest is not None else Polygon()
        self.use_image_roi = use_image_roi
        self.use_model_roi = use_model_roi


class LoadModelRequest(_SimpleMessage):
    def __init__(
        self,
        request_header: RequestHeader | None = None,
        model_name: str = "",
        model_version: str = "",
        device_id: int = 0,
        set_default: bool = False,
    ) -> None:
        self.request_header = request_header if request_header is not None else RequestHeader()
        self.model_name = model_name
        self.model_version = model_version
        self.device_id = device_id
        self.set_default = set_default


class UnloadModelRequest(_SimpleMessage):
    def __init__(
        self,
        request_header: RequestHeader | None = None,
        model_name: str = "",
        model_version: str = "",
        device_id: int = 0,
    ) -> None:
        self.request_header = request_header if request_header is not None else RequestHeader()
        self.model_name = model_name
        self.model_version = model_version
        self.device_id = device_id


class ModelInfo(_SimpleMessage):
    def __init__(
        self,
        name: str = "",
        version: str = "",
        device_id: int = 0,
        is_default: bool = False,
        status: str = "",
    ) -> None:
        self.name = name
        self.version = version
        self.device_id = device_id
        self.is_default = is_default
        self.status = status


class ModelResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        model_info: ModelInfo | None = None,
    ) -> None:
        self.response_header = response_header if response_header is not None else ResponseHeader()
        self.model_info = model_info if model_info is not None else ModelInfo()


class ListModelsRequest(_SimpleMessage):
    def __init__(
        self,
        request_header: RequestHeader | None = None,
        name_filter: str = "",
    ) -> None:
        self.request_header = request_header if request_header is not None else RequestHeader()
        self.name_filter = name_filter


class ListModelsResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        models: list | None = None,
    ) -> None:
        self.response_header = response_header if response_header is not None else ResponseHeader()
        self.models: list[ModelInfo] = models if models is not None else []


class HealthCheckRequest(_SimpleMessage):
    def __init__(self, request_header: RequestHeader | None = None) -> None:
        self.request_header = request_header if request_header is not None else RequestHeader()


class HealthCheckResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        service_name: str = "",
        version: str = "",
    ) -> None:
        self.response_header = response_header if response_header is not None else ResponseHeader()
        self.service_name = service_name
        self.version = version
