"""What a verified WhatsApp batch does: record each customer's window, queue their messages (#2076)."""

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels.base import IncomingMessage, IncomingPress
from app.services.channels.whatsapp_inbound import WhatsAppInbound, handle_customer
from app.services.channels.whatsapp_payload import ParsedWebhook, parse_webhook
from tests.test_whatsapp_payload import FIXTURES

pytestmark = pytest.mark.anyio

MODULE = "app.services.channels.whatsapp_inbound"
ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
NOW = int(time.time())


def _bot() -> MagicMock:
    return MagicMock(id=uuid.uuid4(), organization_id=ORG)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _batch(*messages: tuple[str, str, int, str]) -> ParsedWebhook:
    """Text messages as `(wamid, customer, age in seconds, text)`, in the order given."""
    payload = _fixture("text")
    value = payload["entry"][0]["changes"][0]["value"]
    template = value["messages"][0]
    value["messages"] = [
        {
            **template,
            "id": wamid,
            "from_user_id": user,
            "timestamp": str(NOW - age),
            "text": {"body": text},
        }
        for wamid, user, age, text in messages
    ]
    return _parse(payload)


def _parse(payload: dict[str, Any]) -> ParsedWebhook:
    return parse_webhook(
        payload,
        phone_number_id="PNID1",
        account_id="WABA1",
        now=datetime.fromtimestamp(NOW, UTC),
    )


def _at(age: int) -> datetime:
    return datetime.fromtimestamp(NOW - age, UTC)


async def _receive(
    parsed: ParsedWebhook,
) -> tuple[MagicMock, MagicMock, MagicMock, list[list[IncomingMessage | IncomingPress]]]:
    """Run `receive` with the repository and the queue doubled, then run what it queued.

    Returns the repository double, the queue double, the bot, and what each queued
    customer's task handed the router.
    """
    bot = _bot()
    routed: list[list[IncomingMessage | IncomingPress]] = []

    async def process(events: list[IncomingMessage | IncomingPress]) -> None:
        routed.append(events)

    with (
        patch(f"{MODULE}.whatsapp_customer_repo.record_inbound", AsyncMock()) as record,
        patch(f"{MODULE}.spawn_after_commit") as spawn,
        patch(f"{MODULE}.process_channel_events_in_order", process),
    ):
        await WhatsAppInbound(MagicMock()).receive(bot, parsed)
        for call in spawn.call_args_list:
            await call.args[1]
    return record, spawn, bot, routed


async def test_each_customer_is_recorded_once_with_their_latest_time():
    parsed = _batch(
        ("wamid.1", "US.111", 300, "a"),
        ("wamid.3", "US.222", 100, "c"),
        ("wamid.2", "US.111", 200, "b"),
    )
    record, _, bot, _ = await _receive(parsed)

    assert [(c.kwargs["bsuid"], c.kwargs["sent_at"]) for c in record.await_args_list] == [
        ("US.111", _at(200)),
        ("US.222", _at(100)),
    ]
    assert all(
        c.kwargs["bot_id"] == bot.id and c.kwargs["organization_id"] == ORG
        for c in record.await_args_list
    )


async def test_customers_are_recorded_in_bsuid_order_whatever_order_they_wrote():
    parsed = _batch(("wamid.1", "US.222", 300, "a"), ("wamid.2", "US.111", 200, "b"))
    record, _, _, _ = await _receive(parsed)

    assert [c.kwargs["bsuid"] for c in record.await_args_list] == ["US.111", "US.222"]


async def test_a_tap_and_a_refused_sender_open_the_window_too():
    """Any message Meta delivered says the customer is there, whatever the router decides."""
    tap = _fixture("button_reply")
    tap["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = str(NOW - 5)
    record, _, _, routed = await _receive(_parse(tap))
    record.assert_awaited_once()
    assert record.await_args.kwargs["sent_at"] == _at(5)
    assert isinstance(routed[0][0], IncomingPress)

    record, _, _, _ = await _receive(_batch(("wamid.9", "US.stranger", 7, "let me in")))
    assert record.await_args.kwargs["bsuid"] == "US.stranger"
    assert record.await_args.kwargs["sent_at"] == _at(7)


async def test_a_status_never_moves_the_window():
    record, spawn, _, _ = await _receive(_parse(_fixture("statuses")))

    record.assert_not_awaited()
    spawn.assert_not_called()


async def test_each_customer_is_handled_after_the_commit_oldest_first():
    parsed = _batch(
        ("wamid.2", "US.111", 10, "second"),
        ("wamid.9", "US.222", 15, "other"),
        ("wamid.1", "US.111", 30, "first"),
    )
    _, spawn, bot, routed = await _receive(parsed)

    assert [call.kwargs["name"] for call in spawn.call_args_list] == [
        f"whatsapp_events:{bot.id}"
    ] * 2
    assert [[e.text for e in events] for events in routed] == [["first", "second"], ["other"]]


async def test_handling_turns_messages_and_taps_into_events_in_order():
    payload = _fixture("text")
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"][0]["timestamp"] = str(NOW - 20)
    tap = _fixture("button_reply")["entry"][0]["changes"][0]["value"]["messages"][0]
    tap["timestamp"] = str(NOW - 2)
    value["messages"].append(tap)
    messages = _parse(payload).messages

    process = AsyncMock()
    with patch(f"{MODULE}.process_channel_events_in_order", process):
        await handle_customer("bot-1", ORG, "US.111", list(messages))

    (events,) = process.await_args.args
    assert [type(e) for e in events] == [IncomingMessage, IncomingPress]
    assert [e.platform_user_id for e in events] == [f"{ORG}:US.111"] * 2
    assert events[0].bot_id == "bot-1"
    assert events[0].text == "hello bot"
    assert events[1].value == "aos:0123456789abcdef0123456789abcdef:0"


async def test_a_text_message_is_queued_as_an_incoming_message():
    *_, [events] = await _receive(_batch(("wamid.A1", "US.111", 5, "hello bot")))

    (incoming,) = events
    assert isinstance(incoming, IncomingMessage)
    assert incoming.platform == "whatsapp"
    assert incoming.platform_user_id == f"{ORG}:US.111"
    assert incoming.platform_chat_id == "US.111"
    assert incoming.chat_type == "private"
    assert incoming.message_id == "wamid.A1"
    assert incoming.text == "hello bot"


async def test_a_tap_and_a_message_keep_their_order():
    """The tap answers the question the text before it left open: one task, in Meta's order."""
    payload = _fixture("text")
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"][0]["timestamp"] = str(NOW - 20)
    tap = _fixture("button_reply")["entry"][0]["changes"][0]["value"]["messages"][0]
    tap["timestamp"] = str(NOW - 2)
    value["messages"].append(tap)

    *_, [events] = await _receive(_parse(payload))

    assert [type(e) for e in events] == [IncomingMessage, IncomingPress]


async def test_a_template_button_tap_is_routed_as_a_message():
    payload = _fixture("template_button")
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = str(NOW - 2)

    *_, [[event]] = await _receive(_parse(payload))

    assert isinstance(event, IncomingMessage)
    assert event.text == "Show me"
