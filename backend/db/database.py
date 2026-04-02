from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

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

CREATE_VEHICLE_VISITS_TABLE = """
CREATE TABLE IF NOT EXISTS vehicle_visits (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    track_id INTEGER NOT NULL,
    enter_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    plate TEXT NOT NULL DEFAULT '',
    confirmed_actions TEXT NOT NULL DEFAULT '[]',
    missing_actions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""

CREATE_ANALYSIS_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_messages (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_id TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    image_base64 TEXT,
    created_at TEXT NOT NULL
);
"""

PRAGMA_FK = "PRAGMA foreign_keys = ON;"
PRAGMA_WAL = "PRAGMA journal_mode = WAL;"
PRAGMA_SYNCHRONOUS = "PRAGMA synchronous = NORMAL;"
PRAGMA_BUSY_TIMEOUT = "PRAGMA busy_timeout = 5000;"

_shared_db: aiosqlite.Connection | None = None
_shared_db_path: str | None = None
_shared_db_loop: asyncio.AbstractEventLoop | None = None
_db_lock_loop: asyncio.AbstractEventLoop | None = None
_db_init_lock: asyncio.Lock | None = None
_db_use_lock: asyncio.Lock | None = None


def _get_db_locks() -> tuple[asyncio.Lock, asyncio.Lock]:
    """Return loop-local locks for shared SQLite connection access.
    返回用于共享 SQLite 连接访问的事件循环局部锁。"""
    global _db_lock_loop, _db_init_lock, _db_use_lock

    loop = asyncio.get_running_loop()
    if _db_lock_loop is not loop or _db_init_lock is None or _db_use_lock is None:
        _db_lock_loop = loop
        _db_init_lock = asyncio.Lock()
        _db_use_lock = asyncio.Lock()
    return _db_init_lock, _db_use_lock


async def _configure_db_connection(db: aiosqlite.Connection) -> None:
    """Apply SQLite pragmas for correctness and concurrent-read performance.
    配置 SQLite pragma，以提升正确性和并发读性能。"""
    await db.execute(PRAGMA_FK)
    await db.execute(PRAGMA_WAL)
    await db.execute(PRAGMA_SYNCHRONOUS)
    await db.execute(PRAGMA_BUSY_TIMEOUT)
    await db.commit()


async def _close_shared_db_unlocked() -> None:
    """Close the shared database connection without reacquiring init lock.
    关闭共享数据库连接，不重复获取初始化锁。"""
    global _shared_db, _shared_db_path, _shared_db_loop

    if _shared_db is None:
        return

    try:
        await _shared_db.close()
    except Exception as exc:  # pragma: no cover - best effort cleanup
        logger.warning("Failed to close shared SQLite connection: {}", exc)
    finally:
        _shared_db = None
        _shared_db_path = None
        _shared_db_loop = None


async def _get_shared_db() -> aiosqlite.Connection:
    """Return a reusable SQLite connection configured for this DB path.
    返回为当前 DB 路径配置好的可复用 SQLite 连接。"""
    global _shared_db, _shared_db_path, _shared_db_loop

    init_lock, _ = _get_db_locks()
    loop = asyncio.get_running_loop()
    async with init_lock:
        if _shared_db is not None and (
            _shared_db_path != _DB_PATH or _shared_db_loop is not loop
        ):
            await _close_shared_db_unlocked()

        if _shared_db is None:
            db = await aiosqlite.connect(_DB_PATH)
            await _configure_db_connection(db)
            _shared_db = db
            _shared_db_path = _DB_PATH
            _shared_db_loop = loop
            logger.info("Opened shared SQLite connection at {}", _DB_PATH)

        return _shared_db


@asynccontextmanager
async def _db_session() -> aiosqlite.Connection:
    """Serialize access through the shared SQLite connection.
    通过共享 SQLite 连接串行化数据库访问。"""
    db = await _get_shared_db()
    _, use_lock = _get_db_locks()
    async with use_lock:
        yield db


async def close_db() -> None:
    """Close the shared SQLite connection if one is open.
    如果共享 SQLite 连接已打开，则关闭它。"""
    init_lock, _ = _get_db_locks()
    async with init_lock:
        await _close_shared_db_unlocked()


async def init_db() -> None:
    """Create database tables if they don't exist.
    创建数据库表（如果不存在）。"""
    async with _db_session() as db:
        await db.execute(CREATE_SOURCES_TABLE)
        await db.execute(CREATE_ROIS_TABLE)
        await db.execute(CREATE_SETTINGS_TABLE)
        await db.execute(CREATE_VEHICLE_VISITS_TABLE)
        await db.execute(CREATE_ANALYSIS_MESSAGES_TABLE)
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


def _message_retention_cutoff_iso(retention_days_raw: str | int) -> str:
    """Convert retention-days input into a UTC cutoff timestamp.
    将保留天数输入转换为 UTC 截止时间戳。"""
    try:
        safe_days = min(30, max(1, int(retention_days_raw)))
    except Exception:
        safe_days = 7
    return (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat()


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
    async with _db_session() as db:
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
    async with _db_session() as db:
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
    async with _db_session() as db:
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
    async with _db_session() as db:
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
    async with _db_session() as db:
        fields: list[str] = []
        values: list[str] = []
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
    async with _db_session() as db:
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
    async with _db_session() as db:
        await _save_rois_in_db(db, source_id, rois)
        await db.commit()
        return await _get_rois_for_source(db, source_id)


async def get_rois(source_id: str) -> list[ROI]:
    """Get all ROIs for a given source.
    获取指定视频源的所有 ROI。"""
    async with _db_session() as db:
        return await _get_rois_for_source(db, source_id)


async def get_all_settings() -> dict[str, str]:
    """Return all app settings as a key→value dict.
    以键→值字典形式返回所有应用设置。"""
    async with _db_session() as db:
        async with db.execute("SELECT key, value FROM app_settings") as cursor:
            rows = await cursor.fetchall()
    return {row[0]: row[1] for row in rows}


async def get_setting(key: str) -> str | None:
    """Return a single setting value, or None if not found.
    返回单个设置值，未找到则返回 None。"""
    async with _db_session() as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def update_settings(data: dict[str, str]) -> dict[str, str]:
    """Update multiple settings at once. Returns all settings after update.
    批量更新设置。返回更新后的所有设置。"""
    async with _db_session() as db:
        for key, value in data.items():
            await db.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await db.commit()
    return await get_all_settings()


async def save_vehicle_visit(
    source_id: str,
    source_name: str,
    track_id: int,
    enter_time: str,
    exit_time: str,
    plate: str,
    confirmed_actions: list[str],
    missing_actions: list[str],
) -> str:
    """Insert a vehicle visit record and return its ID.
    插入一条车辆到访记录并返回其 ID。"""
    visit_id = str(uuid.uuid4())
    created_at = _now_iso()
    async with _db_session() as db:
        await db.execute(
            "INSERT INTO vehicle_visits "
            "(id, source_id, source_name, track_id, enter_time, exit_time, "
            "plate, confirmed_actions, missing_actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                visit_id,
                source_id,
                source_name,
                track_id,
                enter_time,
                exit_time,
                plate,
                json.dumps(confirmed_actions),
                json.dumps(missing_actions),
                created_at,
            ),
        )
        await db.commit()
    return visit_id


async def get_vehicle_visits_since(since_iso: str) -> list[dict]:
    """Return all vehicle visits created after *since_iso* (ISO 8601 string).
    返回 *since_iso*（ISO 8601 字符串）之后创建的所有车辆到访记录。"""
    async with _db_session() as db:
        async with db.execute(
            "SELECT id, source_id, source_name, track_id, enter_time, exit_time, "
            "plate, confirmed_actions, missing_actions, created_at "
            "FROM vehicle_visits WHERE created_at >= ? ORDER BY created_at",
            (since_iso,),
        ) as cursor:
            rows = await cursor.fetchall()
    result: list[dict] = []
    for row in rows:
        result.append({
            "id": row[0],
            "source_id": row[1],
            "source_name": row[2],
            "track_id": row[3],
            "enter_time": row[4],
            "exit_time": row[5],
            "plate": row[6],
            "confirmed_actions": json.loads(row[7]),
            "missing_actions": json.loads(row[8]),
            "created_at": row[9],
        })
    return result


async def get_vehicle_visits_between(start_iso: str, end_iso: str) -> list[dict]:
    """Return vehicle visits created within an inclusive time range.
    返回在给定闭区间时间范围内创建的车辆到访记录。"""
    async with _db_session() as db:
        async with db.execute(
            "SELECT id, source_id, source_name, track_id, enter_time, exit_time, "
            "plate, confirmed_actions, missing_actions, created_at "
            "FROM vehicle_visits WHERE created_at >= ? AND created_at <= ? "
            "ORDER BY created_at",
            (start_iso, end_iso),
        ) as cursor:
            rows = await cursor.fetchall()
    result: list[dict] = []
    for row in rows:
        result.append({
            "id": row[0],
            "source_id": row[1],
            "source_name": row[2],
            "track_id": row[3],
            "enter_time": row[4],
            "exit_time": row[5],
            "plate": row[6],
            "confirmed_actions": json.loads(row[7]),
            "missing_actions": json.loads(row[8]),
            "created_at": row[9],
        })
    return result


async def prune_analysis_messages(retention_days: int) -> None:
    """Delete messages older than the configured retention window.
    删除超过保留期的历史消息。"""
    cutoff = _message_retention_cutoff_iso(retention_days)
    async with _db_session() as db:
        await db.execute(
            "DELETE FROM analysis_messages WHERE created_at < ?",
            (cutoff,),
        )
        await db.commit()


async def save_analysis_message(message: dict[str, str | None]) -> str:
    """Persist one analysis message and prune expired records.
    持久化一条分析消息并清理过期记录。"""
    message_id = str(uuid.uuid4())
    created_at = str(message.get("timestamp") or _now_iso())
    async with _db_session() as db:
        await db.execute(
            "INSERT INTO analysis_messages "
            "(id, timestamp, source_name, source_id, level, message, image_base64, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                str(message.get("timestamp") or created_at),
                str(message.get("source_name") or ""),
                str(message.get("source_id") or ""),
                str(message.get("level") or "info"),
                str(message.get("message") or ""),
                message.get("image_base64"),
                created_at,
            ),
        )
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            ("message_retention_days",),
        ) as cursor:
            row = await cursor.fetchone()
        retention_days = 7
        if row is not None:
            retention_days = row[0]
        cutoff = _message_retention_cutoff_iso(retention_days)
        await db.execute(
            "DELETE FROM analysis_messages WHERE created_at < ?",
            (cutoff,),
        )
        await db.commit()
    return message_id


async def list_analysis_messages(
    *,
    limit: int = 500,
    source_id: str | None = None,
) -> list[dict[str, str | None]]:
    """List persisted analysis messages ordered newest-first.
    按时间倒序列出持久化分析消息。"""
    safe_limit = min(1000, max(1, int(limit)))
    async with _db_session() as db:
        if source_id:
            async with db.execute(
                "SELECT timestamp, source_name, source_id, level, message, image_base64 "
                "FROM analysis_messages WHERE source_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (source_id, safe_limit),
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with db.execute(
                "SELECT timestamp, source_name, source_id, level, message, image_base64 "
                "FROM analysis_messages ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ) as cursor:
                rows = await cursor.fetchall()
    return [
        {
            "timestamp": row[0],
            "source_name": row[1],
            "source_id": row[2],
            "level": row[3],
            "message": row[4],
            "image_base64": row[5],
        }
        for row in rows
    ]
