# -*- coding: utf-8 -*-
# Generated stubs for upload_service.proto
from __future__ import annotations

from backend.proto.base_pb2 import _SimpleMessage, ResponseHeader


class UploadImageRequest(_SimpleMessage):
    def __init__(
        self,
        request_header=None,
        data: bytes = b"",
        filename: str = "",
    ) -> None:
        self.request_header = request_header
        self.data = data
        self.filename = filename


class UploadVideoRequest(_SimpleMessage):
    def __init__(
        self,
        request_header=None,
        data: bytes = b"",
        filename: str = "",
    ) -> None:
        self.request_header = request_header
        self.data = data
        self.filename = filename


class UploadResult(_SimpleMessage):
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


class UploadResponse(_SimpleMessage):
    def __init__(
        self,
        response_header: ResponseHeader | None = None,
        results: list | None = None,
    ) -> None:
        self.response_header = response_header or ResponseHeader()
        self.results: list[UploadResult] = results or []
