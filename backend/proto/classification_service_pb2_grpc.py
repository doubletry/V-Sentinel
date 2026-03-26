# -*- coding: utf-8 -*-
# gRPC stub for ImageClassification service
from __future__ import annotations

import grpc
import grpc.aio


class ImageClassificationStub:
    """Async gRPC stub for ImageClassification service."""

    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.Predict = channel.unary_unary(
            "/classification.ImageClassification/Predict",
            request_serializer=None,
            response_deserializer=None,
        )
        self.LoadModel = channel.unary_unary(
            "/classification.ImageClassification/LoadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.UnloadModel = channel.unary_unary(
            "/classification.ImageClassification/UnloadModel",
            request_serializer=None,
            response_deserializer=None,
        )
        self.ListModels = channel.unary_unary(
            "/classification.ImageClassification/ListModels",
            request_serializer=None,
            response_deserializer=None,
        )
        self.HealthCheck = channel.unary_unary(
            "/classification.ImageClassification/HealthCheck",
            request_serializer=None,
            response_deserializer=None,
        )
