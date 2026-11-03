"""Slack blocks and confirmed refusal keep delivery separate from acknowledgement."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from app.services.channels.base import ChannelAdapter, OutgoingMessage
from app.services.channels.notification_send import NotificationRateLimited, retry_after_seconds
from app.services.channels.slack import SlackAdapter

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, 60),
        ([], 60),
        (12, 60),
        (["12"], 12),
        (" 12 ", 12),
        ("0", 1),
        ("86401", 86400),
        ("9999999999", 60),
        ("-1", 60),
        ("١٢", 60),
        ("1.5", 60),
        ({"secret": "opaque"}, 60),
    ],
)
def test_retry_header_is_bounded_without_accepting_unknown_provider_payloads(
    header: object, expected: int
) -> None:
    assert retry_after_seconds(header) == expected


@pytest.mark.parametrize("seconds,expected", [(0, 1), (1, 1), (999999, 86400)])
def test_known_refusal_has_a_controlled_message_and_bounded_delay(
    seconds: int, expected: int
) -> None:
    error = NotificationRateLimited(retry_after_seconds=seconds)
    assert error.retry_after_seconds == expected
    assert error.details == {"retry_after_seconds": expected}


@pytest.mark.parametrize("url", [None, "https://console.example.com/runs"])
async def test_default_transport_appends_the_canonical_link_without_mutating_the_notice(
    url: str | None,
) -> None:
    transport = MagicMock(send_message=AsyncMock())
    message = OutgoingMessage(platform_chat_id="private", text="Notice")
    await ChannelAdapter.send_notification(transport, "token", message, context_url=url)
    sent = transport.send_message.await_args.args[1]
    assert sent.text == (f"Notice\n\n{url}" if url else "Notice")
    assert message.text == "Notice"


@pytest.mark.parametrize("link", [None, "https://console.example.com/runs"])
@pytest.mark.parametrize("long", [False, True])
async def test_slack_uses_safe_bounded_blocks_and_no_sdk_retries(
    link: str | None, long: bool
) -> None:
    client = MagicMock(chat_postMessage=AsyncMock())
    adapter = SlackAdapter()
    text = "<@U123> <!channel> & result" * (200 if long else 1)
    try:
        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=client) as build:
            await adapter.send_notification(
                "opaque-token",
                OutgoingMessage(platform_chat_id="D123:123.456", text=text),
                context_url=link,
            )
    finally:
        await adapter.aclose()
    build.assert_called_once_with(token="opaque-token", retry_handlers=[])
    sent = client.chat_postMessage.await_args.kwargs
    assert sent["channel"] == "D123" and sent["thread_ts"] == "123.456"
    assert sent["blocks"][0]["text"]["type"] == "plain_text"
    assert len(sent["blocks"][0]["text"]["text"]) <= 3000
    assert "<@U123>" not in sent["text"]
    assert "&lt;@U123&gt;" in sent["text"]
    assert not sent["link_names"] and not sent["unfurl_links"] and not sent["unfurl_media"]
    if link:
        assert sent["blocks"][1]["elements"][0]["url"] == link
        assert sent["blocks"][1]["elements"][0]["action_id"] == "open_notification"
    else:
        assert len(sent["blocks"]) == 1


@pytest.mark.parametrize("status", [200, 429, 500])
async def test_only_http_rate_limit_refusal_allows_a_durable_retry(status: int) -> None:
    response = AsyncSlackResponse(
        client=MagicMock(),
        http_verb="POST",
        api_url="https://slack.com/api/chat.postMessage",
        req_args={},
        data={"ok": False, "error": "ratelimited" if status == 429 else "unknown_error"},
        headers={"retry-after": "17"},
        status_code=status,
    )
    error = SlackApiError("provider response", response)
    client = MagicMock(chat_postMessage=AsyncMock(side_effect=error))
    adapter = SlackAdapter()
    try:
        with patch("slack_sdk.web.async_client.AsyncWebClient", return_value=client):
            with pytest.raises(
                NotificationRateLimited if status == 429 else SlackApiError
            ) as caught:
                await adapter.send_notification(
                    "token",
                    OutgoingMessage(platform_chat_id="D123", text="Notice"),
                    context_url=None,
                )
            if status == 429:
                assert caught.value.retry_after_seconds == 17
    finally:
        await adapter.aclose()
    client.chat_postMessage.assert_awaited_once()


@pytest.mark.parametrize("pending,has_time", [(True, False), (False, True)])
async def test_safe_retry_cannot_be_persisted_without_a_pending_state_and_deadline(
    pending: bool, has_time: bool
) -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.repositories import notification_repo

    db = MagicMock(execute=AsyncMock())
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="pending state and retry time"):
        await notification_repo.settle_delivery(
            db,
            delivery_id=uuid4(),
            claimed_at=now,
            status="pending" if pending else "sent",
            retry_safe=True,
            retry_at=now if has_time else None,
        )
    db.execute.assert_not_awaited()
