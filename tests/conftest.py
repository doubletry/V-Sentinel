"""Shared pytest fixtures for V-Sentinel tests.
V-Sentinel 测试的共享 pytest 夹具。"""
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ── Override DB path before any backend import / 在导入后台模块前覆盖数据库路径 ──
# Use a per-test temporary database so tests are isolated.
# 每个测试使用临时数据库以保证隔离性。

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Set up a temporary database for each test.
    为每个测试设置临时数据库。"""
    import tempfile as _tf

    fd, db_path = _tf.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DB_PATH", db_path)

    # Patch the module-level _DB_PATH in database.py / 修补 database.py 中的模块级 _DB_PATH
    import backend.db.database as db_mod
    monkeypatch.setattr(db_mod, "_DB_PATH", db_path)

    yield db_path

    # Cleanup / 清理
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest_asyncio.fixture
async def init_db() -> None:
    """Initialize the database tables for the current test DB.
    为当前测试数据库初始化表结构。"""
    from backend.db.database import init_db
    await init_db()


@pytest_asyncio.fixture
async def async_client(init_db: None) -> AsyncGenerator[AsyncClient, None]:
    """Create an httpx AsyncClient using the FastAPI ASGI app.
    使用 FastAPI ASGI 应用创建 httpx 异步客户端。

    Triggers the app lifespan so module-level singletons (ws_manager,
    processor_manager, vengine_client) are properly initialised.
    触发应用生命周期以正确初始化模块级单例
    （ws_manager、processor_manager、vengine_client）。
    """
    from backend.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def sample_source_data() -> dict:
    """Return valid payload for creating a video source.
    返回创建视频源的有效载荷。"""
    return {"name": "Test Camera", "rtsp_url": "rtsp://localhost:8554/test"}


@pytest.fixture
def sample_roi_data() -> list[dict]:
    """Return valid ROI payload.
    返回有效的 ROI 载荷。"""
    return [
        {
            "type": "rectangle",
            "points": [
                {"x": 0.1, "y": 0.1},
                {"x": 0.9, "y": 0.1},
                {"x": 0.9, "y": 0.9},
                {"x": 0.1, "y": 0.9},
            ],
            "tag": "zone-A",
        }
    ]
