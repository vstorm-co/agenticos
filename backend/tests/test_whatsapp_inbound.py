"""What a verified WhatsApp batch does: record each customer's window, queue their messages (#2076)."""

import contextlib
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.services.channels import whatsapp_inbound as inbound
from app.services.channels.base import IncomingMessage, IncomingPress, OutgoingMessage
from app.services.channels.formatting import STRANGER_REFUSAL
from app.services.channels.handback import (
    EXPIRED_NOTICE,
    STOPPED_NOTICE,
    STRANDED_NOTICE,
)
from app.services.channels.mentions import UnaddressedMessage
from app.services.channels.router import Admission, ChannelMessageRouter, chat_lock
from app.services.channels.whatsapp_customers import Held, WindowStore
from app.services.channels.whatsapp_graph import WhatsAppGraphError
from app.services.channels.whatsapp_inbound import (
    WhatsAppInbound,
    _deliver_answers,
    _offer_again,
    handle_customer,
)
from app.services.channels.whatsapp_payload import (
    ParsedWebhook,
    WhatsAppMessage,
    parse_webhook,
    platform_user_id_for,
)
from app.services.channels.whatsapp_templates import LateTemplate
from app.services.channels.whatsapp_window import FILES_NOT_DELIVERED, NUDGE_REPLY_ID, NUDGE_THANKS
from tests.test_whatsapp_payload import FIXTURES

pytestmark = pytest.mark.anyio

MODULE = "app.services.channels.whatsapp_inbound"
_KEEP_PHONE = inbound._keep_phone


@pytest.fixture(autouse=True)
def _no_number_is_kept():
    """The number's own tests put the real function back; every other test leaves it out."""
    with patch(f"{MODULE}._keep_phone", AsyncMock()):
        yield


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
        patch(f"{MODULE}.WindowStore", lambda: StubStore([], order=[])),
        patch(f"{MODULE}.reclaim_after_refusal", AsyncMock()),
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
    record, _, _, routed = await _receive(_parse(_fixture("statuses")))

    record.assert_not_awaited()
    assert routed == []


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


BOT = "22222222-2222-2222-2222-222222222222"
CHAT = "US.111"
PARKED = "awaiting_answer"


def _answer_id(run_id: uuid.UUID) -> uuid.UUID:
    """The id of the saved answer `World.run` gives a run."""
    return uuid.uuid5(uuid.NAMESPACE_URL, str(run_id))


class StubStore(WindowStore):
    """The held rows in memory, with the claim and settle rules the real store has."""

    def __init__(
        self,
        rows: list[Held],
        *,
        window: bool | None = True,
        order: list[str],
        template: LateTemplate | Exception | None = None,
    ) -> None:
        super().__init__()
        self.template = template
        self.rows = list(rows)
        self.claimed: set[uuid.UUID] = set()
        self.window_state = window
        self.order = order
        self.settled: list[tuple[str, uuid.UUID]] = []
        self.held_new: list[uuid.UUID] = []
        self.closures: list[datetime] = []
        self.hold_is_new = True
        self.superseded: set[uuid.UUID] = set()
        """Rows a newer claim has taken: settling them writes nothing and reports it."""
        self.reheld: set[uuid.UUID] = set()
        """Rows held again during the send: the answer settlement gives the claim back."""
        self.supersede_after_answer: set[uuid.UUID] = set()
        """Rows a newer claim takes right after their answer settles."""

    async def late_template(self, bot_id: str) -> LateTemplate | None:
        if isinstance(self.template, Exception):
            raise self.template
        return self.template

    async def has_held(self, bot_id: str, chat_id: str, *, now: datetime) -> bool:
        return any(
            row.id not in self.claimed or row.answer or row.files or row.notice is not None
            for row in self.rows
        )

    async def claim_held(self, bot_id: str, chat_id: str, *, now: datetime) -> list[Held]:
        taken = [row for row in self.rows if row.id not in self.claimed]
        self.claimed |= {row.id for row in taken}
        return taken

    async def window(self, bot_id: str, chat_id: str, *, now: datetime) -> bool | None:
        return self.window_state

    async def answer_sent(
        self, held: Held, *, prompts_owed: bool, keep_notice: bool = False
    ) -> bool:
        self.settled.append(("answer_sent", held.id))
        if held.id in self.superseded:
            return False
        if held.id in self.reheld:
            self.superseded.add(held.id)
            return True
        if held.id in self.supersede_after_answer:
            self.superseded.add(held.id)
        self.rows = [
            replace(row, answer=False, files=False, notice=row.notice if keep_notice else None)
            if row.id == held.id
            else row
            for row in self.rows
            if row.id != held.id or prompts_owed or keep_notice
        ]
        return True

    async def notice_sent(self, held: Held) -> bool:
        self.settled.append(("notice_sent", held.id))
        if held.id in self.superseded:
            return False
        self.rows = [replace(row, notice=None) if row.id == held.id else row for row in self.rows]
        return True

    async def done(self, held: Held) -> bool:
        self.settled.append(("done", held.id))
        if held.id in self.superseded:
            return False
        self.rows = [row for row in self.rows if row.id != held.id]
        return True

    async def holds(self, held: Held) -> bool:
        return held.id not in self.superseded

    async def release(self, held: Held) -> None:
        self.settled.append(("release", held.id))
        self.claimed.discard(held.id)

    async def close(self, bot_id: str, chat_id: str, *, at: datetime) -> bool:
        self.closures.append(at)
        return True

    async def hold_new(self, bot_id: str, chat_id: str, *, run_id: str) -> bool:
        if self.hold_is_new:
            self.held_new.append(uuid.UUID(run_id))
            self.rows.append(
                Held(
                    id=uuid.uuid4(),
                    run_id=uuid.UUID(run_id),
                    answer=True,
                    files=False,
                    message_id=_answer_id(uuid.UUID(run_id)),
                )
            )
        return self.hold_is_new

    def settled_ids(self, kind: str) -> list[uuid.UUID]:
        return [row_id for name, row_id in self.settled if name == kind]


class World:
    """Everything the held-answer code reaches, doubled; `order` records what happened when."""

    def __init__(self) -> None:
        self.order: list[str] = []
        self.runs: dict[uuid.UUID, MagicMock] = {}
        self.answers: dict[uuid.UUID, str | None] = {}
        self.messages: dict[uuid.UUID, str] = {}
        self.offer_kwargs: list[dict[str, Any]] = []
        self.routed: list[list[IncomingMessage | IncomingPress]] = []
        self.sent: list[OutgoingMessage] = []
        self.offered: list[uuid.UUID] = []
        self.unoffered: set[uuid.UUID] = set()
        """Runs whose prompts `offer` reports it could not put in front of the chat."""
        self.verdict: str = "admitted"
        self.sender_gone = False
        self.session_errors: list[str] = []
        """The type of what each session's body raised; a clean exit adds nothing."""
        self.session: MagicMock | None = None
        self.sessions = 0

    def run(self, *, status: str = "completed", answer: str | None = "the answer") -> MagicMock:
        run = MagicMock(
            id=uuid.uuid4(),
            status=status,
            surface="whatsapp",
            conversation_id=uuid.uuid4(),
            runs_as_agent=False,
        )
        self.runs[run.id] = run
        self.answers[run.id] = answer
        return run

    def held(
        self,
        run: MagicMock,
        *,
        answer: bool = True,
        files: bool = False,
        message: uuid.UUID | None = None,
        notice: str | None = None,
    ) -> Held:
        """A row for the run's answer, or for the saved `message` it names instead."""
        return Held(
            id=uuid.uuid4(),
            run_id=run.id,
            answer=answer,
            files=files,
            message_id=message or (_answer_id(run.id) if answer else None),
            notice=notice,
        )

    def say(self, text: str) -> uuid.UUID:
        """Another saved answer, owed by a row that names it."""
        message_id = uuid.uuid4()
        self.messages[message_id] = text
        return message_id

    def store(self, rows: list[Held], **kwargs: Any) -> StubStore:
        return StubStore(rows, order=self.order, **kwargs)


@pytest.fixture
def world() -> Iterator[World]:
    world = World()

    @asynccontextmanager
    async def sessions() -> AsyncGenerator[MagicMock]:
        world.sessions += 1
        try:
            yield MagicMock()
        except BaseException as failure:
            world.session_errors.append(type(failure).__name__)
            raise

    async def get_run(
        db: Any, run_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> MagicMock | None:
        assert organization_id == ORG
        return world.runs.get(run_id)

    async def last_answer(db: Any, run_id: uuid.UUID, *, organization_id: uuid.UUID) -> Any:
        text = world.answers.get(run_id)
        return None if text is None else MagicMock(content=text)

    async def answer_message(
        db: Any, message_id: uuid.UUID, *, run_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Any:
        assert organization_id == ORG
        text = (
            world.answers.get(run_id)
            if message_id == _answer_id(run_id)
            else world.messages.get(message_id)
        )
        return None if text is None else MagicMock(content=text)

    async def send(token: str, message: OutgoingMessage) -> None:
        world.order.append("answer")
        world.sent.append(message)

    async def offer(
        bot: Any, *, platform: str, platform_chat_id: str, run_id: uuid.UUID, resend: bool = False
    ) -> bool:
        world.order.append("offer")
        world.offered.append(run_id)
        world.offer_kwargs.append({"platform": platform, "resend": resend})
        return run_id not in world.unoffered

    async def incoming_for_run(
        db: Any, run: Any, *, bot_id: uuid.UUID, platform_chat_id: str
    ) -> IncomingMessage | None:
        assert (bot_id, platform_chat_id) == (uuid.UUID(BOT), CHAT)
        if world.sender_gone:
            return None
        return IncomingMessage(
            platform="whatsapp",
            bot_id=BOT,
            platform_user_id=f"{ORG}:{CHAT}",
            platform_chat_id=CHAT,
            chat_type="private",
            text="",
        )

    async def admission(db: Any, run: Any, incoming: IncomingMessage) -> Admission:
        assert (incoming.platform, incoming.bot_id, incoming.platform_chat_id) == (
            "whatsapp",
            BOT,
            CHAT,
        )
        return Admission(world.verdict, "test")  # type: ignore[arg-type]

    async def process(events: list[IncomingMessage | IncomingPress]) -> None:
        world.order.append("route")
        world.routed.append(events)

    adapter = MagicMock(send_message=AsyncMock(side_effect=send), send_held_preview=AsyncMock())
    world.adapter = adapter
    world.offer = AsyncMock(side_effect=offer)
    world.admission = AsyncMock(side_effect=admission)
    bot = MagicMock(is_active=True, organization_id=ORG)
    world.bot = AsyncMock(return_value=bot)
    prompts = MagicMock(return_value=MagicMock(offer=world.offer))
    router = MagicMock(return_value=MagicMock(admission=world.admission))
    with (
        patch(f"{MODULE}.get_db_context", sessions),
        patch(f"{MODULE}.agent_run_repo.get_run", get_run),
        patch(f"{MODULE}.channel_bot_repo.get_for_org", world.bot),
        patch(f"{MODULE}.conversation_repo.last_answer_message", last_answer),
        patch(f"{MODULE}.conversation_repo.answer_message", answer_message),
        patch(f"{MODULE}.unseal_bot_token", return_value="tok"),
        patch(f"{MODULE}.whatsapp_adapter", return_value=adapter),
        patch(f"{MODULE}.ChannelPrompts", prompts),
        patch(f"{MODULE}.ChannelMessageRouter", router),
        patch(f"{MODULE}.incoming_for_run", incoming_for_run),
        patch(f"{MODULE}.process_channel_events_in_order", process),
    ):
        yield world


def _text(text: str = "any news?") -> list[WhatsAppMessage]:
    return list(_batch(("wamid.N1", CHAT, 5, text)).messages)


def _template(button: str | None) -> LateTemplate:
    return LateTemplate(name="late_answer", language="en_US", body="Update: {{1}}", button=button)


def _tap(label: str = "Show me") -> list[WhatsAppMessage]:
    payload = _fixture("template_button")
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message["timestamp"] = str(NOW - 2)
    message["button"] = {"payload": label, "text": label}
    return list(_parse(payload).messages)


def _nudge_tap(reply_id: str = NUDGE_REPLY_ID) -> list[WhatsAppMessage]:
    payload = _fixture("button_reply")
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message["timestamp"] = str(NOW - 2)
    message["interactive"]["button_reply"] = {"id": reply_id, "title": "Keep me posted"}
    return list(_parse(payload).messages)


async def _handle(
    world: World, store: StubStore, messages: list[WhatsAppMessage] | None = None
) -> None:
    await handle_customer(
        BOT, ORG, CHAT, messages if messages is not None else _text(), store=store
    )


class TestHeldAnswers:
    async def test_a_reoffered_question_does_not_take_the_message_that_triggered_it(self, world):
        """The message is routed as a new turn before the question exists to claim it."""
        run = world.run(status=PARKED)
        store = world.store([world.held(run)])

        await _handle(world, store)

        assert world.order == ["answer", "route", "offer"]
        [events] = world.routed
        assert [(type(e), e.text) for e in events] == [(IncomingMessage, "any news?")]
        assert world.offered == [run.id]

    async def test_the_held_answer_goes_out_before_the_new_message_is_routed(self, world):
        run = world.run(answer="Report ready.")
        store = world.store([world.held(run)])

        await _handle(world, store)

        assert world.order == ["answer", "route"]
        [message] = world.sent
        assert (message.run_id, message.text, message.platform_chat_id) == (
            str(run.id),
            "Report ready.",
            CHAT,
        )

    async def test_held_answers_go_out_oldest_first(self, world):
        runs = [world.run(answer=f"answer {n}") for n in range(3)]
        store = world.store([world.held(run) for run in runs])

        await _handle(world, store)

        assert [m.text for m in world.sent] == ["answer 0", "answer 1", "answer 2"]
        assert store.rows == []

    async def test_nothing_held_routes_without_taking_the_chat_lock(self, world):
        store = world.store([])

        async def hold() -> None:
            async with chat_lock(BOT, CHAT):
                with anyio.fail_after(1):
                    await _handle(world, store)

        await hold()
        assert world.order == ["route"]

    async def test_a_held_delivery_waits_for_the_chats_turn(self, world):
        run = world.run()
        store = world.store([world.held(run)])
        sent = anyio.Event()
        send = world.adapter.send_message.side_effect

        async def notify(token: str, message: OutgoingMessage) -> None:
            await send(token, message)
            sent.set()

        world.adapter.send_message.side_effect = notify
        async with anyio.create_task_group() as tasks:
            async with chat_lock(BOT, CHAT):
                tasks.start_soon(_handle, world, store)
                await anyio.sleep(0.1)
                assert world.sent == []
            with anyio.fail_after(1):
                await sent.wait()
        assert world.order == ["answer", "route"]

    async def test_the_chats_lock_is_held_while_sending_and_offering_but_not_while_routing(
        self, world
    ):
        run = world.run(status=PARKED)
        store = world.store([world.held(run)])
        free: dict[str, bool] = {}

        async def probe(name: str) -> None:
            with anyio.move_on_after(0.05) as scope:
                async with chat_lock(BOT, CHAT):
                    pass
            free[name] = not scope.cancelled_caught

        sends, offers = world.adapter.send_message.side_effect, world.offer.side_effect

        async def send(token: str, message: OutgoingMessage) -> None:
            await probe("send")
            await sends(token, message)

        async def route(events: list[Any]) -> None:
            await probe("route")

        async def offer(bot: Any, **kwargs: Any) -> bool:
            await probe("offer")
            return await offers(bot, **kwargs)

        world.adapter.send_message.side_effect = send
        world.offer.side_effect = offer
        with patch(f"{MODULE}.process_channel_events_in_order", route):
            await _handle(world, store)

        assert free == {"send": False, "route": True, "offer": False}

    async def test_two_late_answers_of_one_run_are_each_sent_once_in_order(self, world):
        """Each row owes the message it names, never "the run's latest" saved answer."""
        run = world.run(answer="the third, latest answer")
        first, second = world.say("first answer"), world.say("second answer")
        store = world.store([world.held(run, message=first), world.held(run, message=second)])

        await _handle(world, store)

        assert [m.text for m in world.sent] == ["first answer", "second answer"]
        assert {m.run_id for m in world.sent} == {str(run.id)}
        assert store.rows == []
        assert len(store.settled_ids("answer_sent")) == 2

    async def test_a_run_with_two_answers_and_a_question_offers_it_once_after_the_last(self, world):
        run = world.run(status=PARKED)
        rows = [
            world.held(run, message=world.say("first answer")),
            world.held(run, message=world.say("second answer")),
            world.held(run, answer=False),
        ]
        store = world.store(rows)

        await _handle(world, store)

        assert [m.text for m in world.sent] == ["first answer", "second answer"]
        assert world.order == ["answer", "answer", "route", "offer"]
        assert world.offered == [run.id]
        # The first message of the prompt never arrived, so it is sent again.
        assert world.offer_kwargs == [{"platform": "whatsapp", "resend": True}]

    async def test_a_failed_second_answer_stays_held_and_the_first_is_not_sent_again(self, world):
        run = world.run()
        first, second = world.say("first answer"), world.say("second answer")
        store = world.store([world.held(run, message=first), world.held(run, message=second)])
        world.adapter.send_message.side_effect = [None, WhatsAppGraphError(code=131000)]

        await _handle(world, store)
        assert [row.message_id for row in store.rows] == [second]
        assert store.settled_ids("release") == [row.id for row in store.rows]

        world.adapter.send_message.side_effect = None
        await _handle(world, store)
        assert [c.args[1].text for c in world.adapter.send_message.await_args_list] == [
            "first answer",
            "second answer",
            "second answer",
        ]

    async def test_an_answer_whose_message_is_gone_says_done(self, world):
        run = world.run()
        await _handle(world, world.store([world.held(run, message=uuid.uuid4())]))
        assert [m.text for m in world.sent] == ["Done."]

    async def test_a_held_stop_notice_is_delivered_once_before_the_message_is_routed(self, world):
        run = world.run(status="cancelled")
        row = world.held(run, answer=False, notice="stopped")
        store = world.store([row])

        await _handle(world, store)
        await _handle(world, store)

        assert world.order == ["answer", "route", "route"]
        [message] = world.sent
        assert (message.text, message.notice, message.run_id) == (
            STOPPED_NOTICE,
            "stopped",
            str(run.id),
        )
        assert store.settled == [("done", row.id)]

    @pytest.mark.parametrize("as_agent", [True, False])
    async def test_a_held_stop_notice_names_the_console_only_to_a_member(self, world, as_agent):
        run = world.run(status="cancelled", answer=None)
        run.runs_as_agent = as_agent
        store = world.store([world.held(run, answer=False, notice="stopped")])

        await _handle(world, store)

        [message] = world.sent
        assert message.text == ("This request was stopped." if as_agent else STOPPED_NOTICE)

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("as_agent", "status", "expected"),
        [
            (
                True,
                "awaiting_approval",
                "A person at the company needs to decide this. The answer will come back here.",
            ),
            (True, "completed", "Done."),
            (False, "awaiting_approval", "Done."),
        ],
    )
    async def test_a_held_answer_with_no_saved_words(self, world, as_agent, status, expected):
        run = world.run(status=status, answer=None)
        run.runs_as_agent = as_agent
        row = world.held(run)
        store = world.store([row])

        await _deliver_answers(BOT, ORG, CHAT, store)

        assert [m.text for m in world.sent] == [expected]

    async def test_a_held_answer_and_a_held_notice_go_out_oldest_first(self, world):
        noticed, answered = world.run(status="cancelled"), world.run(answer="Report ready.")
        store = world.store(
            [
                world.held(noticed, answer=False, notice="stopped"),
                world.held(answered),
            ]
        )

        await _handle(world, store)

        assert [(m.text, m.notice) for m in world.sent] == [
            (STOPPED_NOTICE, "stopped"),
            ("Report ready.", None),
        ]

    async def test_a_row_owing_an_answer_and_a_notice_sends_the_answer_first(self, world):
        run = world.run(answer="Report ready.")
        row = world.held(run, notice="expired")
        store = world.store([row])

        await _handle(world, store)

        assert [(m.text, m.notice) for m in world.sent] == [
            ("Report ready.", None),
            (EXPIRED_NOTICE, "expired"),
        ]
        assert store.settled == [("answer_sent", row.id), ("done", row.id)]
        assert store.rows == []

    async def test_a_notice_that_fails_after_its_answer_goes_alone_next_time(self, world):
        run = world.run(answer="Report ready.")
        row = world.held(run, notice="expired")
        store = world.store([row])
        world.adapter.send_message.side_effect = [None, WhatsAppGraphError(code=131000)]

        def sent() -> list[str]:
            return [c.args[1].text for c in world.adapter.send_message.await_args_list]

        await _handle(world, store)
        assert sent() == ["Report ready.", EXPIRED_NOTICE]
        assert store.settled == [("answer_sent", row.id), ("release", row.id)]
        assert [(r.answer, r.notice) for r in store.rows] == [(False, "expired")]

        world.adapter.send_message.side_effect = None
        await _handle(world, store)
        assert sent() == ["Report ready.", EXPIRED_NOTICE, EXPIRED_NOTICE]
        assert store.rows == []

    async def test_a_failed_notice_send_keeps_the_row(self, world):
        run = world.run(status="cancelled")
        row = world.held(run, answer=False, notice="stopped")
        store = world.store([row])
        world.adapter.send_message.side_effect = WhatsAppGraphError(code=131000)

        await _handle(world, store)

        assert store.settled == [("release", row.id)]
        assert store.rows == [row]

    async def test_a_notice_for_a_run_that_is_gone_is_settled(self, world):
        row = Held(
            id=uuid.uuid4(), run_id=uuid.uuid4(), answer=False, files=False, notice="stopped"
        )
        store = world.store([row])

        await _handle(world, store)

        assert world.sent == [] and store.settled == [("done", row.id)]

    async def test_a_notice_whose_chat_moved_is_settled_unsent(self, world):
        run = world.run(status="cancelled")
        row = world.held(run, answer=False, notice="stopped")
        store = world.store([row])
        world.sender_gone = True

        await _handle(world, store)

        assert world.sent == [] and store.settled == [("done", row.id)]

    async def test_a_notice_whose_sender_is_refused_is_settled_unsent(self, world):
        run = world.run(status="cancelled")
        row = world.held(run, answer=False, notice="refused")
        store = world.store([row])
        world.verdict = "refused"

        await _handle(world, store)

        assert world.sent == [] and store.settled == [("done", row.id)]

    async def test_an_unknown_notice_key_sends_nothing_and_settles_the_row(self, world):
        run = world.run(status="cancelled")
        row = world.held(run, answer=False, notice="not-a-sentence")
        store = world.store([row])

        await _handle(world, store)

        assert world.sent == [] and store.settled == [("done", row.id)]

    async def test_a_notice_row_with_prompts_owed_keeps_them_after_the_sentence(self, world):
        run = world.run(status=PARKED)
        row = world.held(run, answer=False, notice="stranded")
        store = world.store([row])

        await _handle(world, store)

        assert [m.text for m in world.sent] == [STRANDED_NOTICE]
        assert store.settled[0] == ("notice_sent", row.id)
        assert world.offered == [run.id]
        assert world.order == ["answer", "route", "offer"]

    async def test_a_notice_row_whose_sender_is_refused_keeps_its_prompts(self, world):
        run = world.run(status=PARKED)
        row = world.held(run, answer=False, notice="stranded")
        store = world.store([row])
        world.verdict = "refused"

        await _handle(world, store)

        assert world.sent == [] and world.offered == []
        assert store.settled == [("notice_sent", row.id), ("release", row.id)]
        assert [r.notice for r in store.rows] == [None]

    async def test_an_answer_row_that_is_not_admitted_keeps_its_notice_too(self, world):
        run = world.run()
        row = world.held(run, notice="expired")
        store = world.store([row])
        world.verdict = "refused"

        await _handle(world, store)

        assert world.sent == [] and store.settled == [("release", row.id)]
        assert store.rows == [row]

    async def test_a_failing_window_store_still_routes_the_message(self, world, caplog):
        store = world.store([])
        store.has_held = AsyncMock(side_effect=RuntimeError("boom for US.111"))  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING):
            await _handle(world, store)

        assert world.order == ["route"]
        record = next(r for r in caplog.records if r.message == "whatsapp_held_failed")
        assert (record.bot_id, record.error) == (BOT, "RuntimeError")
        assert record.exc_info is None
        assert "boom" not in caplog.text and CHAT not in caplog.text

    async def test_a_failed_send_leaves_the_run_held_and_its_reason(self, world, caplog):
        first, second = world.run(), world.run()
        store = world.store([world.held(first), world.held(second)])
        world.adapter.send_message.side_effect = WhatsAppGraphError(code=131000)

        with caplog.at_level(logging.WARNING):
            await _handle(world, store)

        assert store.settled_ids("answer_sent") == []
        assert store.settled_ids("release") == [row.id for row in store.rows]
        assert len(store.rows) == 2
        assert world.order == ["route"]
        [record] = [r for r in caplog.records if r.message == "whatsapp_held_send_failed"]
        assert (record.bot_id, record.run_id, record.error) == (
            BOT,
            str(first.id),
            "WhatsAppGraphError",
        )

    async def test_the_reason_is_cleared_only_after_the_send(self, world):
        run = world.run()
        store = world.store([world.held(run)])
        seen: list[int] = []

        async def answer_sent(held: Held, *, prompts_owed: bool) -> None:
            seen.append(world.adapter.send_message.await_count)

        store.answer_sent = answer_sent  # type: ignore[method-assign]
        await _handle(world, store)

        assert seen == [1]

    @pytest.mark.security
    @pytest.mark.parametrize("why", ["refused", "sender_gone"])
    async def test_a_sender_no_longer_admitted_keeps_the_run_held(self, world, why):
        run = world.run()
        row = world.held(run)
        store = world.store([row])
        if why == "refused":
            world.verdict = "refused"
        else:
            world.sender_gone = True

        await _handle(world, store)

        assert world.sent == []
        assert store.settled == [("release", row.id)]
        assert world.order == ["route"]

    async def test_an_admission_the_platform_cannot_confirm_still_delivers(self, world):
        """Only a definite refusal holds an answer back; an unanswered check does not."""
        run = world.run()
        row = world.held(run)
        store = world.store([row])
        world.verdict = "unconfirmed"

        await _handle(world, store)

        assert world.order == ["answer", "route"]
        assert [m.text for m in world.sent] == ["the answer"]
        assert store.settled_ids("release") == []

    async def test_a_stale_message_does_not_deliver_into_a_closed_window(self, world):
        run = world.run()
        row = world.held(run)
        store = world.store([row], window=False)

        await _handle(world, store)

        assert world.sent == []
        assert store.settled == [("release", row.id)]
        assert world.order == ["route"]

    async def test_a_bot_that_is_gone_or_off_delivers_nothing(self, world):
        run = world.run()
        row = world.held(run)
        for bot in (None, MagicMock(is_active=False, organization_id=ORG)):
            world.bot.return_value = bot
            store = world.store([row])
            await _handle(world, store)
            assert world.sent == []
            assert store.settled == [("release", row.id)]

    async def test_a_run_with_no_saved_answer_sends_done(self, world):
        for saved in (None, "  \n"):
            run = world.run(answer=saved)
            await _handle(world, world.store([world.held(run)]))
        assert [m.text for m in world.sent] == ["Done.", "Done."]

    async def test_the_saved_answer_is_sent_as_saved(self, world):
        run = world.run(answer="Line one.\n\n**Line two** [x](http://e.test)")
        await _handle(world, world.store([world.held(run)]))

        assert world.sent[0].text == "Line one.\n\n**Line two** [x](http://e.test)"

    async def test_a_held_answer_with_files_says_they_could_not_follow(self, world):
        run = world.run(answer="Here is the chart.")
        await _handle(world, world.store([world.held(run, files=True)]))

        assert world.sent[0].text.endswith(FILES_NOT_DELIVERED)
        assert world.sent[0].text.startswith("Here is the chart.")

    async def test_a_show_me_tap_is_not_answered_after_a_held_answer(self, world):
        run = world.run()
        store = world.store([world.held(run)], template=_template("Show me"))

        with patch(f"{MODULE}.claim_delivery", AsyncMock()) as claim:
            await _handle(world, store, _tap())

        assert len(world.sent) == 1
        assert world.routed == []
        claim.assert_awaited_once()
        assert claim.await_args.args[0].message_id == "wamid.T1"

    async def test_a_show_me_tap_is_not_answered_after_an_answer_and_its_notice(self, world):
        run = world.run()
        store = world.store([world.held(run, notice="expired")], template=_template("Show me"))

        with patch(f"{MODULE}.claim_delivery", AsyncMock()) as claim:
            await _handle(world, store, _tap())

        assert [m.text for m in world.sent] == ["the answer", EXPIRED_NOTICE]
        assert world.routed == []
        claim.assert_awaited_once()

    async def test_a_settlement_that_fails_is_logged_as_one_and_gives_the_row_back(
        self, world, caplog
    ):
        run = world.run()
        row = world.held(run, notice="expired")
        store = world.store([row])
        store.answer_sent = AsyncMock(side_effect=RuntimeError("db for US.111"))  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING):
            await _handle(world, store)

        [record] = [r for r in caplog.records if r.message == "whatsapp_held_settle_failed"]
        assert (record.bot_id, record.run_id, record.error) == (BOT, str(run.id), "RuntimeError")
        assert not [r for r in caplog.records if r.message == "whatsapp_held_send_failed"]
        assert "US.111" not in caplog.text
        assert [m.text for m in world.sent] == ["the answer"]
        assert store.settled == [("release", row.id)]

    async def test_another_template_button_after_a_held_answer_is_routed(self, world):
        run = world.run()
        store = world.store([world.held(run)], template=_template("Show me"))

        await _handle(world, store, _tap("Stop"))

        assert [e.text for e in world.routed[0]] == ["Stop"]

    async def test_a_show_me_tap_is_routed_when_the_template_has_no_stored_button(self, world):
        run = world.run()
        store = world.store([world.held(run)], template=_template(None))

        await _handle(world, store, _tap())

        assert [e.text for e in world.routed[0]] == ["Show me"]

    async def test_a_show_me_tap_is_routed_when_there_is_no_template_and_nothing_is_logged(
        self, world, caplog
    ):
        run = world.run()
        store = world.store([world.held(run)], template=None)

        with caplog.at_level(logging.WARNING):
            await _handle(world, store, _tap())

        assert [e.text for e in world.routed[0]] == ["Show me"]
        assert "whatsapp_template_unread" not in caplog.text

    async def test_an_unreadable_template_still_routes_the_batch(self, world, caplog):
        run = world.run()
        store = world.store([world.held(run)], template=RuntimeError("secret-bsuid"))

        with caplog.at_level(logging.WARNING):
            await _handle(world, store, _tap())

        assert [e.text for e in world.routed[0]] == ["Show me"]
        (record,) = [r for r in caplog.records if r.message == "whatsapp_template_unread"]
        assert (record.bot_id, record.error) == (BOT, "RuntimeError")
        assert "secret-bsuid" not in caplog.text

    async def test_a_show_me_tap_after_a_prompt_only_delivery_is_routed(self, world):
        run = world.run(status=PARKED)
        store = world.store([world.held(run, answer=False)])

        await _handle(world, store, _tap())

        assert world.sent == []
        assert world.order == ["route", "offer"]
        assert world.routed[0][0].text == "Show me"

    async def test_a_show_me_tap_with_nothing_delivered_is_routed(self, world):
        await _handle(world, world.store([]), _tap())
        assert world.order == ["route"]

    async def test_a_failed_reoffer_does_not_send_the_answer_again(self, world, caplog):
        run = world.run(status=PARKED)
        row = world.held(run)
        store = world.store([row])
        world.unoffered.add(run.id)

        with caplog.at_level(logging.WARNING):
            await _handle(world, store)
        assert store.settled_ids("release") == [row.id]
        assert store.settled_ids("done") == []
        (record,) = [r for r in caplog.records if r.message == "whatsapp_offer_failed"]
        assert (record.bot_id, record.run_id, record.error) == (BOT, str(run.id), None)
        assert world.session_errors == []
        assert [(r.answer, r.files) for r in store.rows] == [(False, False)]

        world.unoffered.clear()
        await _handle(world, store)

        assert len(world.sent) == 1
        assert store.settled_ids("done") == [row.id]

    async def test_a_reoffer_that_failed_for_one_run_does_not_stop_the_next(self, world):
        first, second = world.run(status=PARKED), world.run(status=PARKED)
        rows = [world.held(first, answer=False), world.held(second, answer=False)]
        store = world.store(rows)
        world.unoffered.add(first.id)

        await _handle(world, store)

        assert world.offered == [first.id, second.id]
        assert store.settled_ids("release") == [rows[0].id]
        assert store.settled_ids("done") == [rows[1].id]

    async def test_a_reoffer_whose_commit_fails_gives_the_claim_back(self, world, caplog):
        first, second = world.run(status=PARKED), world.run(status=PARKED)
        rows = [world.held(first, answer=False), world.held(second, answer=False)]
        store = world.store(rows)

        @asynccontextmanager
        async def failing_commit() -> AsyncGenerator[MagicMock]:
            yield MagicMock()
            if world.offered:
                raise RuntimeError("commit failed")

        with (
            patch(f"{MODULE}.get_db_context", failing_commit),
            caplog.at_level(logging.WARNING),
        ):
            await _handle(world, store)

        assert world.offered == [first.id, second.id]
        assert store.settled_ids("release") == [rows[0].id, rows[1].id]
        assert store.settled_ids("done") == []
        records = [r for r in caplog.records if r.message == "whatsapp_offer_failed"]
        assert [(r.bot_id, r.run_id, r.error) for r in records] == [
            (BOT, str(first.id), "RuntimeError"),
            (BOT, str(second.id), "RuntimeError"),
        ]

    async def test_a_failing_settlement_releases_every_owing_row(self, world, caplog):
        first, second = world.run(status=PARKED), world.run(status=PARKED)
        rows = [world.held(first, answer=False), world.held(second, answer=False)]
        store = world.store(rows)

        async def broken_done(held: Held) -> None:
            raise RuntimeError("db down")

        store.done = broken_done  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING):
            await _handle(world, store)

        assert store.settled_ids("release") == [rows[0].id, rows[1].id]
        (record,) = [r for r in caplog.records if r.message == "whatsapp_offer_failed"]
        assert (record.bot_id, record.error) == (BOT, "RuntimeError")
        assert not hasattr(record, "run_id")

    async def test_a_question_is_not_offered_again_when_the_bot_is_gone(self, world):
        run = world.run(status=PARKED)
        store = world.store([world.held(run, answer=False)])

        bot = world.bot.return_value
        world.bot.side_effect = [bot, None]
        await _handle(world, store)

        assert world.offered == []
        assert store.rows == []

    async def test_a_prompt_only_row_for_a_run_that_moved_on_is_dropped(self, world):
        run = world.run(status="completed")
        row = world.held(run, answer=False)
        store = world.store([row])

        await _handle(world, store)

        assert store.settled == [("done", row.id)]
        assert world.offered == [] and world.sent == []

    async def test_an_answer_for_a_run_that_is_gone_is_dropped(self, world):
        row = Held(id=uuid.uuid4(), run_id=uuid.uuid4(), answer=True, files=False)
        store = world.store([row])

        await _handle(world, store)

        assert world.sent == []
        assert store.settled == [("done", row.id)]

    async def test_an_unexpected_failure_after_the_claim_gives_the_rows_back(self, world):
        run = world.run()
        row = world.held(run)
        store = world.store([row])
        world.admission.side_effect = RuntimeError("db down")

        await _handle(world, store)

        assert store.settled == [("release", row.id)]
        assert world.order == ["route"]

    async def test_a_second_batch_during_the_first_turn_is_routed_before_the_question_is_offered(
        self, world
    ):
        """The first turn's claim is not something the second batch waits behind."""
        run = world.run(status=PARKED)
        store = world.store([world.held(run)])
        entered, finish = anyio.Event(), anyio.Event()

        async def route(events: list[Any]) -> None:
            # What `route` does: the whole turn runs under the chat's lock.
            async with chat_lock(BOT, CHAT):
                world.order.append(f"route:{events[0].text}")
                if events[0].text == "first":
                    entered.set()
                    await finish.wait()

        with patch(f"{MODULE}.process_channel_events_in_order", route):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(_handle, world, store, _text("first"))
                await entered.wait()
                tasks.start_soon(_handle, world, store, _text("second"))
                await anyio.sleep(0.1)
                finish.set()

        assert world.order == ["answer", "route:first", "route:second", "offer"]

    async def test_a_second_batch_during_the_first_batchs_held_send_waits_its_turn(self, world):
        """A claim that still owes an answer is a delivery under way: the first batch is routed first."""
        run = world.run()
        store = world.store([world.held(run)])
        sending, finish = anyio.Event(), anyio.Event()
        send = world.adapter.send_message.side_effect

        async def slow(token: str, message: OutgoingMessage) -> None:
            sending.set()
            await finish.wait()
            await send(token, message)

        async def route(events: list[Any]) -> None:
            async with chat_lock(BOT, CHAT):
                world.order.append(f"route:{events[0].text}")

        world.adapter.send_message.side_effect = slow
        with patch(f"{MODULE}.process_channel_events_in_order", route):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(_handle, world, store, _text("first"))
                await sending.wait()
                tasks.start_soon(_handle, world, store, _text("second"))
                await anyio.sleep(0.1)
                finish.set()

        assert world.order == ["answer", "route:first", "route:second"]

    async def test_a_tap_dropped_after_a_held_answer_still_claims_its_delivery(self, world):
        run = world.run()
        store = world.store([world.held(run)], template=_template("Show me"))
        [tap] = _tap()

        with patch(f"{MODULE}.claim_delivery", AsyncMock(return_value=True)) as claim:
            await _handle(world, store, [tap])

        claim.assert_awaited_once()
        assert claim.await_args.args[0].message_id == tap.wamid
        assert world.routed == []

    async def test_rows_settled_before_a_failure_are_still_offered_and_taps_still_dropped(
        self, world
    ):
        first, second = world.run(status=PARKED), world.run()
        store = world.store([world.held(first), world.held(second)], template=_template("Show me"))
        settled = store.answer_sent

        async def fail_second(held: Held, *, prompts_owed: bool) -> bool:
            if held.run_id == second.id:
                raise RuntimeError("db down")
            return await settled(held, prompts_owed=prompts_owed)

        store.answer_sent = fail_second  # type: ignore[method-assign]

        await _handle(world, store, _tap())

        assert world.offered == [first.id]
        assert world.routed == []

    async def test_an_answer_row_taken_over_at_its_settlement_is_not_offered_again(self, world):
        run = world.run(status=PARKED)
        row = world.held(run)
        store = world.store([row], template=_template("Show me"))
        store.superseded.add(row.id)

        await _handle(world, store, _tap())

        assert [m.text for m in world.sent] == ["the answer"]
        assert world.offered == []
        assert world.routed == []
        assert store.settled == [("answer_sent", row.id)]

    async def test_a_notice_is_not_sent_for_a_row_taken_over_at_its_answer(self, world):
        first, second = world.run(status=PARKED), world.run(answer="second answer")
        row = world.held(first, notice="stranded")
        store = world.store([row, world.held(second)], template=_template("Show me"))
        store.superseded.add(row.id)

        await _handle(world, store, _tap())

        assert [m.text for m in world.sent] == ["the answer", "second answer"]
        assert world.offered == []
        assert world.routed == []
        assert ("release", row.id) not in store.settled
        assert [r.id for r in store.rows] == [row.id]

    async def test_a_notice_row_taken_over_at_its_settlement_is_not_offered_again(self, world):
        run = world.run(status=PARKED)
        row = world.held(run, answer=False, notice="stranded")
        store = world.store([row], template=_template("Show me"))
        store.superseded.add(row.id)

        await _handle(world, store, _tap())

        assert [m.text for m in world.sent] == [STRANDED_NOTICE]
        assert world.offered == []
        assert [e.text for e in world.routed[0]] == ["Show me"]
        assert store.settled == [("notice_sent", row.id)]

    async def test_a_delivery_reports_a_taken_over_answer_without_its_prompts(self, world):
        run = world.run(status=PARKED)
        row = world.held(run)
        store = world.store([row])
        store.superseded.add(row.id)

        delivered = await _deliver_answers(BOT, ORG, CHAT, store)

        assert [(h.id, h.prompts_owed) for h in delivered] == [(row.id, False)]

    async def test_a_delivery_reports_nothing_for_a_taken_over_notice_row(self, world):
        run = world.run(status=PARKED)
        row = world.held(run, answer=False, notice="stranded")
        store = world.store([row])
        store.superseded.add(row.id)

        assert await _deliver_answers(BOT, ORG, CHAT, store) == []

    async def test_a_notice_row_taken_over_after_its_answer_is_not_offered_again(self, world):
        run = world.run(status=PARKED)
        row = world.held(run, notice="stranded")
        store = world.store([row], template=_template("Show me"))
        store.supersede_after_answer.add(row.id)

        delivered = await _deliver_answers(BOT, ORG, CHAT, store)
        assert [(h.id, h.prompts_owed) for h in delivered] == [(row.id, False)]
        assert [m.text for m in world.sent] == ["the answer", STRANDED_NOTICE]

        store = world.store([row], template=_template("Show me"))
        store.supersede_after_answer.add(row.id)
        await _handle(world, store, _tap())
        assert world.offered == []
        assert world.routed == []

    async def test_a_row_held_again_during_the_send_is_not_offered_in_this_delivery(self, world):
        run = world.run(status=PARKED)
        row = world.held(run)
        store = world.store([row], template=_template("Show me"))
        store.reheld.add(row.id)

        await _handle(world, store, _tap())

        assert [m.text for m in world.sent] == ["the answer"]
        assert world.offered == []
        assert world.routed == []
        assert store.settled == [("answer_sent", row.id)]

    async def test_a_row_taken_over_during_the_routed_turn_is_not_offered(self, world):
        run = world.run(status=PARKED)
        row = replace(world.held(run), prompts_owed=True)
        store = world.store([row])
        store.superseded.add(row.id)

        await _offer_again(BOT, ORG, CHAT, [row], store)

        assert world.offered == []
        assert store.settled == []

    async def test_the_default_store_is_the_real_one(self, world):
        with patch(f"{MODULE}.WindowStore") as created:
            created.return_value = world.store([])
            await handle_customer(BOT, ORG, CHAT, _text())
        created.assert_called_once_with()


class TestAHeldAgentRun:
    @pytest.mark.security
    async def test_a_held_agent_run_is_re_offered_nothing(self):
        """The customer is not asked to decide: no button row, no prompt message."""
        from app.schemas.agent import ParkedCall
        from app.services.agent_runner import AgentRunnerService

        run = MagicMock(
            id=uuid.uuid4(),
            user_id=None,
            status="awaiting_approval",
            runs_as_agent=True,
        )
        row = MagicMock(run_id=run.id)
        store = MagicMock(holds=AsyncMock(return_value=True), done=AsyncMock(), release=AsyncMock())
        bot = MagicMock(id=uuid.UUID(BOT), organization_id=ORG, is_active=True)
        adapter = MagicMock(send_prompt=AsyncMock(), send_message=AsyncMock())
        create = AsyncMock()
        prompts = "app.services.channels.prompts"
        call = ParkedCall(
            id=uuid.uuid4(), tool_call_id="c1", tool_name="upsert_record", tool_args={}
        )

        @asynccontextmanager
        async def sessions() -> AsyncGenerator[MagicMock]:
            yield MagicMock()

        with (
            patch(f"{MODULE}.get_db_context", sessions),
            patch(f"{MODULE}.channel_bot_repo.get_for_org", AsyncMock(return_value=bot)),
            patch(f"{MODULE}.agent_run_repo.get_run", AsyncMock(return_value=run)),
            patch(f"{prompts}.agent_run_repo.get_run", AsyncMock(return_value=run)),
            patch(f"{prompts}.channel_prompt_repo.for_run", AsyncMock(return_value=[])),
            patch(f"{prompts}.channel_prompt_repo.create", create),
            patch(f"{prompts}.get_adapter", return_value=adapter),
            patch(f"{prompts}.unseal_bot_token", return_value="tok"),
            patch.object(AgentRunnerService, "parked_calls", AsyncMock(return_value=[call])),
            patch.object(AgentRunnerService, "parked_questions", AsyncMock(return_value=[])),
        ):
            await _offer_again(BOT, ORG, CHAT, [row], store)

        create.assert_not_awaited()
        adapter.send_prompt.assert_not_awaited()
        store.done.assert_awaited_once_with(row)
        store.release.assert_not_awaited()


RUN = uuid.UUID("5b1f3c6e-2f0a-4c55-9a43-0d1f6f0c1a11")
CLOSED_AT = datetime.fromtimestamp(1790000000, UTC)


def _failed(*codes: int, callback: str | None = str(RUN), at: int = 1790000000) -> dict[str, Any]:
    status: dict[str, Any] = {
        "id": f"wamid.F{at}",
        "status": "failed",
        "timestamp": str(at),
        "recipient_user_id": CHAT,
        "errors": [{"code": code} for code in codes],
    }
    if callback is not None:
        status["biz_opaque_callback_data"] = callback
    return status


def _statuses(*statuses: dict[str, Any]) -> ParsedWebhook:
    payload = _fixture("statuses")
    payload["entry"][0]["changes"][0]["value"]["statuses"] = list(statuses)
    return _parse(payload)


async def _queued(
    parsed: ParsedWebhook, caplog: pytest.LogCaptureFixture
) -> tuple[MagicMock, MagicMock]:
    bot = _bot()
    with (
        patch(f"{MODULE}.whatsapp_customer_repo.record_inbound", AsyncMock()),
        patch(f"{MODULE}.spawn_after_commit") as spawn,
        patch(f"{MODULE}.reclaim_after_refusal", AsyncMock()) as reclaim,
        caplog.at_level(logging.WARNING),
    ):
        await WhatsAppInbound(MagicMock()).receive(bot, parsed)
        for call in spawn.call_args_list:
            await call.args[1]
    return bot, MagicMock(spawn=spawn, reclaim=reclaim)


async def test_a_closed_window_status_is_queued_once_per_run(caplog):
    later = 1790000500
    bot, queued = await _queued(
        _statuses(_failed(131047), _failed(131047, at=later), _failed(131047, callback="nope")),
        caplog,
    )

    queued.reclaim.assert_awaited_once_with(
        str(bot.id), ORG, CHAT, RUN, datetime.fromtimestamp(later, UTC)
    )
    assert [c.kwargs["name"] for c in queued.spawn.call_args_list] == [
        f"whatsapp_window_closed:{bot.id}"
    ]


async def test_a_closed_window_status_with_no_callback_is_only_logged(caplog):
    _, queued = await _queued(_statuses(_failed(131047, callback=None)), caplog)

    queued.spawn.assert_not_called()
    [record] = [r for r in caplog.records if r.message == "whatsapp_closed_window_unattributed"]
    assert record.levelno == logging.WARNING
    assert set(vars(record)) & {"phone", "recipient", "wamid", "callback"} == set()


async def test_a_closed_window_status_with_no_recipient_is_only_logged(caplog):
    status = _failed(131047)
    del status["recipient_user_id"]
    _, queued = await _queued(_statuses(status), caplog)

    queued.spawn.assert_not_called()
    assert any(r.message == "whatsapp_closed_window_unattributed" for r in caplog.records)


async def test_another_failure_code_queues_nothing_and_holds_nothing(caplog):
    _, queued = await _queued(_statuses(_failed(131000, 131026)), caplog)

    queued.spawn.assert_not_called()
    [record] = [r for r in caplog.records if r.message == "whatsapp_send_failed"]
    assert (record.run_id, record.codes) == (str(RUN), [131000, 131026])


async def test_a_status_never_falls_back_to_the_latest_run(caplog):
    with patch(f"{MODULE}.agent_run_repo") as runs:
        _, queued = await _queued(_statuses(_failed(131047, callback=None)), caplog)

    queued.spawn.assert_not_called()
    assert runs.method_calls == []


async def test_a_status_with_no_time_is_queued_without_one(caplog):
    status = _failed(131047)
    del status["timestamp"]
    bot, queued = await _queued(_statuses(status), caplog)

    queued.reclaim.assert_awaited_once_with(str(bot.id), ORG, CHAT, RUN, None)


async def test_another_failure_without_a_run_is_not_logged_against_one(caplog):
    _, queued = await _queued(_statuses(_failed(131000, callback="nope")), caplog)

    queued.spawn.assert_not_called()
    assert not [r for r in caplog.records if r.message == "whatsapp_send_failed"]


async def test_the_fixtures_failed_status_queues_one_reclaim(caplog):
    _, queued = await _queued(_parse(_fixture("statuses")), caplog)
    assert queued.reclaim.await_count == 1  # only the fixture's failed 131047 naming a run


class TestReclaim:
    @pytest.fixture
    def claim(self, world: World) -> Iterator[World]:
        world.chat_session = MagicMock(conversation_id=None)
        world.runs[RUN] = run = MagicMock(
            id=RUN,
            status="completed",
            surface="whatsapp",
            conversation_id=uuid.uuid4(),
            runs_as_agent=False,
        )
        world.answers[RUN] = "the saved answer"
        world.chat_session.conversation_id = run.conversation_id
        world.lookups = AsyncMock(return_value=world.chat_session)
        with patch(f"{MODULE}.channel_session_repo.get_by_bot_and_chat", world.lookups):
            yield world

    async def _reclaim(self, store: StubStore) -> None:
        await inbound.reclaim_after_refusal(BOT, ORG, CHAT, RUN, CLOSED_AT, store=store)

    async def test_a_failed_late_answer_is_held_and_previewed(self, claim):
        store = claim.store([], window=False)

        await self._reclaim(store)

        assert store.closures == [CLOSED_AT]
        assert store.held_new == [RUN]
        [(token, message)] = [c.args for c in claim.adapter.send_held_preview.await_args_list]
        assert (token, message.text, message.run_id, message.platform_chat_id) == (
            "tok",
            "the saved answer",
            str(RUN),
            CHAT,
        )
        claim.adapter.send_message.assert_not_awaited()

    async def test_a_preview_with_no_saved_answer_says_done(self, claim):
        claim.answers[RUN] = None
        await self._reclaim(claim.store([], window=False))
        assert claim.adapter.send_held_preview.await_args.args[1].text == "Done."

    async def test_a_failed_answer_after_the_customer_wrote_again_goes_as_text(self, claim):
        store = claim.store([], window=True)

        await self._reclaim(store)

        assert [m.text for m in claim.sent] == ["the saved answer"]
        assert claim.sent[0].run_id == str(RUN)
        assert len(store.settled_ids("answer_sent")) == 1
        claim.adapter.send_held_preview.assert_not_awaited()

    async def test_a_failed_answer_that_reopened_also_offers_the_prompts_again(self, claim):
        claim.runs[RUN].status = PARKED
        store = claim.store([], window=True)

        await self._reclaim(store)

        assert claim.order == ["answer", "offer"]
        assert claim.offered == [RUN]

    async def test_a_status_with_no_time_holds_and_acts_but_never_closes_the_window(self, claim):
        store = claim.store([], window=False)

        await inbound.reclaim_after_refusal(BOT, ORG, CHAT, RUN, None, store=store)

        assert store.closures == []
        assert store.held_new == [RUN]
        claim.adapter.send_held_preview.assert_awaited_once()

    async def test_a_message_sent_before_the_reclaims_offer_is_never_claimable_either_way(
        self, claim
    ):
        """The reclaim and a batch race for the chat. Whichever goes first, the batch's message was
        sent before the question exists, and that is what keeps it out of the answer."""
        claim.runs[RUN].status = PARKED
        offered_at: list[datetime] = []

        async def offer(bot: Any, **kwargs: Any) -> bool:
            offered_at.append(datetime.now(UTC))
            return True

        claim.offer.side_effect = offer
        claimable: list[Any] = []

        async def route(events: list[Any]) -> None:
            async with chat_lock(BOT, CHAT):
                claimable.extend(e for e in events if any(at <= e.sent_at for at in offered_at))

        store = claim.store([], window=True)
        with patch(f"{MODULE}.process_channel_events_in_order", route):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(self._reclaim, store)
                tasks.start_soon(_handle, claim, store, _text("typed before the question"))

        assert offered_at and claimable == []

    async def test_a_preview_for_a_bot_that_is_gone_sends_nothing(self, claim):
        claim.bot.return_value = None

        await self._reclaim(claim.store([], window=False))

        claim.adapter.send_held_preview.assert_not_awaited()

    async def test_a_second_status_for_the_same_run_sends_nothing(self, claim):
        store = claim.store([], window=False)
        store.hold_is_new = False

        await self._reclaim(store)

        assert store.closures == [CLOSED_AT]
        claim.adapter.send_held_preview.assert_not_awaited()
        claim.adapter.send_message.assert_not_awaited()

    @pytest.mark.security
    async def test_a_callback_naming_another_organizations_run_is_ignored(self, claim, caplog):
        del claim.runs[RUN]
        store = claim.store([], window=False)

        with caplog.at_level(logging.WARNING):
            await self._reclaim(store)

        assert store.closures == [] and store.held_new == []
        claim.adapter.send_held_preview.assert_not_awaited()
        assert any(r.message == "whatsapp_callback_ignored" for r in caplog.records)

    async def test_a_callback_whose_run_is_not_this_chats_is_ignored(self, claim):
        claim.chat_session.conversation_id = uuid.uuid4()
        store = claim.store([], window=False)

        await self._reclaim(store)

        assert store.closures == [] and store.held_new == []

    async def test_a_chat_with_no_session_is_ignored(self, claim):
        claim.lookups.return_value = None
        store = claim.store([], window=False)

        await self._reclaim(store)

        assert store.held_new == []

    async def test_a_run_from_another_surface_is_ignored(self, claim):
        claim.runs[RUN].surface = "web"
        store = claim.store([], window=False)

        await self._reclaim(store)

        assert store.held_new == []

    async def test_the_reclaim_never_raises_and_logs_the_type(self, claim, caplog):
        store = claim.store([], window=False)
        store.close = AsyncMock(side_effect=RuntimeError("boom for US.111"))  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING):
            await self._reclaim(store)

        [record] = [r for r in caplog.records if r.message == "whatsapp_reclaim_failed"]
        assert (record.bot_id, record.run_id, record.error) == (BOT, str(RUN), "RuntimeError")
        assert "boom" not in caplog.text and record.exc_info is None

    async def test_the_default_store_is_the_real_one(self, claim):
        with patch(f"{MODULE}.WindowStore") as created:
            created.return_value = claim.store([], window=False)
            await inbound.reclaim_after_refusal(BOT, ORG, CHAT, RUN, CLOSED_AT)
        created.assert_called_once_with()


def _number(payload: dict[str, Any], number: str, user: str, wamid: str, text: str) -> None:
    """Add a change for `number` (account `WABA1`) from `user` to the payload."""
    change = json.loads(json.dumps(payload["entry"][0]["changes"][0]))
    value = change["value"]
    value["metadata"]["phone_number_id"] = number
    value["contacts"][0]["user_id"] = user
    value["messages"][0].update(
        {"id": wamid, "from_user_id": user, "timestamp": str(NOW - 5), "text": {"body": text}}
    )
    payload["entry"][0]["changes"].append(change)


def _signed(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestRoutingToTheNumbersOwner:
    """A change for another number goes to the bot that owns it, and only on that bot's own secret."""

    URL_SECRET = "secret-of-a"

    @pytest.fixture
    def world(self):
        url_bot = _bot()
        payload = _fixture("text")
        payload["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = str(NOW - 5)
        _number(payload, "PNID2", "US.222", "wamid.B1", "for b")
        body = json.dumps(payload).encode()

        class World:
            def __init__(self) -> None:
                self.url_bot = url_bot
                self.payload = payload
                self.body = body
                self.signature = _signed(body, TestRoutingToTheNumbersOwner.URL_SECRET)
                self.secrets: dict[uuid.UUID, str | Exception | None] = {}
                self.found: list[MagicMock] = []
                self.parsed: ParsedWebhook | None = None
                self.service = WhatsAppInbound(MagicMock())
                self.service.receive = AsyncMock()  # type: ignore[method-assign]

            def owner(self, secret: str | Exception | None, **fields: Any) -> MagicMock:
                bot = MagicMock(
                    id=uuid.uuid4(),
                    organization_id=fields.pop("organization_id", ORG),
                    whatsapp_phone_number_id=fields.pop("number", "PNID2"),
                    whatsapp_account_id="WABA1",
                )
                self.secrets[bot.id] = secret
                self.found.append(bot)
                return bot

            async def route(self) -> int:
                parsed = parse_webhook(
                    self.payload,
                    phone_number_id="PNID1",
                    account_id="WABA1",
                    now=datetime.fromtimestamp(NOW, UTC),
                )
                self.parsed = parsed

                def unseal(bot: MagicMock) -> str | None:
                    value = self.secrets[bot.id]
                    if isinstance(value, Exception):
                        raise value
                    return value

                with (
                    patch(
                        f"{MODULE}.channel_bot_repo.get_active_whatsapp_by_numbers",
                        AsyncMock(return_value=[*self.found, self.url_bot]),
                    ) as lookup,
                    patch(f"{MODULE}.unseal_webhook_secret", unseal),
                ):
                    self.secrets[self.url_bot.id] = TestRoutingToTheNumbersOwner.URL_SECRET
                    self.lookup = lookup
                    return await self.service.route_others(
                        self.url_bot,
                        self.body,
                        self.signature,
                        self.payload,
                        parsed,
                        now=datetime.fromtimestamp(NOW, UTC),
                    )

            def received(self) -> list[tuple[Any, list[str]]]:
                return [
                    (call.args[0], [m.wamid for m in call.args[1].messages])
                    for call in self.service.receive.await_args_list
                ]

        return World()

    @pytest.mark.security
    async def test_the_owner_receives_its_change_when_its_own_secret_verifies_the_body(self, world):
        owner = world.owner(self.URL_SECRET)

        routed = await world.route()

        assert routed == 1
        assert world.received() == [(owner, ["wamid.B1"])]
        world.lookup.assert_awaited_once()
        assert world.lookup.await_args.kwargs["pairs"] == (("WABA1", "PNID2"),)

    @pytest.mark.security
    async def test_a_bot_whose_own_secret_does_not_verify_the_body_gets_nothing(
        self, world, caplog
    ):
        """The URL bot's signature alone never admits another bot's change."""
        world.owner("another-secret")

        with caplog.at_level(logging.WARNING):
            routed = await world.route()

        assert routed == 0
        world.service.receive.assert_not_awaited()
        [record] = [r for r in caplog.records if r.message == "whatsapp_number_unrouted"]
        assert (record.bot_id, record.phone_number_id) == (str(world.url_bot.id), "PNID2")

    @pytest.mark.security
    async def test_a_bot_with_no_secret_is_never_admitted(self, world):
        world.owner(None)

        assert await world.route() == 0
        world.service.receive.assert_not_awaited()

    async def test_a_number_nobody_owns_is_logged_and_dropped(self, world, caplog):
        with caplog.at_level(logging.WARNING):
            assert await world.route() == 0

        world.service.receive.assert_not_awaited()
        assert [r.message for r in caplog.records].count("whatsapp_number_unrouted") == 1

    @pytest.mark.security
    async def test_two_bots_that_verify_the_body_get_nothing_and_it_is_logged(self, world, caplog):
        world.owner(self.URL_SECRET)
        world.owner(self.URL_SECRET)

        with caplog.at_level(logging.WARNING):
            routed = await world.route()

        assert routed == 0
        world.service.receive.assert_not_awaited()
        [record] = [r for r in caplog.records if r.message == "whatsapp_number_ambiguous"]
        assert (record.bot_id, record.phone_number_id, record.count) == (
            str(world.url_bot.id),
            "PNID2",
            2,
        )

    async def test_one_verifying_bot_is_enough_when_another_candidate_does_not_verify(self, world):
        wrong = world.owner("another-secret")
        right = world.owner(self.URL_SECRET)

        assert await world.route() == 1
        assert [bot for bot, _ in world.received()] == [right]
        assert wrong not in [bot for bot, _ in world.received()]

    @pytest.mark.security
    async def test_a_bot_of_another_organization_is_routed_when_its_secret_verifies(self, world):
        owner = world.owner(self.URL_SECRET, organization_id=uuid.uuid4())

        assert await world.route() == 1
        assert world.received() == [(owner, ["wamid.B1"])]

    @pytest.mark.security
    async def test_a_bot_whose_secret_cannot_be_read_is_unrouted_and_the_rest_goes_on(
        self, world, caplog
    ):
        world.owner(RuntimeError("sealed with a retired key"))
        world.payload["entry"][0]["changes"].append(
            json.loads(json.dumps(world.payload["entry"][0]["changes"][1]))
        )
        other = world.owner(self.URL_SECRET, number="PNID3")
        world.payload["entry"][0]["changes"][-1]["value"]["metadata"]["phone_number_id"] = "PNID3"
        world.payload["entry"][0]["changes"][-1]["value"]["messages"][0]["id"] = "wamid.C1"
        world.body = json.dumps(world.payload).encode()
        world.signature = _signed(world.body, self.URL_SECRET)

        with caplog.at_level(logging.WARNING):
            routed = await world.route()

        assert routed == 1
        assert world.received() == [(other, ["wamid.C1"])]
        [record] = [r for r in caplog.records if r.message == "whatsapp_owner_secret_unreadable"]
        assert record.error == "RuntimeError"
        assert len([r for r in caplog.records if r.message == "whatsapp_number_unrouted"]) == 1
        assert "retired" not in caplog.text

    async def test_a_status_only_change_reaches_the_owner(self, world):
        failed = _fixture("statuses")["entry"][0]["changes"][0]
        failed["value"]["metadata"]["phone_number_id"] = "PNID7"
        world.payload["entry"][0]["changes"] = [failed]
        world.body = json.dumps(world.payload).encode()
        world.signature = _signed(world.body, self.URL_SECRET)
        owner = world.owner(self.URL_SECRET, number="PNID7")

        assert await world.route() == 1

        ((receiver, parsed),) = [
            (call.args[0], call.args[1]) for call in world.service.receive.await_args_list
        ]
        assert receiver is owner
        assert [
            (s.status, s.error_codes, s.callback) for s in parsed.statuses if s.status == "failed"
        ] == [("failed", (131047,), "5b1f3c6e-2f0a-4c55-9a43-0d1f6f0c1a11")]

    async def test_a_batch_with_no_other_number_looks_nothing_up(self, world):
        world.payload["entry"][0]["changes"].pop()
        parsed = parse_webhook(
            world.payload,
            phone_number_id="PNID1",
            account_id="WABA1",
            now=datetime.fromtimestamp(NOW, UTC),
        )
        with patch(
            f"{MODULE}.channel_bot_repo.get_active_whatsapp_by_numbers", AsyncMock()
        ) as lookup:
            routed = await world.service.route_others(
                world.url_bot, world.body, world.signature, world.payload, parsed, now=_at(0)
            )

        assert routed == 0
        lookup.assert_not_awaited()

    @pytest.mark.security
    async def test_the_url_bot_is_never_routed_a_change_even_if_the_lookup_returns_it(self, world):
        """The URL bot's own secret verifies the body; that must not make it a candidate."""
        world.url_bot.whatsapp_account_id = "WABA1"
        world.url_bot.whatsapp_phone_number_id = "PNID2"

        assert await world.route() == 0
        world.service.receive.assert_not_awaited()

    async def test_a_routed_bots_failure_to_record_fails_the_batch(self, world):
        world.owner(self.URL_SECRET)
        world.service.receive.side_effect = RuntimeError("could not record")

        with pytest.raises(RuntimeError):
            await world.route()

    async def test_every_change_for_a_routed_number_is_counted_as_routed(self, world, caplog):
        """Changes [A, B, B] with B routed: nothing was dropped, so the URL bot logs nothing."""
        world.payload["entry"][0]["changes"].append(
            json.loads(json.dumps(world.payload["entry"][0]["changes"][1]))
        )
        world.body = json.dumps(world.payload).encode()
        world.signature = _signed(world.body, self.URL_SECRET)
        world.owner(self.URL_SECRET)

        routed = await world.route()

        assert routed == 2
        assert world.parsed is not None and world.parsed.foreign == 2
        with caplog.at_level(logging.INFO):
            inbound.log_parsed(world.url_bot, world.parsed, routed=routed)
        assert caplog.records == []

    @pytest.mark.security
    async def test_a_candidate_whose_secret_cannot_be_read_is_logged_when_another_is_routed(
        self, world, caplog
    ):
        broken = world.owner(RuntimeError("sealed with a retired key"))
        right = world.owner(self.URL_SECRET)

        with caplog.at_level(logging.WARNING):
            routed = await world.route()

        assert routed == 1
        assert [bot for bot, _ in world.received()] == [right]
        [record] = [r for r in caplog.records if r.message == "whatsapp_owner_secret_unreadable"]
        assert (record.bot_id, record.owner_id, record.phone_number_id, record.error) == (
            str(world.url_bot.id),
            str(broken.id),
            "PNID2",
            "RuntimeError",
        )
        assert "retired" not in caplog.text

    @pytest.mark.security
    async def test_no_customer_id_number_or_text_is_logged_for_a_routed_or_refused_change(
        self, world, caplog
    ):
        world.owner(self.URL_SECRET)
        world.owner("another-secret", number="PNID3")
        world.payload["entry"][0]["changes"].append(
            json.loads(json.dumps(world.payload["entry"][0]["changes"][1]))
        )
        world.payload["entry"][0]["changes"][-1]["value"]["metadata"]["phone_number_id"] = "PNID3"
        world.body = json.dumps(world.payload).encode()
        world.signature = _signed(world.body, self.URL_SECRET)

        with caplog.at_level(logging.DEBUG):
            await world.route()

        for record in caplog.records:
            extra = " ".join(f"{k}={v}" for k, v in record.__dict__.items())
            for leaked in ("US.111", "US.222", "wamid.", "for b", "4915112345678", "secret"):
                assert leaked not in extra


class TestLoggingAParsedBatch:
    def _parsed(self, **counts: int) -> ParsedWebhook:
        return ParsedWebhook(
            messages=(),
            statuses=(),
            foreign=counts.get("foreign", 0),
            stale=counts.get("stale", 0),
            unidentified=counts.get("unidentified", 0),
            ignored=counts.get("ignored", 0),
            others=(),
        )

    def test_the_changes_that_were_routed_are_not_counted_foreign(self, caplog):
        bot = _bot()
        with caplog.at_level(logging.INFO):
            inbound.log_parsed(bot, self._parsed(foreign=3), routed=2)

        [record] = [r for r in caplog.records if r.message == "whatsapp_webhook_dropped"]
        assert (record.levelname, record.foreign) == ("WARNING", 1)

    def test_an_owners_record_counts_no_foreign_changes(self, caplog):
        with caplog.at_level(logging.INFO):
            inbound.log_parsed(_bot(), self._parsed(foreign=2, unidentified=1), owner=True)

        [record] = caplog.records
        assert (record.foreign, record.unidentified) == (0, 1)

    def test_a_batch_whose_foreign_changes_were_all_routed_logs_no_warning(self, caplog):
        with caplog.at_level(logging.INFO):
            inbound.log_parsed(_bot(), self._parsed(foreign=2), routed=2)

        assert caplog.records == []

    def test_stale_and_ignored_are_counted_at_info(self, caplog):
        with caplog.at_level(logging.INFO):
            inbound.log_parsed(_bot(), self._parsed(stale=1, ignored=2))

        [record] = caplog.records
        assert (record.levelname, record.stale, record.ignored) == ("INFO", 1, 2)


class TestTheNudgeButton:
    async def test_a_tap_is_thanked_once_and_not_routed(self, world):
        with patch(f"{MODULE}.claim_delivery", AsyncMock(return_value=True)) as claim:
            await _handle(world, world.store([]), _nudge_tap())

        claim.assert_awaited_once()
        assert claim.await_args.args[0].message_id == "wamid.TAP1"
        [thanks] = world.sent
        assert (thanks.text, thanks.platform_chat_id, thanks.run_id) == (NUDGE_THANKS, CHAT, None)
        assert world.routed == []

    async def test_a_redelivered_tap_is_not_thanked_again(self, world):
        with patch(f"{MODULE}.claim_delivery", AsyncMock(return_value=False)):
            await _handle(world, world.store([]), _nudge_tap())

        assert world.sent == []
        assert world.routed == []

    async def test_a_failed_thank_you_still_routes_the_rest_of_the_batch(self, world, caplog):
        world.adapter.send_message.side_effect = RuntimeError("to US.111")

        with (
            patch(f"{MODULE}.claim_delivery", AsyncMock(return_value=True)),
            caplog.at_level(logging.WARNING),
        ):
            await _handle(world, world.store([]), [*_nudge_tap(), *_text()])

        assert [e.text for e in world.routed[0]] == ["any news?"]
        [record] = [r for r in caplog.records if r.message == "whatsapp_nudge_thanks_failed"]
        assert (record.bot_id, record.error) == (BOT, "RuntimeError")
        assert "US.111" not in caplog.text

    async def test_another_button_reply_still_takes_the_press_path(self, world):
        with patch(f"{MODULE}.claim_delivery", AsyncMock(return_value=True)):
            await _handle(
                world, world.store([]), _nudge_tap("aos:0123456789abcdef0123456789abcdef:0")
            )

        assert world.sent == []
        [event] = world.routed[0]
        assert isinstance(event, IncomingPress)

    async def test_a_tap_for_a_bot_that_is_gone_is_not_thanked(self, world):
        world.bot.return_value = None

        with patch(f"{MODULE}.claim_delivery", AsyncMock(return_value=True)):
            await _handle(world, world.store([]), _nudge_tap())

        assert world.sent == []
        assert world.routed == []

    async def test_a_tap_that_just_released_a_held_answer_is_not_thanked(self, world):
        run = world.run()
        store = world.store([world.held(run)])

        with patch(f"{MODULE}.claim_delivery", AsyncMock(return_value=True)) as claim:
            await _handle(world, store, _nudge_tap())

        assert [m.text for m in world.sent] == ["the answer"]
        assert world.routed == []
        claim.assert_awaited_once()


class _Line:
    """One message through the real router, with everything outside the decision doubled.

    What a test asks is who the turn is for: `answer_default` and `answer` record the
    arguments the router handed them, `invited` is the link invitation, and `turns`
    is what `_run_turn` was given.
    """

    def __init__(self, policy: dict[str, Any], *, platform: str = "whatsapp") -> None:
        self.bot = MagicMock(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            platform=platform,
            is_active=True,
            stream_answers=False,
            access_policy=policy,
        )
        self.identity = MagicMock(id=uuid.uuid4(), user_id=None)
        self.member: MagicMock | None = None
        self.answered = MagicMock(
            text="answered",
            refused=[],
            delivery_notices=[],
            acts_as_agent=False,
            parked_run_id=None,
            next_steps=None,
            run_id=None,
        )
        self.answer_default = AsyncMock(return_value=self.answered)
        # Nothing is addressed to an agent by name unless a test says so.
        self.answer = AsyncMock(side_effect=UnaddressedMessage())
        self.invited = AsyncMock(return_value="link first")
        self.replies = AsyncMock()
        self.limit = AsyncMock()
        self.delivered = AsyncMock()
        self.failures = AsyncMock()
        self.files = AsyncMock(return_value=([], []))
        self.voice = AsyncMock(return_value=([], []))
        self.turns: list[dict[str, Any]] = []
        self.mentions: list[dict[str, Any]] = []

    def message(self, text: str = "any news?", *, chat_type: str = "private") -> IncomingMessage:
        return IncomingMessage(
            platform=self.bot.platform,
            bot_id=str(self.bot.id),
            platform_user_id=platform_user_id_for(self.bot.organization_id, "BSUID-1"),
            platform_chat_id="chat-1",
            chat_type=chat_type,
            text=text,
            addressed=True,
            raw={"guild_id": "123"},
        )

    async def route(self, text: str = "any news?", *, chat_type: str = "private") -> None:

        router = ChannelMessageRouter()
        real_turn, real_mention = router._run_turn, router._answer_mention

        async def run_turn(_self: Any, *args: Any, **kwargs: Any) -> bool:
            self.turns.append(kwargs)
            return await real_turn(*args, **kwargs)

        async def answer_mention(_self: Any, *args: Any, **kwargs: Any) -> bool:
            self.mentions.append(kwargs)
            return await real_mention(*args, **kwargs)

        prefix = "app.services.channels.router"
        agent_router = MagicMock(
            return_value=MagicMock(answer=self.answer, answer_default=self.answer_default)
        )
        prompts = MagicMock(return_value=MagicMock(reply=AsyncMock(return_value=False)))
        patches = [
            patch(f"{prefix}.channel_bot_repo.get_for_inbound", AsyncMock(return_value=self.bot)),
            patch(
                f"{prefix}.channel_identity_repo.get_or_create",
                AsyncMock(return_value=self.identity),
            ),
            patch(f"{prefix}.member_repo.get_active", AsyncMock(return_value=self.member)),
            patch(
                f"{prefix}.ChannelLinkService.complete_with_code", AsyncMock(return_value="none")
            ),
            patch(f"{prefix}.ChannelAgentRouter", agent_router),
            patch(f"{prefix}.ChannelPrompts", prompts),
            patch(
                f"{prefix}.get_adapter",
                MagicMock(
                    return_value=MagicMock(
                        begin_reply=AsyncMock(return_value=None),
                        open_answer=AsyncMock(return_value=None),
                        resolve_addressing=AsyncMock(return_value=True),
                    )
                ),
            ),
            patch(f"{prefix}.unseal_bot_token", MagicMock(return_value="token")),
            patch.object(ChannelMessageRouter, "_link_vouched", AsyncMock()),
            patch.object(ChannelMessageRouter, "_invite_to_link", self.invited),
            patch.object(ChannelMessageRouter, "_send_reply", self.replies),
            patch.object(ChannelMessageRouter, "_check_rate_limit", self.limit),
            patch.object(
                ChannelMessageRouter,
                "_resolve_session",
                AsyncMock(return_value=MagicMock(conversation_id=uuid.uuid4(), turn_count=1)),
            ),
            patch.object(ChannelMessageRouter, "_channel_directory", MagicMock(return_value=None)),
            patch.object(
                ChannelMessageRouter, "_thread_context", AsyncMock(return_value=([], [], []))
            ),
            patch.object(ChannelMessageRouter, "_load_history", AsyncMock(return_value=[])),
            patch.object(ChannelMessageRouter, "_start_workflow", AsyncMock(return_value=False)),
            patch.object(ChannelMessageRouter, "_acknowledge", AsyncMock()),
            patch.object(ChannelMessageRouter, "_open_reply", AsyncMock(return_value=(None, None))),
            patch.object(ChannelMessageRouter, "_deliver", self.delivered),
            patch.object(ChannelMessageRouter, "_post_failure", self.failures),
            patch.object(ChannelMessageRouter, "_receive_files", self.files),
            patch.object(ChannelMessageRouter, "_transcribe", self.voice),
            patch.object(ChannelMessageRouter, "_run_turn", run_turn),
            patch.object(ChannelMessageRouter, "_answer_mention", answer_mention),
        ]
        with contextlib.ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            await router._route_inner(self.message(text, chat_type=chat_type), MagicMock())


def _public(**policy: Any) -> dict[str, Any]:
    return {"mode": "open", "answer_unlinked_direct": True, **policy}


class TestACustomerWhoNeverLinked:
    """What the router does with a direct message from a number nobody linked.

    Off, it asks for a link and runs nothing. On, the agent answers as itself.
    """

    @pytest.mark.security
    async def test_a_public_line_answers_as_the_agent(self):
        line = _Line(_public())

        await line.route()

        line.answer_default.assert_awaited_once()
        sent = line.answer_default.await_args.kwargs
        assert sent["as_agent"] is True
        assert sent["admit_unlinked"] is True
        assert sent["user_id"] is None
        assert sent["channel_identity_id"] == line.identity.id
        assert [turn["as_agent"] for turn in line.turns] == [True, True]
        assert line.mentions[0]["as_agent"] is True
        line.invited.assert_not_awaited()
        assert line.delivered.await_args.args[2] == "answered"

    @pytest.mark.security
    async def test_a_line_that_is_not_public_asks_for_a_link_and_runs_nothing(self):
        line = _Line({"mode": "open"})

        await line.route()

        line.invited.assert_awaited_once()
        line.answer_default.assert_not_awaited()
        line.answer.assert_not_awaited()
        assert line.turns == []

    @pytest.mark.security
    async def test_a_switch_that_is_off_asks_for_a_link_and_runs_nothing(self):
        line = _Line({"mode": "open", "answer_unlinked_direct": False})

        await line.route()

        line.invited.assert_awaited_once()
        line.answer_default.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize(
        "policy",
        [
            {"mode": "jwt_linked", "answer_unlinked_direct": True},
            {"mode": "open", "require_link": True, "answer_unlinked_direct": True},
        ],
        ids=["jwt_linked", "require_link"],
    )
    async def test_a_link_the_policy_asks_for_wins_over_the_switch(self, policy):
        line = _Line(policy)

        await line.route()

        line.invited.assert_awaited_once()
        line.answer_default.assert_not_awaited()
        assert line.turns == []

    @pytest.mark.security
    async def test_a_linked_member_on_a_public_line_is_not_answered_as_the_agent(self):
        line = _Line(_public())
        line.identity.user_id = uuid.uuid4()
        line.member = MagicMock(role="member")

        await line.route()

        sent = line.answer_default.await_args.kwargs
        # The principal is settled where the membership is read, and a member is
        # always themselves there; the wording of a refusal follows the member.
        assert sent["user_id"] == line.identity.user_id
        assert sent["as_agent"] is True
        # The mention path is handed the same unfiltered decision.
        assert line.answer.await_args.kwargs["as_agent"] is True
        assert [turn["as_agent"] for turn in line.turns] == [False, False]

    @pytest.mark.security
    async def test_a_departed_member_is_answered_as_the_agent(self):
        line = _Line(_public())
        line.identity.user_id = uuid.uuid4()
        line.member = None

        await line.route()

        assert line.answer_default.await_args.kwargs["as_agent"] is True
        assert [turn["as_agent"] for turn in line.turns] == [True, True]

    @pytest.mark.security
    async def test_a_mention_is_answered_as_the_agent_on_a_public_line(self):
        line = _Line(_public())
        line.answer.side_effect = None
        line.answer.return_value = line.answered

        await line.route("@support what is the refund window")

        line.answer.assert_awaited_once()
        assert line.answer.await_args.kwargs["as_agent"] is True
        assert [turn["as_agent"] for turn in line.turns] == [True]
        line.invited.assert_not_awaited()

    @pytest.mark.security
    async def test_an_ordinary_message_mints_no_link_request(self):
        """The invitation is what mints a bearer link; a customer who just wrote is
        not asked for one."""
        line = _Line(_public())

        await line.route("any news?")

        line.invited.assert_not_awaited()

    @pytest.mark.security
    async def test_typing_link_still_mints_a_request(self):
        line = _Line(_public())

        await line.route("link")

        line.invited.assert_awaited_once()
        line.answer_default.assert_not_awaited()

    @pytest.mark.security
    async def test_a_refusal_on_the_ordinary_path_is_one_neutral_sentence(self):
        """What raised is not the customer's to read: an archived agent or a missing
        model reads the same."""
        line = _Line(_public())
        line.answer_default.side_effect = NotFoundError(message="Agent 'Front desk' is archived")

        await line.route()

        assert line.failures.await_args.args[3] == STRANGER_REFUSAL
        assert "archived" not in line.failures.await_args.args[3]

    @pytest.mark.security
    async def test_a_member_on_a_public_line_still_reads_what_refused(self):
        line = _Line(_public())
        line.identity.user_id = uuid.uuid4()
        line.member = MagicMock(role="member")
        line.answer_default.side_effect = NotFoundError(message="Agent 'Front desk' is archived")

        await line.route()

        assert line.failures.await_args.args[3] == "Agent 'Front desk' is archived"

    @pytest.mark.security
    async def test_files_and_voice_are_handed_the_decision_already_made(self):
        """Not recomputed where they are read: a member's files are not a stranger's."""
        stranger, member = _Line(_public()), _Line(_public())
        member.identity.user_id = uuid.uuid4()
        member.member = MagicMock(role="member")

        await stranger.route()
        await member.route()

        assert stranger.files.await_args.kwargs["as_agent"] is True
        assert stranger.voice.await_args.kwargs["as_agent"] is True
        assert member.files.await_args.kwargs["as_agent"] is False
        assert member.voice.await_args.kwargs["as_agent"] is False

    @pytest.mark.security
    async def test_the_rate_limit_still_applies_per_chat_account(self):

        line = _Line(_public())
        line.limit.side_effect = BadRequestError(message="Rate limit exceeded. Please slow down.")

        await line.route()

        line.limit.assert_awaited_once_with(line.bot, str(line.identity.id))
        line.answer_default.assert_not_awaited()
        assert "Rate limit" in line.replies.await_args.args[2]

    @pytest.mark.security
    async def test_another_organizations_bot_with_the_same_customer_is_untouched(self):
        """The customer id is namespaced by organization, and the switch is read off the
        bot that received the message: the second organization's line is closed."""
        open_line, closed_line = _Line(_public()), _Line({"mode": "open"})
        closed_line.identity = MagicMock(id=uuid.uuid4(), user_id=None)

        await open_line.route()
        await closed_line.route()

        assert open_line.message().platform_user_id != closed_line.message().platform_user_id
        assert open_line.message().platform_user_id.startswith(str(open_line.bot.organization_id))
        open_line.answer_default.assert_awaited_once()
        closed_line.answer_default.assert_not_awaited()
        closed_line.invited.assert_awaited_once()


@pytest.mark.security
class TestAnUnlinkedGroupSenderIsNotAStranger:
    """A room admits its unlinked senders under the binding on every platform, as it
    did before the switch existed, and the switch changes neither that nor a private
    chat on a line without it."""

    @pytest.mark.parametrize("switch", [False, True])
    @pytest.mark.parametrize(
        ("platform", "chat_type"),
        [
            ("telegram", "group"),
            ("telegram", "supergroup"),
            ("slack", "group"),
            ("mattermost", "group"),
            ("discord", "group"),
            ("teams", "group"),
            ("whatsapp", "group"),
        ],
    )
    async def test_a_room_runs_under_the_binding_not_as_the_agent(
        self, platform: str, chat_type: str, switch: bool
    ):
        policy = {"mode": "open", "answer_unlinked_direct": switch}
        if platform == "discord":
            policy["discord_guild_ids"] = ["123"]
        line = _Line(policy, platform=platform)

        await line.route(chat_type=chat_type)

        sent = line.answer_default.await_args.kwargs
        assert sent["admit_unlinked"] is True
        assert sent["as_agent"] is False
        assert line.turns[0]["as_agent"] is False
        line.invited.assert_not_awaited()

    @pytest.mark.parametrize("platform", ["telegram", "slack", "mattermost", "discord", "teams"])
    @pytest.mark.parametrize("switch", [False, True])
    async def test_a_private_chat_on_another_platform_still_asks_for_a_link(
        self, platform: str, switch: bool
    ):
        """Even a stored policy that carries the key: the platform cannot take it."""
        line = _Line({"mode": "open", "answer_unlinked_direct": switch}, platform=platform)

        await line.route()

        line.invited.assert_awaited_once()
        line.answer_default.assert_not_awaited()
        assert line.turns == []


NUMBER = "+48 600 700 800"


class TestKeepingTheNumber:
    """A stranger's number is written once, after the access check, and never from the upsert."""

    def _world(self, *, admits: bool = True, linked: bool = False):
        identity = MagicMock(user_id=uuid.uuid4() if linked else None)
        router = MagicMock(admits_stranger=MagicMock(return_value=admits))
        repo = MagicMock(set_phone=AsyncMock(), clear_phone=AsyncMock())

        @asynccontextmanager
        async def sessions() -> AsyncGenerator[MagicMock]:
            yield MagicMock()

        patches = (
            patch(f"{MODULE}.get_db_context", sessions),
            patch(f"{MODULE}.channel_bot_repo.get_for_org", AsyncMock(return_value=_bot())),
            patch(
                f"{MODULE}.channel_identity_repo.get_by_platform_user",
                AsyncMock(return_value=identity),
            ),
            patch(
                f"{MODULE}.member_repo.get_active",
                AsyncMock(return_value=MagicMock() if linked else None),
            ),
            patch(f"{MODULE}.ChannelMessageRouter", MagicMock(return_value=router)),
            patch(f"{MODULE}.whatsapp_customer_repo.set_phone", repo.set_phone),
            patch(f"{MODULE}.whatsapp_customer_repo.clear_phone", repo.clear_phone),
        )
        return repo, patches

    async def _keep(self, number: str | None = NUMBER, **world: bool):
        repo, patches = self._world(**world)
        message = replace(_text()[0], phone=number)
        with contextlib.ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            await _KEEP_PHONE(BOT, ORG, CHAT, [message])
        return repo

    @pytest.mark.security
    async def test_an_unlinked_customer_on_a_public_line_has_their_digits_kept(self):
        repo = await self._keep()

        assert repo.set_phone.await_args.kwargs == {
            "organization_id": ORG,
            "bot_id": uuid.UUID(BOT),
            "bsuid": CHAT,
            "phone": "48600700800",
        }
        repo.clear_phone.assert_not_awaited()

    @pytest.mark.security
    async def test_nothing_is_kept_when_the_line_is_closed_or_the_whitelist_refuses(self):
        repo = await self._keep(admits=False)

        repo.set_phone.assert_not_awaited()

    @pytest.mark.security
    async def test_a_linked_sender_has_the_number_cleared_and_not_kept(self):
        repo = await self._keep(linked=True)

        assert repo.clear_phone.await_args.kwargs == {"organization_id": ORG, "bsuid": CHAT}
        repo.set_phone.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize("number", [None, "", "abc", "1" * 16])
    async def test_a_number_that_is_not_one_to_fifteen_digits_is_not_kept(self, number):
        repo = await self._keep(number)

        repo.set_phone.assert_not_awaited()

    @pytest.mark.security
    async def test_a_failing_write_still_routes_the_batch_and_logs_no_digits(self, caplog):
        repo, patches = self._world()
        repo.set_phone.side_effect = RuntimeError("48600700800 refused")
        process = AsyncMock()
        with contextlib.ExitStack() as stack:
            for each in patches:
                stack.enter_context(each)
            stack.enter_context(patch(f"{MODULE}._keep_phone", _KEEP_PHONE))
            stack.enter_context(patch(f"{MODULE}.process_channel_events_in_order", process))
            stack.enter_context(patch(f"{MODULE}.WindowStore", MagicMock()))
            caplog.set_level(logging.DEBUG)
            message = replace(_text()[0], phone=NUMBER)
            store = MagicMock(has_held=AsyncMock(return_value=False))
            await handle_customer(BOT, ORG, CHAT, [message], store=store)

        process.assert_awaited_once()
        unsaved = [r for r in caplog.records if r.getMessage() == "whatsapp_phone_unsaved"]
        assert [(r.bot_id, r.error) for r in unsaved] == [(BOT, "RuntimeError")]
        for record in caplog.records:
            assert not {"600", "700", "800"} & set(
                re.findall(r"\d{3}", record.getMessage() + repr(record.__dict__))
            )

    @pytest.mark.security
    async def test_the_inbound_upsert_is_given_no_number(self):
        import inspect

        from app.repositories import whatsapp_customer as repo

        assert "phone" not in inspect.signature(repo.record_inbound).parameters
        assert "phone" not in inspect.getsource(repo.record_inbound)

    @pytest.mark.security
    async def test_the_number_is_written_before_the_batch_is_routed(self):
        order: list[str] = []
        keep = AsyncMock(side_effect=lambda *a, **k: order.append("keep"))
        process = AsyncMock(side_effect=lambda *a, **k: order.append("route"))
        store = MagicMock(has_held=AsyncMock(return_value=False))
        with (
            patch(f"{MODULE}._keep_phone", keep),
            patch(f"{MODULE}.process_channel_events_in_order", process),
        ):
            await handle_customer(BOT, ORG, CHAT, _text(), store=store)

        assert order == ["keep", "route"]


def _line(**policy: object) -> MagicMock:
    return MagicMock(platform="whatsapp", access_policy={"answer_unlinked_direct": True, **policy})


def _from_customer(chat_type: str = "private") -> IncomingMessage:
    return IncomingMessage(
        platform="whatsapp", bot_id=BOT, platform_user_id=f"{ORG}:{CHAT}", platform_chat_id=CHAT,
        chat_type=chat_type, text="hi",
    )  # fmt: skip


class TestAdmitsAStranger:
    """The real decision, with a real access policy and nothing doubled."""

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("bot", "chat_type", "admitted"),
        [
            (_line(), "private", True),
            (_line(answer_unlinked_direct=False), "private", False),
            (_line(mode="whitelist", whitelist=["someone-else"]), "private", False),
            (_line(mode="whitelist", whitelist=[f"{ORG}:{CHAT}"]), "private", True),
            (_line(), "group", False),
        ],
    )
    def test_the_policy_decides(self, bot, chat_type, admitted):
        assert ChannelMessageRouter().admits_stranger(_from_customer(chat_type), bot) is admitted

    @pytest.mark.security
    async def test_a_refused_senders_number_is_not_stored(self):
        repo = MagicMock(set_phone=AsyncMock(), clear_phone=AsyncMock())

        @asynccontextmanager
        async def sessions() -> AsyncGenerator[MagicMock]:
            yield MagicMock()

        message = replace(_text()[0], phone=NUMBER)
        with (
            patch(f"{MODULE}.get_db_context", sessions),
            patch(
                f"{MODULE}.channel_bot_repo.get_for_org",
                AsyncMock(return_value=_line(mode="whitelist", whitelist=["someone-else"])),
            ),
            patch(
                f"{MODULE}.channel_identity_repo.get_by_platform_user",
                AsyncMock(return_value=None),
            ),
            patch(f"{MODULE}.whatsapp_customer_repo.set_phone", repo.set_phone),
            patch(f"{MODULE}.whatsapp_customer_repo.clear_phone", repo.clear_phone),
        ):
            await _KEEP_PHONE(BOT, ORG, CHAT, [message])

        repo.set_phone.assert_not_awaited()
