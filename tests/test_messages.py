from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from httpx import AsyncClient

from backend.db.database import (
    get_vehicle_visits_between,
    list_analysis_messages,
    save_analysis_message,
    save_vehicle_visit,
    update_settings,
)


class TestMessagePersistence:
    async def test_save_and_list_messages(self, init_db):
        await save_analysis_message(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_name": "Cam1",
                "source_id": "s1",
                "level": "info",
                "message": "hello",
                "image_base64": None,
            }
        )

        rows = await list_analysis_messages(limit=10)
        assert len(rows["items"]) == 1
        assert rows["items"][0]["message"] == "hello"

    async def test_save_message_persists_image_to_filesystem(self, async_client: AsyncClient):
        encoded = base64.b64encode(b"jpeg-bytes").decode("ascii")
        await save_analysis_message(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_name": "Cam1",
                "source_id": "s1",
                "level": "info",
                "message": "hello",
                "image_base64": encoded,
            }
        )

        rows = await list_analysis_messages(limit=10)
        assert rows["items"][0]["image_url"].startswith("/api/messages/")
        assert rows["items"][0]["image_base64"] is None

        resp = await async_client.get(rows["items"][0]["image_url"])
        assert resp.status_code == 200
        assert resp.content == b"jpeg-bytes"

    async def test_retention_prunes_old_messages(self, init_db):
        await update_settings({"message_retention_days": "1"})
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        await save_analysis_message(
            {
                "timestamp": old_timestamp,
                "source_name": "OldCam",
                "source_id": "old",
                "level": "info",
                "message": "old",
                "image_base64": None,
            }
        )
        await save_analysis_message(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_name": "NewCam",
                "source_id": "new",
                "level": "info",
                "message": "new",
                "image_base64": None,
            }
        )

        rows = await list_analysis_messages(limit=10)
        assert [row["message"] for row in rows["items"]] == ["new"]


class TestMessagesAPI:
    async def test_list_persisted_messages(self, async_client: AsyncClient):
        await save_analysis_message(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_name": "Cam1",
                "source_id": "s1",
                "level": "warning",
                "message": "persisted",
                "image_base64": None,
            }
        )

        resp = await async_client.get("/api/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"][0]["message"] == "persisted"
        assert data["items"][0]["level"] == "warning"
        assert data["total"] == 1
        assert "image_url" in data["items"][0]

    async def test_list_persisted_messages_paginates(self, async_client: AsyncClient):
        for index in range(25):
            await save_analysis_message(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_name": "Cam1",
                    "source_id": "s1",
                    "level": "info",
                    "message": f"persisted-{index}",
                    "image_base64": None,
                }
            )

        resp = await async_client.get("/api/messages", params={"page": 2, "page_size": 20})
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["page_size"] == 20
        assert data["total"] == 25
        assert len(data["items"]) == 5

    async def test_processor_plugins_endpoint(self, async_client: AsyncClient):
        resp = await async_client.get("/api/processor/plugins")
        assert resp.status_code == 200
        data = resp.json()
        values = {item["value"] for item in data}
        assert {"truck", "example"} <= values

    async def test_today_vehicle_events_endpoint(self, async_client: AsyncClient):
        now = datetime.now(timezone.utc).isoformat()
        await save_vehicle_visit(
            source_id="s1",
            source_name="Cam1",
            track_id=1,
            enter_time=now,
            exit_time=now,
            plate="ABC123",
            confirmed_actions=["ExteriorInspectionOfTruck"],
            missing_actions=["TakePhotosOfGoods"],
        )

        resp = await async_client.get("/api/vehicle-events/today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["visits"][0]["plate"] == "ABC123"
        assert data["visits"][0]["confirmed_actions"] == ["车外检查"]
        assert data["visits"][0]["missing_actions"] == ["货物拍照"]
        assert "ABC123" in data["summary_text"]
        assert "到达时间" in data["summary_text"]
        assert "离开时间" in data["summary_text"]

    async def test_send_summary_now_endpoint(self, async_client: AsyncClient):
        from backend.main import app

        app.state.email_client.send_daily_summary_email = AsyncMock(
            return_value={"status": "SUCCESS"}
        )
        app.state.email_client.reconnect_from_settings = AsyncMock()

        now = datetime.now(timezone.utc).isoformat()
        await save_vehicle_visit(
            source_id="s1",
            source_name="Cam1",
            track_id=1,
            enter_time=now,
            exit_time=now,
            plate="XYZ888",
            confirmed_actions=["车外检查"],
            missing_actions=[],
        )

        resp = await async_client.post("/api/vehicle-events/send-summary-now")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert "XYZ888" in data["summary_text"]
        assert "到达时间" in data["summary_text"]
        assert "离开时间" in data["summary_text"]
        app.state.email_client.send_daily_summary_email.assert_awaited_once()
