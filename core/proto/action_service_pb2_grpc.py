# -*- coding: utf-8 -*-
# gRPC stub for ActionRecognition service
# 行为识别服务的 gRPC 存根
from __future__ import annotations

import grpc
import grpc.aio


class ActionRecognitionStub:
    """Async gRPC stub for ActionRecognition service.
    行为识别服务的异步 gRPC 存根。"""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.Predict = channel.unary_unary(
            "/action.ActionRecognition/Predict",
            request_serializer=None,
            response_deserializer=None,
        )
        self.LoadModel = channel.unary_unary(
            "/action.ActionRecognition/LoadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.UnloadModel = channel.unary_unary(
            "/action.ActionRecognition/UnloadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.ListModels = channel.unary_unary(
            "/action.ActionRecognition/ListModels",
            request_serializer=None,
            response_deserializer=None,
        )
        self.HealthCheck = channel.unary_unary(
            "/action.ActionRecognition/HealthCheck",
            request_serializer=None,
            response_deserializer=None,
        )
