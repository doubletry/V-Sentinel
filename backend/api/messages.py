from __future__ import annotations

from fastapi import APIRouter, Query

from backend.db.database import list_analysis_messages
from backend.models.schemas import AnalysisMessage

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("")
async def get_messages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source_id: str | None = Query(default=None),
) -> dict:
    """Return persisted analysis messages ordered newest-first.
    返回按时间倒序排列的持久化分析消息。"""
    result = await list_analysis_messages(
        page=page,
        page_size=page_size,
        source_id=source_id,
    )
    return {
        **result,
        "items": [AnalysisMessage(**row).model_dump() for row in result["items"]],
    }
