"""The chat lock a continuation shares with the router's turns (#2656)."""

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.channels.base import split_thread
from app.services.channels.directory import BoundChannelDirectory
from app.services.channels.router import chat_lock

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("chat_id", ["C1:1700.1", "-1001234567", "19:abc@thread.tacv2"])
def test_the_chat_lock_key_round_trips_through_a_recorded_destination(chat_id: str) -> None:
    """(pinning) The key a continuation locks on is the one a turn locked on."""
    channel_id, thread_id = split_thread(chat_id)

    directory = BoundChannelDirectory(
        adapter=MagicMock(),
        bot_token="t",
        bot_id=uuid4(),
        channel_id=channel_id,
        thread_id=thread_id or None,
    )

    assert directory.destination is not None
    assert directory.destination.platform_chat_id == chat_id


async def test_two_holders_of_one_chat_lock_run_one_after_the_other() -> None:
    events: list[str] = []

    async def hold(name: str) -> None:
        async with chat_lock("b", "c"):
            events.append(f"{name} in")
            await asyncio.sleep(0.05)
            events.append(f"{name} out")

    await asyncio.gather(hold("first"), hold("second"))

    assert events in (
        ["first in", "first out", "second in", "second out"],
        ["second in", "second out", "first in", "first out"],
    )
