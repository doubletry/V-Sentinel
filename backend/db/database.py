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
    """Create database tables if they don't exist.
    创建数据库表（如果不存在）。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        await db.execute(CREATE_SOURCES_TABLE)
        await db.execute(CREATE_ROIS_TABLE)
        await db.execute(CREATE_SETTINGS_TABLE)
        # Ensure all default keys exist, while preserving user-modified values.
        # 确保所有默认键存在，同时保留用户修改过的值。
        for key, value in DEFAULT_APP_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()
    logger.info("Database initialized at {}", _DB_PATH)


def _now_iso() -> str:
    """Return current UTC time as an ISO 8601 string.
    返回当前 UTC 时间的 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).isoformat()


async def _get_rois_for_source(db: aiosqlite.Connection, source_id: str) -> list[ROI]:
    """Fetch all ROIs for a given source from the database.
    从数据库获取指定视频源的所有 ROI。"""
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
    """Convert a database row and ROI list to a VideoSource model.
    将数据库行与 ROI 列表转换为 VideoSource 模型。"""
    source_id, name, rtsp_url, created_at = row
    return VideoSource(
        id=source_id,
        name=name,
        rtsp_url=rtsp_url,
        rois=rois,
        created_at=created_at,
    )


async def create_source(source: VideoSourceCreate) -> VideoSource:
    """Insert a new video source into the database.
    向数据库插入新的视频源。"""
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
    """Retrieve a single video source by ID, or None if not found.
    按 ID 获取单个视频源，未找到则返回 None。"""
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
    """Retrieve a video source by its RTSP URL, or None if not found.
    按 RTSP URL 获取视频源，未找到则返回 None。"""
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
    """List all video sources ordered by creation time.
    按创建时间列出所有视频源。"""
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
    """Update a video source's fields and/or ROIs.
    更新视频源的字段和/或 ROI。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        # Build update query dynamically / 动态构建更新查询
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
        # Update ROIs if provided / 如果提供了 ROI 则更新
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
    """Delete a video source by ID. Returns True if a row was deleted.
    按 ID 删除视频源。如果删除了记录则返回 True。"""
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
    """Replace all ROIs for a source within an existing transaction.
    在已有事务内替换指定源的所有 ROI。"""
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
    """Save ROIs for a source (replaces existing ROIs).
    保存视频源的 ROI（替换现有 ROI）。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(PRAGMA_FK)
        await _save_rois_in_db(db, source_id, rois)
        await db.commit()
        return await _get_rois_for_source(db, source_id)


async def get_rois(source_id: str) -> list[ROI]:
    """Get all ROIs for a given source.
    获取指定视频源的所有 ROI。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        return await _get_rois_for_source(db, source_id)


# ── App Settings / 应用设置 ────────────────────────────────────────────────────

async def get_all_settings() -> dict[str, str]:
    """Return all app settings as a key→value dict.
    以键→值字典形式返回所有应用设置。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        async with db.execute("SELECT key, value FROM app_settings") as cursor:
            rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_setting(key: str) -> str | None:
    """Return a single setting value, or None if not found.
    返回单个设置值，未找到则返回 None。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def update_settings(data: dict[str, str]) -> dict[str, str]:
    """Update multiple settings at once. Returns all settings after update.
    批量更新设置。返回更新后的所有设置。"""
    async with aiosqlite.connect(_DB_PATH) as db:
        for key, value in data.items():
            await db.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await db.commit()
    return await get_all_settings()
