"""Async gRPC client for the email service.
邮件服务的异步 gRPC 客户端。
"""

from __future__ import annotations

from typing import Any

import grpc.aio

from core.constants import EMAIL_PORT
from core.proto import email_pb2, email_pb2_grpc


class AsyncEmailClient:
    """Async gRPC client for email delivery and test-email checks.
    用于邮件投递与测试邮件校验的异步 gRPC 客户端。"""

    def __init__(self) -> None:
        self._channel: grpc.aio.Channel | None = None
        self._stub: email_pb2_grpc.EmailServiceStub | None = None
        self._address: str | None = None

    @staticmethod
    def _build_address(app_settings: dict[str, str]) -> str:
        host = app_settings.get("email_host") or app_settings.get(
            "vengine_host", "localhost"
        )
        port = app_settings.get("email_port", EMAIL_PORT)
        return f"{host}:{port}"

    @staticmethod
    def _split_addresses(raw: str | None) -> list[str]:
        return [
            part
            for part in (segment.strip() for segment in str(raw or "").split(","))
            if part
        ]

    async def connect(self, app_settings: dict[str, str]) -> None:
        """Connect to the configured email-service endpoint.
        连接到配置的邮件服务端点。"""
        address = self._build_address(app_settings)
        if self._channel is not None and self._address == address:
            return
        await self.close()
        self._channel = grpc.aio.insecure_channel(address)
        self._stub = email_pb2_grpc.EmailServiceStub(self._channel)
        self._address = address

    async def reconnect_from_settings(self, app_settings: dict[str, str]) -> None:
        """Reconnect using the latest settings.
        使用最新设置重新连接。"""
        await self.connect(app_settings)

    async def close(self) -> None:
        """Close the email-service channel if open.
        如已打开则关闭邮件服务通道。"""
        if self._channel is not None:
            await self._channel.close()
        self._channel = None
        self._stub = None
        self._address = None

    async def send_email(self, request: email_pb2.SendEmailRequest) -> dict[str, str]:
        """Send a gRPC email request and return the service response.
        发送 gRPC 邮件请求并返回服务响应。"""
        if self._stub is None:
            raise RuntimeError("Email client is not connected")
        response = await self._stub.SendEmail(request)
        return {
            "status": response.status,
            "message": response.message,
            "email_id": response.email_id,
        }

    def build_request(
        self,
        app_settings: dict[str, str],
        *,
        subject: str,
        plain_text_body: str,
        html_body: str = "",
        overrides: dict[str, Any] | None = None,
    ) -> email_pb2.SendEmailRequest:
        """Build a SendEmailRequest from persisted settings.
        根据持久化设置构建 SendEmailRequest。"""
        merged = dict(app_settings)
        if overrides:
            merged.update({k: str(v) for k, v in overrides.items() if v is not None})

        from_address = str(merged.get("email_from_address", "")).strip()
        from_auth_code = str(merged.get("email_from_auth_code", "")).strip()
        to_addresses = self._split_addresses(merged.get("email_to_addresses"))
        cc_addresses = self._split_addresses(merged.get("email_cc_addresses"))

        if not from_address:
            raise ValueError("Sender email address is required (email_from_address)")
        if not from_auth_code:
            raise ValueError("Sender password/auth code is required (email_from_auth_code)")
        if not (to_addresses or cc_addresses):
            raise ValueError(
                "At least one recipient is required (email_to_addresses or email_cc_addresses)"
            )

        return email_pb2.SendEmailRequest(
            from_address=from_address,
            from_auth_code=from_auth_code,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            subject=subject,
            plain_text_body=plain_text_body,
            html_body=html_body or plain_text_body.replace("\n", "<br>"),
        )

    async def send_test_email(
        self,
        app_settings: dict[str, str],
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Send a test email using the provided settings.
        使用提供的设置发送测试邮件。"""
        request = self.build_request(
            app_settings,
            subject="V-Sentinel 邮件配置测试",
            plain_text_body="这是一封来自 V-Sentinel 的测试邮件，用于验证邮件配置是否正确。",
            overrides=overrides,
        )
        return await self.send_email(request)

    async def send_daily_summary_email(
        self,
        app_settings: dict[str, str],
        summary_text: str,
        until_iso: str,
    ) -> dict[str, str]:
        """Send the daily truck summary email.
        发送 truck 每日总结邮件。"""
        request = self.build_request(
            app_settings,
            subject=f"V-Sentinel 每日总结 {until_iso[:10]}",
            plain_text_body=summary_text,
        )
        return await self.send_email(request)
