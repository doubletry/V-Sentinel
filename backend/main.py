from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.api import processor as processor_router
from backend.api import messages as messages_router
from backend.api import settings as settings_router
from backend.api import sources as sources_router
from backend.api import vehicle_events as vehicle_events_router
from backend.api import ws as ws_module
from backend.config import settings
from backend.db.database import close_db, get_all_settings, init_db, save_analysis_message
from backend.processing.log_buffer import processing_log_buffer
from backend.processing.manager import ProcessorManager
from backend.vengine.client import AsyncVEngineClient
from core.email_client import AsyncEmailClient

# Configure loguru / 配置 loguru 日志
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True)


def _should_capture_runtime_log(module_name: str) -> bool:
    """Return whether a runtime log should be shown in the log page.
    返回该运行时日志是否应显示在日志页。"""
    return module_name.startswith(("backend.", "core."))


def _processing_log_sink(message) -> None:
    """Forward processing logs to the in-memory ring buffer.
    将处理日志转发到内存环形缓冲区。"""
    record = message.record
    processing_log_buffer.append(
        timestamp=record["time"].isoformat(),
        level=record["level"].name,
        module=record["name"],
        message=record["message"],
    )


logger.add(
    _processing_log_sink,
    level="INFO",
    filter=lambda record: _should_capture_runtime_log(str(record["name"])),
)


class _StdlibProcessingLogHandler(logging.Handler):
    """Bridge stdlib logging records into the runtime log buffer.
    将标准库 logging 记录桥接到运行时日志缓冲区。"""

    def emit(self, record: logging.LogRecord) -> None:
        if not _should_capture_runtime_log(record.name):
            return
        processing_log_buffer.append(
            timestamp=datetime_from_record(record),
            level=record.levelname,
            module=record.name,
            message=record.getMessage(),
        )


def datetime_from_record(record: logging.LogRecord) -> str:
    """Format a stdlib logging timestamp as ISO string.
    将标准库 logging 的时间格式化为 ISO 字符串。"""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()


_STDLIB_LOG_HANDLER = _StdlibProcessingLogHandler()
_STDLIB_LOG_CAPTURE_CONFIGURED = False


def _configure_stdlib_log_capture() -> None:
    """Register stdlib log forwarding exactly once per process.
    为当前进程只注册一次标准库日志转发。"""
    global _STDLIB_LOG_CAPTURE_CONFIGURED

    if _STDLIB_LOG_CAPTURE_CONFIGURED:
        return

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        std_logger = logging.getLogger(logger_name)
        if not any(handler is _STDLIB_LOG_HANDLER for handler in std_logger.handlers):
            std_logger.addHandler(_STDLIB_LOG_HANDLER)
    _STDLIB_LOG_CAPTURE_CONFIGURED = True

# Module-level singletons (accessed by API routers) / 模块级单例（供 API 路由使用）
ws_manager: ws_module.WSManager
vengine_client: AsyncVEngineClient
email_client: AsyncEmailClient
processor_manager: ProcessorManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize and teardown resources.
    应用生命周期：初始化与销毁资源。"""
    global ws_manager, vengine_client, email_client, processor_manager

    logger.info("Starting {} ...", settings.app_name)
    _configure_stdlib_log_capture()

    # Initialize WebSocket manager / 初始化 WebSocket 管理器
    async def _persist_message(message) -> None:
        await save_analysis_message(message.model_dump())

    ws_manager = ws_module.WSManager(persist_message=_persist_message)

    # Initialize database / 初始化数据库
    await init_db()

    # Initialize V-Engine async gRPC client (addresses from DB settings)
    # 初始化 V-Engine 异步 gRPC 客户端（地址来自数据库设置）
    app_settings = await get_all_settings()
    app.title = app_settings.get("site_title") or settings.app_name
    vengine_client = AsyncVEngineClient(settings)
    await vengine_client.connect(app_settings)
    email_client = AsyncEmailClient()
    await email_client.connect(app_settings)

    # Store on app.state for dependency-injection in API routes / 存储到 app.state 以便 API 路由依赖注入
    app.state.vengine_client = vengine_client
    app.state.email_client = email_client

    # Initialize ProcessorManager (includes AnalysisAgent) / 初始化处理器管理器（含分析代理）
    processor_manager = ProcessorManager(
        vengine_client=vengine_client,
        ws_manager=ws_manager,
        app_settings=app_settings,
        email_client=email_client,
    )
    await processor_manager.start_agent()

    logger.info("{} started successfully", settings.app_name)
    yield

    # ── Shutdown / 关闭 ─────────────────────────────────────────────────
    logger.info("Shutting down {} ...", settings.app_name)

    await processor_manager.stop_all()
    await processor_manager.stop_agent()
    await email_client.close()
    await vengine_client.close()
    await close_db()

    logger.info("{} shutdown complete", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description="AI Video Surveillance Analysis Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(sources_router.router)
app.include_router(processor_router.router)
app.include_router(messages_router.router)
app.include_router(settings_router.router)
app.include_router(vehicle_events_router.router)
app.include_router(ws_module.router)


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint.
    健康检查端点。"""
    return {"status": "ok", "app": app.title}


# ── Static files (production: serve built frontend) / 静态文件（生产环境：托管构建后的前端） ──
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
    logger.info("Serving frontend from {}", _frontend_dist)
