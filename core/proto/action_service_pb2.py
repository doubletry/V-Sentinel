# -*- coding: utf-8 -*-
# Generated stubs for action_service.proto
# 行为识别服务的生成存根
from __future__ import annotations

from core.proto.base_pb2 import _SimpleMessage, ResponseHeader, ImageCacheInfo


class ActionParams(_SimpleMessage):
    def __init__(self, base=None) -> None:
        self.base = base


class ActionResult(_SimpleMessage):
    def __init__(
        self,
        label: str = "",
        confidence: float = 0.0,
        sequence_id: int = 0,
        cache_info: ImageCacheInfo | None = None,
        class_id: int = 0,
    ) -> None:
        self.label = label
        self.confidence = confidence
        self.sequence_id = sequence_id
        self.cache_info = cache_info or ImageCacheInfo()
        self.class_id = class_id


class ActionRequest(_SimpleMessage):
    def __init__(
        self,
        request_header=None,
        sequences: list | None = None,
        params: ActionParams | None = None,
    ) -> None:
        self.request_header = request_header
        self.sequences = sequences or []
        self.params = params or ActionParams()


class ActionResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        results: list | None = None,
    ) -> None:
        self.response_header = response_header or ResponseHeader()
        self.results: list[ActionResult] = results or []
