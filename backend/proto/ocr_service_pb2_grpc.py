# -*- coding: utf-8 -*-
# gRPC stub for OpticalCharacterRecognition service
from __future__ import annotations

import grpc
import grpc.aio


class OpticalCharacterRecognitionStub:
    """Async gRPC stub for OpticalCharacterRecognition service."""

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
