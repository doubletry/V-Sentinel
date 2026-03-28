# -*- coding: utf-8 -*-
# gRPC stub for ObjectDetection service
from __future__ import annotations

import grpc
import grpc.aio

from backend.proto import detection_service_pb2 as _detection_pb2


class ObjectDetectionStub:
    """Async gRPC stub for ObjectDetection service."""

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


class ObjectDetectionServicer:
    """Base class for ObjectDetection servicer."""

    async def Predict(self, request, context):
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented!")
        raise NotImplementedError("Method not implemented!")


def add_ObjectDetectionServicer_to_server(servicer, server):
    from grpc import unary_unary_rpc_method_handler as _handler
    from grpc import method_service_handler as _method_handler  # noqa: F401
    server.add_generic_rpc_handlers(())
