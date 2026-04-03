from __future__ import annotations

import csv
from io import StringIO

import pytest

from core.email_client import AsyncEmailClient


class TestAsyncEmailClient:
    def test_build_request_splits_addresses(self):
        client = AsyncEmailClient()
        request = client.build_request(
            {
                "email_from_address": "sender@example.com",
                "email_from_auth_code": "secret",
                "email_to_addresses": "a@example.com, b@example.com",
                "email_cc_addresses": "cc1@example.com, cc2@example.com",
            },
            subject="test",
            plain_text_body="hello",
        )
        assert list(request.to_addresses) == ["a@example.com", "b@example.com"]
        assert list(request.cc_addresses) == ["cc1@example.com", "cc2@example.com"]

    def test_build_request_requires_sender(self):
        client = AsyncEmailClient()
        with pytest.raises(ValueError):
            client.build_request(
                {
                    "email_from_auth_code": "secret",
                    "email_to_addresses": "a@example.com",
                },
                subject="test",
                plain_text_body="hello",
            )

    def test_product_name_drives_summary_subject(self):
        client = AsyncEmailClient()
        request = client.build_request(
            {
                "site_title": "My Sentinel",
                "email_from_address": "sender@example.com",
                "email_from_auth_code": "secret",
                "email_to_addresses": "a@example.com",
            },
            subject=f"{client._product_name({'site_title': 'My Sentinel'})} 每日总结 2026-01-01",
            plain_text_body="hello",
        )
        assert request.subject == "My Sentinel 每日总结 2026-01-01"

    async def test_send_daily_summary_email_attaches_single_csv_table(self):
        client = AsyncEmailClient()
        captured = {}

        async def fake_send_email(request):
            captured["request"] = request
            return {"status": "SUCCESS"}

        client.send_email = fake_send_email
        await client.send_daily_summary_email(
            {
                "site_title": "My Sentinel",
                "email_from_address": "sender@example.com",
                "email_from_auth_code": "secret",
                "email_to_addresses": "a@example.com",
            },
            summary_text="hello",
            until_iso="2026-01-01T12:00:00+00:00",
            visits=[
                {"source_name": "Cam1", "missing_actions": ["HandOverKeys"]},
                {"source_name": "Cam2", "missing_actions": []},
            ],
        )
        request = captured["request"]
        assert request.subject == "My Sentinel 每日总结 2026-01-01"
        assert len(request.attachments) == 1
        attachment = request.attachments[0]
        assert attachment.filename == "truck-daily-summary-2026-01-01.csv"
        decoded = attachment.data.decode("utf-8-sig")
        rows = list(csv.reader(StringIO(decoded)))
        assert rows == [
            ["序号", "区域", "回放位置或IP", "抽查内容/类型", "AI视觉分析结果"],
            ["1", "", "Cam1", "货台检查", "上交钥匙"],
            ["2", "", "Cam2", "货台检查", "无异常"],
        ]
