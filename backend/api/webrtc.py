from __future__ import annotations

import base64

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from backend.db.database import get_all_settings

router = APIRouter(prefix="/api/webrtc", tags=["webrtc"])


def _build_basic_auth_header(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode("utf-8")
    token = base64.b64encode(raw).decode("ascii")
    return f"Basic {token}"


@router.post("/{stream_path:path}/whep")
async def proxy_whep_offer(stream_path: str, request: Request) -> Response:
    """Proxy WHEP negotiation through the backend.
    通过后端代理 WHEP 协商。"""
    route = str(stream_path or "").strip("/")
    if not route:
        raise HTTPException(status_code=400, detail="Stream path is required")

    app_settings = await get_all_settings()
    gateway = str(app_settings.get("mediamtx_webrtc_addr", "") or "").rstrip("/")
    if not gateway:
        raise HTTPException(status_code=400, detail="WebRTC gateway address is not configured")

    offer_sdp = await request.body()
    target_url = f"{gateway}/{route}/whep"
    headers = {
        "Content-Type": request.headers.get("content-type", "application/sdp"),
    }

    username = str(app_settings.get("mediamtx_username", "") or "")
    if username:
        headers["Authorization"] = _build_basic_auth_header(
            username,
            str(app_settings.get("mediamtx_password", "") or ""),
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.post(target_url, content=offer_sdp, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"WHEP request failed: {exc}") from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/sdp"),
    )
