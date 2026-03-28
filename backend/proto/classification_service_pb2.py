# -*- coding: utf-8 -*-
# Generated stubs for classification_service.proto
from __future__ import annotations

from backend.proto.base_pb2 import _SimpleMessage, ResponseHeader, ImageCacheInfo


class ClassificationParams(_SimpleMessage):
    def __init__(self, base=None) -> None:
        self.base = base


class ClassificationResult(_SimpleMessage):
    def __init__(
        self,
        label: str = "",
        confidence: float = 0.0,
        image_id: int = 0,
        cache_info: ImageCacheInfo | None = None,
        class_id: int = 0,
    ) -> None:
        self.label = label
        self.confidence = confidence
        self.image_id = image_id
        self.cache_info = cache_info or ImageCacheInfo()
        self.class_id = class_id


class ClassificationRequest(_SimpleMessage):
    def __init__(
        self,
        request_header=None,
        images: list | None = None,
        params: ClassificationParams | None = None,
    ) -> None:
        self.request_header = request_header
        self.images = images or []
        self.params = params or ClassificationParams()


class ClassificationResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        results: list | None = None,
    ) -> None:
        self.response_header = response_header or ResponseHeader()
        self.results: list[ClassificationResult] = results or []
