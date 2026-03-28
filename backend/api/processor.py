from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models.schemas import ProcessorStartRequest, ProcessorStopRequest, ProcessorStatus

router = APIRouter(prefix="/api/processor", tags=["processor"])


@router.post("/start", status_code=200)
async def start_processor(request: ProcessorStartRequest) -> dict:
    """Start AI analysis processing for a video source."""
    from backend.main import processor_manager  # avoid circular imports at module level

    try:
        result = await processor_manager.start_processor(request.source_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/stop", status_code=200)
async def stop_processor(request: ProcessorStopRequest) -> dict:
    """Stop AI analysis processing for a video source."""
    from backend.main import processor_manager

    result = await processor_manager.stop_processor(request.source_id)
    return result


@router.post("/start-all", status_code=200)
async def start_all_processors() -> dict:
    """Start AI analysis for all configured sources."""
    from backend.main import processor_manager

    result = await processor_manager.start_all_processors()
    return result


@router.post("/stop-all", status_code=200)
async def stop_all_processors() -> dict:
    """Stop AI analysis for all running sources."""
    from backend.main import processor_manager

    result = await processor_manager.stop_all_processors()
    return result


@router.get("/status", response_model=list[ProcessorStatus])
async def get_status() -> list[ProcessorStatus]:
    """Get status of all running processors."""
    from backend.main import processor_manager

    return processor_manager.get_all_status()
