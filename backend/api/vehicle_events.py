from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.db.database import get_all_settings, get_vehicle_visits_between, delete_vehicle_visit
from core.truck.agent import TruckAnalysisAgent

router = APIRouter(prefix="/api/vehicle-events", tags=["vehicle-events"])


def _safe_summary_time(app_settings: dict[str, str]) -> tuple[int, int]:
    try:
        hour = min(23, max(0, int(app_settings.get("daily_summary_hour", "23"))))
    except (TypeError, ValueError):
        hour = 23
    try:
        minute = min(59, max(0, int(app_settings.get("daily_summary_minute", "59"))))
    except (TypeError, ValueError):
        minute = 59
    return hour, minute


def _previous_summary_boundary(now: datetime, app_settings: dict[str, str]) -> datetime:
    hour, minute = _safe_summary_time(app_settings)
    tzinfo = _get_timezone(app_settings)
    local_now = now.astimezone(tzinfo)
    boundary = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if boundary > local_now:
        boundary -= timedelta(days=1)
    return boundary.astimezone(timezone.utc)


def _get_timezone(app_settings: dict[str, str]) -> ZoneInfo:
    timezone_name = str(app_settings.get("timezone") or "Asia/Shanghai").strip()
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


@router.get("/today")
async def get_today_vehicle_events() -> dict:
    """Return today's vehicle visits and a summary text.
    返回当天车辆事件及其总结文本。"""
    app_settings = await get_all_settings()
    tzinfo = _get_timezone(app_settings)
    local_now = datetime.now(timezone.utc).astimezone(tzinfo)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_start.astimezone(timezone.utc)
    now = local_now.astimezone(timezone.utc)
    visits = await get_vehicle_visits_between(start.isoformat(), now.isoformat())
    translated_visits = TruckAnalysisAgent.translate_visits(visits)
    summary_text = TruckAnalysisAgent.build_daily_summary_text(
        visits,
        start.isoformat(),
        now.isoformat(),
        timezone_name=str(app_settings.get("timezone") or "Asia/Shanghai"),
    )
    return {
        "since": start.isoformat(),
        "until": now.isoformat(),
        "timezone": str(app_settings.get("timezone") or "Asia/Shanghai"),
        "summary_text": summary_text,
        "visits": translated_visits,
    }


@router.post("/send-summary-now")
async def send_summary_now(request: Request) -> dict:
    """Send a summary email from the last scheduled summary boundary until now.
    立即发送一封从上一次定时点到当前时间的总结邮件。"""
    app_settings = await get_all_settings()
    now = datetime.now(timezone.utc)
    since = _previous_summary_boundary(now, app_settings)
    until_iso = now.isoformat()
    visits = await get_vehicle_visits_between(since.isoformat(), until_iso)
    summary_text = TruckAnalysisAgent.build_daily_summary_text(
        visits,
        since.isoformat(),
        until_iso,
        timezone_name=str(app_settings.get("timezone") or "Asia/Shanghai"),
    )
    email_client = request.app.state.email_client
    await email_client.reconnect_from_settings(app_settings)
    result = await email_client.send_daily_summary_email(
        app_settings=app_settings,
        summary_text=summary_text,
        until_iso=until_iso,
        visits=visits,
    )
    return {
        "status": result.get("status", "SUCCESS"),
        "since": since.isoformat(),
        "until": until_iso,
        "timezone": str(app_settings.get("timezone") or "Asia/Shanghai"),
        "visit_count": len(visits),
        "summary_text": summary_text,
    }


@router.delete("/{visit_id}", status_code=204)
async def delete_vehicle_event(visit_id: str) -> None:
    """Delete a vehicle visit record so it no longer appears anywhere.
    删除一条车辆到访记录，使其不再出现在网页和邮件中。"""
    deleted = await delete_vehicle_visit(visit_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Vehicle event not found")
