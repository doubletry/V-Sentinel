from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.api import processor as processor_router
from backend.api import settings as settings_router
from backend.api import sources as sources_router
from backend.api import ws as ws_module
from backend.config import settings
from backend.db.database import get_all_settings, init_db
from backend.processing.manager import ProcessorManager
from backend.vengine.client import AsyncVEngineClient

# Configure loguru
logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True)

# Module-level singletons (accessed by API routers)
ws_manager: ws_module.WSManager
vengine_client: AsyncVEngineClient
processor_manager: ProcessorManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize and teardown resources."""
    global ws_manager, vengine_client, processor_manager

    logger.info("Starting {} ...", settings.app_name)

    # Initialize WebSocket manager
    ws_manager = ws_module.WSManager()

    # Initialize database
    await init_db()

    # Initialize V-Engine async gRPC client (addresses from DB settings)
    app_settings = await get_all_settings()
    vengine_client = AsyncVEngineClient(settings)
    await vengine_client.connect(app_settings)

    # Initialize ProcessorManager
    processor_manager = ProcessorManager(
        vengine_client=vengine_client,
        ws_manager=ws_manager,
        app_settings=app_settings,
    )

    logger.info("{} started successfully", settings.app_name)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("Shutting down {} ...", settings.app_name)

    await processor_manager.stop_all()
    await vengine_client.close()

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
app.include_router(settings_router.router)
app.include_router(ws_module.router)


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "app": settings.app_name}


# ── Static files (production: serve built frontend) ───────────────────────────
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
    logger.info("Serving frontend from {}", _frontend_dist)
