# -*- coding: utf-8 -*-
# Generated stubs for detection_service.proto
from __future__ import annotations

from backend.proto.base_pb2 import (  # noqa: F401
    _SimpleMessage,
    ResponseHeader,
    ImageCacheInfo,
)


class BoundingBox(_SimpleMessage):
    def __init__(
        self,
        x_min: float = 0.0,
        y_min: float = 0.0,
        x_max: float = 0.0,
        y_max: float = 0.0,
        confidence: float = 0.0,
        class_id: int = 0,
        label: str = "",
    ) -> None:
        self.x_min = x_min
        self.y_min = y_min
        self.x_max = x_max
        self.y_max = y_max
        self.confidence = confidence
        self.class_id = class_id
        self.label = label


class DetectionParams(_SimpleMessage):
    def __init__(
        self,
        base=None,
        confidence_threshold: float = 0.5,
        nms_iou_threshold: float = 0.7,
    ) -> None:
        self.base = base
        self.confidence_threshold = confidence_threshold
        self.nms_iou_threshold = nms_iou_threshold


class DetectionResults(_SimpleMessage):
    def __init__(
        self,
        names: list | None = None,
        boxes: list | None = None,
        image_id: int = 0,
        cache_info: ImageCacheInfo | None = None,
    ) -> None:
        self.names: list[str] = names or []
        self.boxes: list[BoundingBox] = boxes or []
        self.image_id = image_id
        self.cache_info = cache_info or ImageCacheInfo()


class DetectionRequest(_SimpleMessage):
    def __init__(
        self,
        request_header=None,
        images: list | None = None,
        params: DetectionParams | None = None,
    ) -> None:
        self.request_header = request_header
        self.images = images or []
        self.params = params or DetectionParams()


class DetectionResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        results: list | None = None,
    ) -> None:
        self.response_header = response_header or ResponseHeader()
        self.results: list[DetectionResults] = results or []
