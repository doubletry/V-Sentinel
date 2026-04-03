from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.db.database import list_analysis_messages, resolve_message_image_path
from backend.models.schemas import AnalysisMessage, PaginatedMessagesResponse

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("", response_model=PaginatedMessagesResponse)
async def get_messages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source_id: str | None = Query(default=None),
) -> PaginatedMessagesResponse:
    """Return persisted analysis messages ordered newest-first.
    返回按时间倒序排列的持久化分析消息。"""
    result = await list_analysis_messages(
        page=page,
        page_size=page_size,
        source_id=source_id,
    )
    return PaginatedMessagesResponse(
        items=[AnalysisMessage(**row) for row in result["items"]],
        page=int(result["page"]),
        page_size=int(result["page_size"]),
        total=int(result["total"]),
        total_pages=int(result["total_pages"]),
    )


@router.get("/images/{image_path:path}", include_in_schema=False)
async def get_message_image(image_path: str) -> FileResponse:
    """Serve one persisted analysis-message thumbnail from disk.
    从磁盘提供一张持久化分析消息缩略图。"""
    file_path = resolve_message_image_path(image_path)
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Message image not found")
    return FileResponse(file_path)
