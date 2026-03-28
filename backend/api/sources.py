from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.db import database as db
from backend.models.schemas import (
    VideoSource,
    VideoSourceCreate,
    VideoSourceUpdate,
)

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.post("", response_model=VideoSource, status_code=201)
async def create_source(source: VideoSourceCreate) -> VideoSource:
    """Create a new video source."""
    try:
        return await db.create_source(source)
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=409, detail="A source with this RTSP URL already exists"
            )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("", response_model=list[VideoSource])
async def list_sources() -> list[VideoSource]:
    """List all video sources."""
    return await db.list_sources()


@router.get("/by-rtsp", response_model=VideoSource)
async def get_source_by_rtsp(rtsp_url: str) -> VideoSource:
    """Get a video source by its RTSP URL."""
    source = await db.get_source_by_rtsp(rtsp_url)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/{source_id}", response_model=VideoSource)
async def get_source(source_id: str) -> VideoSource:
    """Get a single video source with its ROIs."""
    source = await db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.put("/{source_id}", response_model=VideoSource)
async def update_source(source_id: str, data: VideoSourceUpdate) -> VideoSource:
    """Update a video source (name, rtsp_url, and/or ROIs)."""
    source = await db.update_source(source_id, data)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str) -> None:
    """Delete a video source."""
    deleted = await db.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
