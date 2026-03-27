from __future__ import annotations

from fastapi import APIRouter

from backend.db import database as db
from backend.models.schemas import AppSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings() -> dict[str, str]:
    """Get all application settings."""
    return await db.get_all_settings()


@router.put("")
async def update_settings(data: AppSettingsUpdate) -> dict[str, str]:
    """Update application settings.

    After saving, the V-Engine gRPC client is reconnected with the new
    addresses so changes take effect immediately.
    """
    # Build dict of only the fields that were actually provided
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        return await db.get_all_settings()

    result = await db.update_settings(updates)

    # Reconnect V-Engine client with new addresses
    from backend.main import vengine_client
    await vengine_client.reconnect_from_settings(result)

    return result
