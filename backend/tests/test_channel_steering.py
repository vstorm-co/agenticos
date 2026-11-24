"""Adding to a channel turn while it runs, and asking on the side of one (#2087)."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from app.services.channels.base import IncomingMessage
from app.services.channels.router import ChannelMessageRouter
from app.services.channels.steering import (
    aside_question,
    current_steering,
    is_asked_aside,
)

pytestmark = pytest.mark.anyio


def _message(text: str, *, user: str = "U1") -> IncomingMessage:
    return IncomingMessage(
        platform="slack",
        bot_id="00000000-0000-0000-0000-000000000001",
        platform_user_id=user,
        platform_chat_id="C1",
        chat_type="channel",
        text=text,
        message_id=text,
    )


@pytest.mark.parametrize(
    ("text", "question"),
    [
        ("/btw how many are left?", "how many are left?"),
        ("  /BTW   what's next ", "what's next"),
        ("/btw", None),
        ("/btwx hi", None),
        ("use the EU numbers", None),
    ],
)
def test_a_side_question_is_the_words_after_the_command(text: str, question: str | None) -> None:
    assert aside_question(text) == question


class _Turns:
    """`_route_inner` stood in: the first message runs until released."""

    def __init__(self, *, asks_again: bool = True) -> None:
        # Whether the run makes another model request after it is released -
        # the one that carries whatever arrived meanwhile.
        self.asks_again = asks_again
        self.running = asyncio.Event()
        self.release = asyncio.Event()
        self.seen: list[tuple[str, Any, bool]] = []

    async def __call__(self, incoming: IncomingMessage, db: Any) -> None:
        self.seen.append((incoming.text, current_steering(), is_asked_aside()))
        if len(self.seen) == 1:
            self.running.set()
            await self.release.wait()
            steering = current_steering()
            assert steering is not None or is_asked_aside()
            if self.asks_again and steering is not None:
                steering.take()


async def _wait(event: asyncio.Event) -> None:
    with anyio.fail_after(5):
        await event.wait()


async def _route_two(
    second: IncomingMessage, *, asks_again: bool = True, first: IncomingMessage | None = None
) -> _Turns:
    turns = _Turns(asks_again=asks_again)
    router = ChannelMessageRouter()
    with (
        patch("app.services.channels.router.claim_delivery", new=AsyncMock(return_value=True)),
        patch.object(ChannelMessageRouter, "_route_inner", turns),
    ):
        first = asyncio.create_task(
            router.route(first or _message("draft the report"), MagicMock())
        )
        await _wait(turns.running)
        second_task = asyncio.create_task(router.route(second, MagicMock()))
        await asyncio.sleep(0)
        turns.release.set()
        await first
        await second_task
    return turns


async def test_a_message_from_the_person_whose_turn_it_is_joins_that_turn():
    turns = await _route_two(_message("use the EU numbers"))

    # One turn ran; the correction rode in it rather than starting another.
    assert [text for text, _inbox, _aside in turns.seen] == ["draft the report"]


@pytest.mark.security
async def test_a_remark_not_addressed_to_the_bot_does_not_join_the_turn():
    """Review on #2062: the starter's word to a colleague in the thread was fed to
    the model and stored; a second after the turn it is ignored, and now too."""
    from dataclasses import replace

    remark = replace(_message("thanks, I'll check with Ola"), chat_type="group", addressed=False)
    turns = await _route_two(remark)

    # Not steered into the running turn; routed as a message of its own, which
    # the router then ignores as overheard.
    assert [text for text, _inbox, _aside in turns.seen] == [
        "draft the report",
        "thanks, I'll check with Ola",
    ]


async def test_a_message_with_a_file_is_a_turn_of_its_own():
    """Codex review of #2062: the steer took the text and the router stopped before
    the file was fetched, so the agent read "use this spreadsheet" without it."""
    from dataclasses import replace

    from app.services.channels.base import IncomingAttachment

    sheet = IncomingAttachment(
        filename="q3.xlsx", mime_type="application/vnd.ms-excel", size=10, handle="F1"
    )
    corrected = replace(_message("use this corrected spreadsheet"), attachments=[sheet])
    turns = await _route_two(corrected)

    assert [text for text, _inbox, _aside in turns.seen] == [
        "draft the report",
        "use this corrected spreadsheet",
    ]


async def test_a_colleagues_message_is_a_turn_of_its_own():
    turns = await _route_two(_message("what about Q3?", user="U2"))

    assert [text for text, _inbox, _aside in turns.seen] == [
        "draft the report",
        "what about Q3?",
    ]


async def test_a_side_question_is_answered_at_once_without_its_command():
    turns = _Turns()
    router = ChannelMessageRouter()
    with (
        patch("app.services.channels.router.claim_delivery", new=AsyncMock(return_value=True)),
        patch.object(ChannelMessageRouter, "_route_inner", turns),
    ):
        first = asyncio.create_task(router.route(_message("draft the report"), MagicMock()))
        await _wait(turns.running)
        # Answered while the turn still holds the chat - not queued behind it.
        await router.route(_message("/btw how long will it take?"), MagicMock())
        assert turns.seen[1][0] == "how long will it take?"
        assert turns.seen[1][2] is True
        turns.release.set()
        await first


async def test_side_question_is_tool_free_when_another_worker_may_own_the_turn():
    turns = _Turns()
    turns.release.set()
    router = ChannelMessageRouter()
    with (
        patch("app.services.channels.router.claim_delivery", new=AsyncMock(return_value=True)),
        patch.object(ChannelMessageRouter, "_route_inner", turns),
    ):
        await router.route(_message("/btw anything new?"), MagicMock())

    text, inbox, aside = turns.seen[0]
    assert (text, aside) == ("anything new?", True)
    assert inbox is None


async def test_a_correction_too_late_for_the_turn_is_answered_as_its_own():
    """Sent after the turn's last request, it has nothing to steer - so it runs."""
    turns = await _route_two(_message("and the totals"), asks_again=False)

    assert [text for text, _inbox, _aside in turns.seen] == ["draft the report", "and the totals"]


async def test_a_durable_turn_registers_a_worker_independent_steering_reader(monkeypatch):
    from uuid import uuid4

    from app.services.channels import router as routing
    from app.services.channels.steering import current_steering, queued_turn

    monkeypatch.setattr(routing, "claim_delivery", AsyncMock(return_value=True))

    async def inner(_incoming, _db):
        inbox = current_steering()
        assert inbox is not None and inbox.poll is not None

    router = ChannelMessageRouter()
    monkeypatch.setattr(router, "_route_inner", inner)
    with queued_turn(uuid4()):
        await router.route(_message("read it"), MagicMock())


async def test_slashless_help_is_a_command_instead_of_a_correction():
    from dataclasses import replace

    turns = await _route_two(replace(_message("help"), platform="mattermost"))
    assert [text for text, _, _ in turns.seen] == ["draft the report", "help"]


@pytest.mark.parametrize("addressed", [False, True])
@pytest.mark.parametrize("bot_state", ["active", "inactive", "missing"])
async def test_telegram_addressing_is_resolved_before_in_process_steering(
    monkeypatch, addressed, bot_state
):
    from dataclasses import replace
    from types import SimpleNamespace

    from app.services.channels import router as module

    bot = SimpleNamespace(is_active=bot_state == "active", access_policy={})
    resolve = AsyncMock(return_value=addressed)
    monkeypatch.setattr(
        module.channel_bot_repo,
        "get_for_inbound",
        AsyncMock(return_value=None if bot_state == "missing" else bot),
    )
    monkeypatch.setattr(
        module, "get_adapter", lambda platform: SimpleNamespace(resolve_addressing=resolve)
    )
    monkeypatch.setattr(module, "unseal_bot_token", lambda bot: "test-token")
    first = replace(
        _message("draft the report"), platform="telegram", chat_type="group", addressed=True
    )
    second = replace(_message("use the EU numbers"), platform="telegram", chat_type="group")
    turns = await _route_two(second, first=first)
    assert len(turns.seen) == (1 if addressed or bot_state != "active" else 2)
    assert resolve.await_count == int(bot_state == "active")
