# -*- coding: utf-8 -*-
# Generated stubs for ocr_service.proto
from __future__ import annotations

from backend.proto.base_pb2 import _SimpleMessage, ResponseHeader, ImageCacheInfo, Point


class OCRParams(_SimpleMessage):
    def __init__(
        self,
        base=None,
        confidence_threshold: float = 0.5,
        language_hint: str = "",
    ) -> None:
        self.base = base
        self.confidence_threshold = confidence_threshold
        self.language_hint = language_hint


class TextBlock(_SimpleMessage):
    def __init__(
        self,
        points: list | None = None,
        text: str = "",
        confidence: float = 0.0,
        language: str = "",
    ) -> None:
        self.points: list[Point] = points or []
        self.text = text
        self.confidence = confidence
        self.language = language


class OCRResults(_SimpleMessage):
    def __init__(
        self,
        blocks: list | None = None,
        image_id: int = 0,
        cache_info: ImageCacheInfo | None = None,
    ) -> None:
        self.blocks: list[TextBlock] = blocks or []
        self.image_id = image_id
        self.cache_info = cache_info or ImageCacheInfo()


class OCRRequest(_SimpleMessage):
    def __init__(
        self,
        request_header=None,
        images: list | None = None,
        params: OCRParams | None = None,
    ) -> None:
        self.request_header = request_header
        self.images = images or []
        self.params = params or OCRParams()


class OCRResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        results: list | None = None,
    ) -> None:
        self.response_header = response_header or ResponseHeader()
        self.results: list[OCRResults] = results or []
