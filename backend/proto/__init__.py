"""Backend proto package — re-exports from ``core.proto``.
后台 proto 包 — 从 ``core.proto`` 重新导出。

The canonical proto stub files live in ``core/proto/``.  This package
re-exports everything so existing ``from backend.proto import ...`` imports
continue to work unchanged.
规范的 proto 存根文件位于 ``core/proto/``。此包重新导出所有内容，
使现有的 ``from backend.proto import ...`` 导入继续正常工作。
"""
# Re-export all proto modules from core / 从 core 重新导出所有 proto 模块
from core.proto import base_pb2  # noqa: F401
from core.proto import base_pb2_grpc  # noqa: F401
from core.proto import detection_service_pb2  # noqa: F401
from core.proto import detection_service_pb2_grpc  # noqa: F401
from core.proto import classification_service_pb2  # noqa: F401
from core.proto import classification_service_pb2_grpc  # noqa: F401
from core.proto import action_service_pb2  # noqa: F401
from core.proto import action_service_pb2_grpc  # noqa: F401
from core.proto import ocr_service_pb2  # noqa: F401
from core.proto import ocr_service_pb2_grpc  # noqa: F401
from core.proto import upload_service_pb2  # noqa: F401
from core.proto import upload_service_pb2_grpc  # noqa: F401
