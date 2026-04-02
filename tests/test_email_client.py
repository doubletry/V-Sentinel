from __future__ import annotations

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
