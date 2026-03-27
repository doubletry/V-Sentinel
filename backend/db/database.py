from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import aiosqlite
from loguru import logger

from backend.config import DEFAULT_APP_SETTINGS, settings
from backend.models.schemas import ROI, ROICreate, VideoSource, VideoSourceCreate, VideoSourceUpdate


_DB_PATH = settings.db_path

CREATE_SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS video_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rtsp_url TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""

CREATE_ROIS_TABLE = """
CREATE TABLE IF NOT EXISTS rois (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES video_sources(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    points TEXT NOT NULL,
    tag TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""

CREATE_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

PRAGMA_FK = "PRAGMA foreign_keys = ON;"


async def init_db() -> None:
    """Create database tables if they don't exist."""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        await db.execute(CREATE_SOURCES_TABLE)
        await db.execute(CREATE_ROIS_TABLE)
        await db.execute(CREATE_SETTINGS_TABLE)
        # Seed default settings if table is empty
        async with db.execute("SELECT COUNT(*) FROM app_settings") as cursor:
            row = await cursor.fetchone()
        if row and row[0] == 0:
            for key, value in DEFAULT_APP_SETTINGS.items():
                await db.execute(
                    "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
        await db.commit()
    logger.info("Database initialized at {}", _DB_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_rois_for_source(db: aiosqlite.Connection, source_id: str) -> list[ROI]:
    async with db.execute(
        "SELECT id, type, points, tag FROM rois WHERE source_id = ? ORDER BY created_at",
        (source_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    result: list[ROI] = []
    for row in rows:
        roi_id, roi_type, points_json, tag = row
        points = json.loads(points_json)
        result.append(ROI(id=roi_id, type=roi_type, points=points, tag=tag))
    return result


def _row_to_source(row: tuple, rois: list[ROI]) -> VideoSource:
    source_id, name, rtsp_url, created_at = row
    return VideoSource(
        id=source_id,
        name=name,
        rtsp_url=rtsp_url,
        rois=rois,
        created_at=created_at,
    )


async def create_source(source: VideoSourceCreate) -> VideoSource:
    source_id = str(uuid.uuid4())
    created_at = _now_iso()
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        await db.execute(
            "INSERT INTO video_sources (id, name, rtsp_url, created_at) VALUES (?, ?, ?, ?)",
            (source_id, source.name, source.rtsp_url, created_at),
        )
        await db.commit()
    return VideoSource(
        id=source_id,
        name=source.name,
        rtsp_url=source.rtsp_url,
        rois=[],
        created_at=created_at,
    )


async def get_source(source_id: str) -> VideoSource | None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        async with db.execute(
            "SELECT id, name, rtsp_url, created_at FROM video_sources WHERE id = ?",
            (source_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        rois = await _get_rois_for_source(db, source_id)
    return _row_to_source(row, rois)


async def get_source_by_rtsp(rtsp_url: str) -> VideoSource | None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        async with db.execute(
            "SELECT id, name, rtsp_url, created_at FROM video_sources WHERE rtsp_url = ?",
            (rtsp_url,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        rois = await _get_rois_for_source(db, row[0])
    return _row_to_source(row, rois)


async def list_sources() -> list[VideoSource]:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        async with db.execute(
            "SELECT id, name, rtsp_url, created_at FROM video_sources ORDER BY created_at"
        ) as cursor:
            rows = await cursor.fetchall()
        sources: list[VideoSource] = []
        for row in rows:
            rois = await _get_rois_for_source(db, row[0])
            sources.append(_row_to_source(row, rois))
    return sources


async def update_source(source_id: str, data: VideoSourceUpdate) -> VideoSource | None:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        # Build update query dynamically
        fields: list[str] = []
        values: list = []
        if data.name is not None:
            fields.append("name = ?")
            values.append(data.name)
        if data.rtsp_url is not None:
            fields.append("rtsp_url = ?")
            values.append(data.rtsp_url)
        if fields:
            values.append(source_id)
            await db.execute(
                f"UPDATE video_sources SET {', '.join(fields)} WHERE id = ?",
                values,
            )
        # Update ROIs if provided
        if data.rois is not None:
            await _save_rois_in_db(db, source_id, data.rois)
        await db.commit()
        async with db.execute(
            "SELECT id, name, rtsp_url, created_at FROM video_sources WHERE id = ?",
            (source_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        rois = await _get_rois_for_source(db, source_id)
    return _row_to_source(row, rois)


async def delete_source(source_id: str) -> bool:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        cursor = await db.execute(
            "DELETE FROM video_sources WHERE id = ?", (source_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def _save_rois_in_db(
    db: aiosqlite.Connection, source_id: str, rois: list[ROICreate]
) -> None:
    await db.execute("DELETE FROM rois WHERE source_id = ?", (source_id,))
    now = _now_iso()
    for roi in rois:
        roi_id = str(uuid.uuid4())
        points_json = json.dumps([p.model_dump() for p in roi.points])
        await db.execute(
            "INSERT INTO rois (id, source_id, type, points, tag, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (roi_id, source_id, roi.type, points_json, roi.tag, now),
        )


async def save_rois(source_id: str, rois: list[ROICreate]) -> list[ROI]:
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        await _save_rois_in_db(db, source_id, rois)
        await db.commit()
        return await _get_rois_for_source(db, source_id)


async def get_rois(source_id: str) -> list[ROI]:
    async with aiosqlite.connect(_DB_PATH) as db:
        return await _get_rois_for_source(db, source_id)


# ── App Settings ──────────────────────────────────────────────────────────────

async def get_all_settings() -> dict[str, str]:
    """Return all app settings as a key→value dict."""
    async with aiosqlite.connect(_DB_PATH) as db:
        async with db.execute("SELECT key, value FROM app_settings") as cursor:
            rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_setting(key: str) -> str | None:
    """Return a single setting value, or None if not found."""
    async with aiosqlite.connect(_DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def update_settings(data: dict[str, str]) -> dict[str, str]:
    """Update multiple settings at once. Returns all settings after update."""
    async with aiosqlite.connect(_DB_PATH) as db:
        for key, value in data.items():
            await db.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await db.commit()
    return await get_all_settings()
