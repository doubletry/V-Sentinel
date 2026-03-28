"""Shared pytest fixtures for V-Sentinel tests."""
from __future__ import annotations

import asyncio
import os
import tempfile
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ── Override DB path before any backend import ────────────────────────────────
# Use a per-test temporary database so tests are isolated.

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Set up a temporary database for each test."""
    import tempfile as _tf

    fd, db_path = _tf.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DB_PATH", db_path)

    # Patch the module-level _DB_PATH in database.py
    import backend.db.database as db_mod
    monkeypatch.setattr(db_mod, "_DB_PATH", db_path)

    yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest_asyncio.fixture
async def init_db() -> None:
    """Initialize the database tables for the current test DB."""
    from backend.db.database import init_db
    await init_db()


@pytest_asyncio.fixture
async def async_client(init_db: None) -> AsyncGenerator[AsyncClient, None]:
    """Create an httpx AsyncClient using the FastAPI ASGI app.

    Triggers the app lifespan so module-level singletons (ws_manager,
    processor_manager, vengine_client) are properly initialised.
    """
    from backend.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def sample_source_data() -> dict:
    """Return valid payload for creating a video source."""
    return {"name": "Test Camera", "rtsp_url": "rtsp://localhost:8554/test"}


@pytest.fixture
def sample_roi_data() -> list[dict]:
    """Return valid ROI payload."""
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
