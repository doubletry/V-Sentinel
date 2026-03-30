# -*- coding: utf-8 -*-
# gRPC stub for Upload service
# 上传服务的 gRPC 存根
from __future__ import annotations

import grpc
import grpc.aio


class UploadStub:
    """Async gRPC stub for Upload service.
    上传服务的异步 gRPC 存根。"""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.UploadImage = channel.unary_unary(
            "/upload.Upload/UploadImage",
            request_serializer=None,
            response_deserializer=None,
        )
        self.UploadVideo = channel.unary_unary(
            "/upload.Upload/UploadVideo",
            request_serializer=None,
            response_deserializer=None,
        )
        self.HealthCheck = channel.unary_unary(
            "/upload.Upload/HealthCheck",
            request_serializer=None,
            response_deserializer=None,
        )
