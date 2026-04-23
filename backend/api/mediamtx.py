from __future__ import annotations

from secrets import compare_digest
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db import database as db

router = APIRouter(prefix="/api/mediamtx", tags=["mediamtx"])


class MediaMTXAuthRequest(BaseModel):
    """HTTP auth payload sent by MediaMTX.
    MediaMTX 发来的 HTTP 鉴权请求体。"""

    user: str = ""
    password: str = ""
    token: str = ""
    ip: str = ""
    action: str = ""
    path: str = ""
    protocol: str = ""
    id: str | None = None
    query: str = ""


def _normalize_stream_path(value: str | None) -> str:
    return str(value or "").strip().strip("/")


def _fallback_extract_route_path(rtsp_url: str) -> str | None:
    """Best-effort route extraction for manually entered RTSP URLs.
    为手工录入的 RTSP URL 做尽力而为的路由提取。"""
    full = str(rtsp_url or "").strip()
    if not full:
        return None

    parsed = urlparse(full)
    route = parsed.path.strip("/")
    return unquote(route) if route else None


async def _collect_allowed_paths(rtsp_base_address: str) -> set[str]:
    allowed_paths: set[str] = set()
    for source in await db.list_sources():
        route_path = db._extract_route_path(source.rtsp_url, rtsp_base_address)  # noqa: SLF001
        if not route_path:
            route_path = _fallback_extract_route_path(source.rtsp_url)

        route_path = _normalize_stream_path(route_path)
        if not route_path:
            continue

        allowed_paths.add(route_path)
        allowed_paths.add(f"{route_path}_processed")
    return allowed_paths


def _has_valid_credentials(
    data: MediaMTXAuthRequest,
    app_settings: dict[str, str],
) -> bool:
    expected_username = str(app_settings.get("mediamtx_username", "") or "").strip()
    expected_password = str(app_settings.get("mediamtx_password", "") or "")

    if not expected_username:
        return True

    return compare_digest(str(data.user or ""), expected_username) and compare_digest(
        str(data.password or ""), expected_password
    )


@router.post("/auth")
async def mediamtx_auth(data: MediaMTXAuthRequest) -> dict[str, str]:
    """Authenticate MediaMTX read/publish requests against app settings and sources.
    根据应用设置与已配置视频源校验 MediaMTX 读写请求。"""
    app_settings = await db.get_all_settings()
    if not _has_valid_credentials(data, app_settings):
        raise HTTPException(status_code=401, detail="Invalid MediaMTX credentials")

    requested_path = _normalize_stream_path(data.path)
    if not requested_path:
        raise HTTPException(status_code=401, detail="Missing MediaMTX stream path")

    allowed_paths = await _collect_allowed_paths(
        app_settings.get("mediamtx_rtsp_addr", "")
    )
    if requested_path not in allowed_paths:
        raise HTTPException(status_code=401, detail="Unknown MediaMTX stream path")

    return {"status": "ok"}
