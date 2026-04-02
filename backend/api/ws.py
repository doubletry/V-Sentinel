from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.models.schemas import AnalysisMessage

router = APIRouter()


class WSManager:
    """WebSocket connection manager for real-time message broadcasting.
    用于实时消息广播的 WebSocket 连接管理器。"""

    def __init__(
        self,
        persist_message: Callable[[AnalysisMessage], Awaitable[None]] | None = None,
    ) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._persist_message = persist_message

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.
        接受并注册新的 WebSocket 连接。"""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info(
            "WebSocket client connected. Total: {}", len(self._connections)
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active set.
        从活跃连接集合中移除 WebSocket 连接。"""
        async with self._lock:
            self._connections.discard(websocket)
        logger.info(
            "WebSocket client disconnected. Total: {}", len(self._connections)
        )

    async def broadcast(self, message: AnalysisMessage) -> None:
        """Send a message to all connected WebSocket clients.
        向所有已连接的 WebSocket 客户端发送消息。"""
        if self._persist_message is not None:
            await self._persist_message(message)
        payload = message.model_dump_json()
        dead: list[WebSocket] = []
        async with self._lock:
            connections = set(self._connections)
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


@router.websocket("/ws/messages")
async def ws_messages_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time analysis message streaming.
    用于实时分析消息推送的 WebSocket 端点。"""
    from backend.main import ws_manager  # avoid circular imports / 避免循环导入

    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings / 保持连接活跃；客户端可发送 ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)
