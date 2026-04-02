from __future__ import annotations

from fastapi import APIRouter, Request

from backend.db import database as db
from backend.models.schemas import AppSettingsUpdate, EmailTestRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings() -> dict[str, str]:
    """Get all application settings.
    获取所有应用设置。"""
    return await db.get_all_settings()


@router.put("")
async def update_settings(data: AppSettingsUpdate, request: Request) -> dict[str, str]:
    """Update application settings.
    更新应用设置。

    After saving, the V-Engine gRPC client is reconnected with the new
    addresses so changes take effect immediately.
    保存后重新连接 V-Engine gRPC 客户端以使新地址立即生效。
    """
    # Build dict of only the fields that were actually provided
    # 仅构建实际提供了值的字段字典
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await db.get_all_settings()

    result = await db.update_settings(updates)

    # Reconnect V-Engine client with new addresses / 使用新地址重连 V-Engine 客户端
    vengine_client = request.app.state.vengine_client
    await vengine_client.reconnect_from_settings(result)
    email_client = request.app.state.email_client
    await email_client.reconnect_from_settings(result)

    return result


@router.post("/email/test")
async def test_email_settings(
    data: EmailTestRequest,
    request: Request,
) -> dict[str, str]:
    """Send a test email using current or provided settings.
    使用当前或传入的设置发送测试邮件。"""
    app_settings = await db.get_all_settings()
    overrides = {k: v for k, v in data.model_dump().items() if v is not None}

    merged_settings = {**app_settings, **overrides}
    email_client = request.app.state.email_client
    await email_client.reconnect_from_settings(merged_settings)
    return await email_client.send_test_email(app_settings, overrides=overrides)
