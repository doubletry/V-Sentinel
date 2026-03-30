# -*- coding: utf-8 -*-
# gRPC stub for OpticalCharacterRecognition service
# OCR 服务的 gRPC 存根
from __future__ import annotations

import grpc
import grpc.aio


class OpticalCharacterRecognitionStub:
    """Async gRPC stub for OpticalCharacterRecognition service.
    OCR 服务的异步 gRPC 存根。"""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.Predict = channel.unary_unary(
            "/ocr.OpticalCharacterRecognition/Predict",
            request_serializer=None,
            response_deserializer=None,
        )
        self.LoadModel = channel.unary_unary(
            "/ocr.OpticalCharacterRecognition/LoadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.UnloadModel = channel.unary_unary(
            "/ocr.OpticalCharacterRecognition/UnloadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.ListModels = channel.unary_unary(
            "/ocr.OpticalCharacterRecognition/ListModels",
            request_serializer=None,
            response_deserializer=None,
        )
        self.HealthCheck = channel.unary_unary(
            "/ocr.OpticalCharacterRecognition/HealthCheck",
            request_serializer=None,
            response_deserializer=None,
        )
