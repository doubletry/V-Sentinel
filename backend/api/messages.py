from __future__ import annotations

from fastapi import APIRouter, Query

from backend.db.database import list_analysis_messages
from backend.models.schemas import AnalysisMessage

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("", response_model=list[AnalysisMessage])
async def get_messages(
    limit: int = Query(default=500, ge=1, le=1000),
    source_id: str | None = Query(default=None),
) -> list[AnalysisMessage]:
    """Return persisted analysis messages ordered newest-first.
    返回按时间倒序排列的持久化分析消息。"""
    rows = await list_analysis_messages(limit=limit, source_id=source_id)
    return [AnalysisMessage(**row) for row in rows]
