from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.models.schemas import AnalysisMessage

router = APIRouter()


class WSManager:
    """WebSocket connection manager for real-time message broadcasting."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info(
            "WebSocket client connected. Total: {}", len(self._connections)
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info(
            "WebSocket client disconnected. Total: {}", len(self._connections)
        )

    async def broadcast(self, message: AnalysisMessage) -> None:
        """Send a message to all connected WebSocket clients."""
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
    """WebSocket endpoint for real-time analysis message streaming."""
    from backend.main import ws_manager  # avoid circular imports

    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; client can send pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)
