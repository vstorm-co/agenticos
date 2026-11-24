"""The SDK must not advance Telegram's offset ahead of durable message admission."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Dispatcher
from aiogram.methods import GetMe, GetUpdates
from aiogram.types import Chat, Message, Update, User

from app.services.channels.telegram import _MessageAdmission

pytestmark = pytest.mark.anyio


def update(identifier: int) -> Update:
    return Update(
        update_id=identifier,
        message=Message(
            message_id=identifier,
            date=datetime(2026, 11, 16, tzinfo=UTC),
            chat=Chat(id=42, type="private"),
            from_user=User(id=7, is_bot=False, first_name="Test"),
            text="Check Friday",
        ),
    )


async def test_failed_storage_is_retried_before_the_real_sdk_advances_its_offset(monkeypatch):
    offsets: list[int | None] = []
    admit = AsyncMock(side_effect=[RuntimeError("database unavailable"), None, None])
    boundary = _MessageAdmission(admit)
    bot = AsyncMock(session=SimpleNamespace(timeout=0), id=42)

    async def request(method: GetUpdates, **_options: object) -> object:
        offsets.append(method.offset)
        response = [update(7 if len(offsets) < 3 else 8)]
        return await boundary(AsyncMock(return_value=response), bot, method)

    bot.side_effect = request
    monkeypatch.setattr("aiogram.dispatcher.dispatcher.Backoff.asleep", AsyncMock())
    stream = Dispatcher._listen_updates(bot)
    try:
        assert (await anext(stream)).update_id == 7
        assert offsets == [None, None], "failed admission was already acknowledged"
        assert (await anext(stream)).update_id == 8
        assert offsets == [None, None, 8]
        assert [call.args[0].message_id for call in admit.await_args_list] == [7, 7, 8]
    finally:
        await stream.aclose()


@pytest.mark.parametrize("updates", [[], [Update(update_id=7)]])
async def test_empty_batches_and_other_update_types_do_not_create_message_jobs(updates):
    admit = AsyncMock()
    result = await _MessageAdmission(admit)(
        AsyncMock(return_value=updates), AsyncMock(), GetUpdates()
    )
    assert result is updates
    admit.assert_not_awaited()


async def test_other_bot_methods_preserve_the_sdk_response_without_admission():
    response = object()
    admit = AsyncMock()
    assert (
        await _MessageAdmission(admit)(AsyncMock(return_value=response), AsyncMock(), GetMe())
        is response
    )
    admit.assert_not_awaited()
