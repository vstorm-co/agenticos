"""Native bridge identity, bounded transport and the existing prompt contract."""

import base64
import json
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import JsonValue, SecretStr

from app.core.exceptions import ExternalServiceError
from app.services.channels.base import (
    ChannelChoice,
    IncomingAttachment,
    OutgoingAttachment,
    OutgoingMessage,
    PromptMessage,
)
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.imessage import ImessageAdapter
from app.services.channels.imessage_transport import BridgeCredentials

pytestmark = pytest.mark.anyio


def credential() -> BridgeCredentials:
    return BridgeCredentials(
        bot_id=uuid4(),
        server="https://bridge.example.com",
        password=SecretStr("private-password"),
        webhook_secret=SecretStr("callback-secret"),
    )


def payload(
    *, group: bool = False, changes: dict[str, JsonValue] | None = None
) -> dict[str, JsonValue]:
    return {
        "type": "new-message",
        "data": {
            "guid": "MESSAGE-GUID",
            "text": "Hello",
            "isFromMe": False,
            "handle": {"address": "ada@example.com"},
            "chats": [{"guid": "iMessage;+;chat123" if group else "iMessage;-;ada@example.com"}],
            "attachments": [],
            **(changes or {}),
        },
    }


@pytest.mark.parametrize("group", [False, True])
async def test_inbound_private_and_group_contexts_remain_distinct(group: bool) -> None:
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    try:
        incoming = adapter.parse_incoming(payload(group=group), "bot")
        assert incoming is not None
        assert incoming.platform == "imessage" and incoming.platform_user_id == "ada@example.com"
        assert incoming.chat_type == ("group" if group else "private")
        assert incoming.addressed is (not group)
        assert incoming.message_id == "MESSAGE-GUID"
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "change", [{"isFromMe": True}, {"itemType": 1}, {"associatedMessageType": 2000}, {"text": " "}]
)
async def test_self_echoes_system_events_and_tapbacks_do_not_start_agent_turns(
    change: dict[str, JsonValue],
) -> None:
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    event = payload(changes=change)
    try:
        assert adapter.parse_incoming(event, "bot") is None
        assert adapter.parse_incoming({"type": "updated-message"}, "bot") is None
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "change",
    [
        {"handle": None},
        {"handle": {"address": "someone-else@example.com"}},
        {"handle": {"address": " "}},
        {"isFromMe": "false"},
        {"chats": []},
        {"chats": [{"guid": "SMS;-;+15555550123"}]},
        {"chats": [{"guid": "iMessage;-;ada@example.com"}, {"guid": "iMessage;+;chat-other"}]},
        {"text": "invalid\x00jsonb"},
    ],
)
async def test_unidentified_ambiguous_or_malformed_sender_cannot_borrow_private_history(
    change: dict[str, JsonValue],
) -> None:
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    event = payload(changes=change)
    try:
        with pytest.raises(ExternalServiceError):
            adapter.parse_incoming(event, "bot")
    finally:
        await adapter.aclose()


async def test_attachment_only_message_keeps_metadata_and_never_trusts_an_external_url() -> None:
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    event = payload(
        changes={
            "text": None,
            "attachments": [
                {
                    "guid": "FILE-GUID",
                    "transferName": "../../private/report.pdf",
                    "mimeType": "application/pdf",
                    "totalBytes": 12,
                    "downloadUrl": "https://attacker.example/secret",
                }
            ],
        }
    )
    try:
        incoming = adapter.parse_incoming(event, "bot")
        assert incoming is not None and incoming.text == ""
        assert incoming.attachments == [
            IncomingAttachment(
                filename="report.pdf", mime_type="application/pdf", size=12, handle="FILE-GUID"
            )
        ]
        assert "attacker" not in json.dumps(incoming.raw)
    finally:
        await adapter.aclose()


@pytest.mark.security
@pytest.mark.parametrize("bad", ["", "Basic wrong", "Bearer callback-secret", "Basic ü"])
async def test_callback_authentication_is_closed_without_the_correct_bot_secret(bad: str) -> None:
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    try:
        assert not adapter.verify_webhook_signature({"authorization": bad}, "callback-secret")
        valid = "Basic " + base64.b64encode(b"agenticos:callback-secret").decode()
        assert adapter.verify_webhook_signature({"authorization": valid}, "callback-secret")
        assert not adapter.verify_webhook_signature({"authorization": valid}, "different-secret")
        with pytest.raises(ChannelNotConfigured):
            await adapter.start_polling("bot", credential().encode())
        await adapter.stop_polling("bot")
    finally:
        await adapter.aclose()


async def test_text_and_files_use_one_configured_bridge_and_fresh_send_handles() -> None:
    calls: list[tuple[str, bytes]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "bridge.example.com"
        assert request.url.params["password"] == "private-password"
        calls.append((request.url.path, await request.aread()))
        return httpx.Response(200, json={"status": 200, "data": {"guid": "SENT", "error": 0}})

    adapter = ImessageAdapter(httpx.MockTransport(respond))
    token = credential().encode()
    try:
        await adapter.send_message(
            token,
            OutgoingMessage(
                platform_chat_id="iMessage;-;ada@example.com",
                text="Hello",
                attachments=[
                    OutgoingAttachment(
                        filename="report.txt", content=b"report", mime_type="text/plain"
                    )
                ],
                image_png=b"png",
            ),
        )
    finally:
        await adapter.aclose()
    assert [path for path, _ in calls] == [
        "/api/v1/message/text",
        "/api/v1/message/attachment",
        "/api/v1/message/attachment",
    ]
    text = json.loads(calls[0][1])
    assert text["message"] == "Hello" and text["method"] == "apple-script"
    assert text["chatGuid"] == "iMessage;-;ada@example.com" and text["tempGuid"]
    assert b"report.txt" in calls[2][1] and b"report" in calls[2][1]


async def test_broken_or_different_bridge_is_visible_without_sending_to_another_host() -> None:
    called: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        called.append(request.url.host)
        return httpx.Response(503)

    adapter = ImessageAdapter(httpx.MockTransport(refuse))
    message = OutgoingMessage(platform_chat_id="iMessage;-;ada@example.com", text="Hello")
    try:
        with pytest.raises(ChannelNotConfigured):
            await adapter.send_message(
                credential().encode(),
                replace(message, api_base_url="https://different.example.com"),
            )
        assert called == []
        with pytest.raises(ExternalServiceError, match="unavailable"):
            await adapter.send_message(credential().encode(), message)
        assert called == ["bridge.example.com"]
    finally:
        await adapter.aclose()


async def test_numbered_prompt_uses_existing_shared_namespace_and_records_only_sent_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.channels import sms_prompts

    reserve, remember = AsyncMock(return_value=7), AsyncMock()
    monkeypatch.setattr(sms_prompts, "reserve", reserve)
    monkeypatch.setattr(sms_prompts, "remember", remember)
    adapter = ImessageAdapter(httpx.MockTransport(lambda _request: httpx.Response(200)))
    send = AsyncMock()
    monkeypatch.setattr(adapter, "send_message", send)
    prompt = PromptMessage(
        bot_id="bot",
        platform_chat_id="iMessage;-;ada@example.com",
        text="Approve?",
        choices=[
            ChannelChoice(label="Yes", value="aos:one:0"),
            ChannelChoice(label="No", value="aos:one:1"),
        ],
    )
    try:
        await adapter.send_prompt(credential().encode(), prompt)
        reserve.assert_awaited_once_with("bot", prompt.platform_chat_id, 2, platform="imessage")
        assert "7. Yes\n8. No" in send.await_args.args[1].text
        assert remember.await_args.kwargs == {"start": 7, "platform": "imessage"}
        remember.reset_mock()
        send.side_effect = ExternalServiceError(message="bridge offline")
        with pytest.raises(ExternalServiceError):
            await adapter.send_prompt(credential().encode(), prompt)
        remember.assert_not_awaited()
    finally:
        await adapter.aclose()
