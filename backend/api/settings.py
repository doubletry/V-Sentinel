from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger

from backend.db import database as db
from backend.models.schemas import (
    AppSettingsUpdate,
    EmailTestRequest,
    PluginRuntimeConfigUpdate,
)
from backend.processing.plugin_config import (
    build_plugin_runtime_config_response,
    normalize_plugin_config,
)

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
    previous_settings = await db.get_all_settings()
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return previous_settings

    result = await db.update_settings(updates)
    if any(
        key in updates
        for key in ("mediamtx_rtsp_addr", "mediamtx_username", "mediamtx_password")
    ):
        await db.sync_source_rtsp_urls_with_settings(previous_settings, result)

    request.app.title = result.get("site_title") or request.app.title
    if "message_retention_days" in updates:
        try:
            await db.prune_analysis_messages(int(result.get("message_retention_days", "7")))
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid message retention days while pruning: {}", exc)

    # Reconnect V-Engine client with new addresses / 使用新地址重连 V-Engine 客户端
    vengine_client = request.app.state.vengine_client
    await vengine_client.reconnect_from_settings(result)
    email_client = request.app.state.email_client
    await email_client.reconnect_from_settings(result)
    request.app.state.processor_manager.update_app_settings(result)

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


@router.get("/plugin-runtime-config")
async def get_plugin_runtime_config(plugin: str = Query(..., min_length=1)) -> dict:
    """Get runtime config metadata and values for a processor plugin.
    获取处理器插件的运行时配置元数据与当前值。"""
    try:
        return await build_plugin_runtime_config_response(plugin)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/plugin-runtime-config")
async def update_plugin_runtime_config(
    data: PluginRuntimeConfigUpdate,
    request: Request,
    plugin: str = Query(..., min_length=1),
) -> dict:
    """Save validated runtime config for a processor plugin.
    保存已校验的处理器插件运行时配置。"""
    try:
        normalized = normalize_plugin_config(plugin, data.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.save_plugin_runtime_config(plugin, normalized)
    settings = await db.get_all_settings()
    request.app.state.processor_manager.update_app_settings(settings)
    return await build_plugin_runtime_config_response(plugin)


@router.get("/plugin-label-candidates")
async def get_plugin_label_candidates(plugin: str = Query(..., min_length=1)) -> dict:
    """Get merged action-label candidates for a processor plugin.
    获取处理器插件合并后的动作标签候选。"""
    try:
        response = await build_plugin_runtime_config_response(plugin)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "plugin": plugin,
        "label_candidates": response["label_candidates"],
    }
