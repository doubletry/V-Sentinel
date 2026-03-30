# -*- coding: utf-8 -*-
# gRPC stub for ObjectDetection service
# 目标检测服务的 gRPC 存根
from __future__ import annotations

import grpc
import grpc.aio


class ObjectDetectionStub:
    """Async gRPC stub for ObjectDetection service.
    目标检测服务的异步 gRPC 存根。"""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.Predict = channel.unary_unary(
            "/detection.ObjectDetection/Predict",
            request_serializer=None,
            response_deserializer=None,
        )
        self.LoadModel = channel.unary_unary(
            "/detection.ObjectDetection/LoadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.UnloadModel = channel.unary_unary(
            "/detection.ObjectDetection/UnloadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.ListModels = channel.unary_unary(
            "/detection.ObjectDetection/ListModels",
            request_serializer=None,
            response_deserializer=None,
        )
        self.HealthCheck = channel.unary_unary(
            "/detection.ObjectDetection/HealthCheck",
            request_serializer=None,
            response_deserializer=None,
        )
