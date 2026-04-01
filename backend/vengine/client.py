"""Backend V-Engine client — re-exports from ``core.vengine_client``.
后台 V-Engine 客户端 — 从 ``core.vengine_client`` 重新导出。

The canonical implementation lives in ``core.vengine_client``.
This wrapper adds a thin ``__init__`` that accepts the backend's
pydantic ``Settings`` object for backward compatibility with existing
backend code that passes ``config`` to the constructor.
规范实现位于 ``core.vengine_client``。
此包装器添加了一个接受后台 pydantic ``Settings`` 对象的 ``__init__``，
以保持与现有后台代码的向后兼容。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

# Re-export the canonical class so all existing imports keep working.
# 重新导出规范类，使所有现有导入继续工作。
from core.vengine_client import AsyncVEngineClient as _CoreAsyncVEngineClient

if TYPE_CHECKING:
    from backend.config import Settings


class AsyncVEngineClient(_CoreAsyncVEngineClient):
    """Backend-compatible wrapper around the core AsyncVEngineClient.
    核心 AsyncVEngineClient 的后台兼容包装。

    Accepts an optional ``config`` (pydantic ``Settings``) argument for
    backward compatibility.  When ``connect()`` is called without
    ``app_settings``, falls back to ``backend.config.DEFAULT_APP_SETTINGS``.
    接受可选的 ``config``（pydantic ``Settings``）参数以保持向后兼容。
    当 ``connect()`` 不带 ``app_settings`` 调用时，
    回退到 ``backend.config.DEFAULT_APP_SETTINGS``。
    """

    def __init__(self, config: "Settings | None" = None) -> None:
        super().__init__()
        self._config = config

    async def connect(self, app_settings: dict[str, str] | None = None) -> None:
        """Connect using backend defaults when no settings are provided.
        未提供设置时使用后台默认值连接。"""
        if app_settings is None:
            from backend.config import DEFAULT_APP_SETTINGS
            app_settings = DEFAULT_APP_SETTINGS
        await super().connect(app_settings)
