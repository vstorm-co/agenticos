"""Thumbs under a channel answer become the presser's rating of it (#2084)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.channels.base import FeedbackComment, IncomingPress, feedback_value
from app.services.channels.feedback import ChannelFeedback
from app.worker.background.channel import process_channel_press, process_feedback_comment

pytestmark = pytest.mark.anyio

MODULE = "app.services.channels.feedback"
BOT_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _press(value: str | None = None) -> IncomingPress:
    return IncomingPress(
        platform="slack",
        bot_id=str(BOT_ID),
        platform_user_id="U1",
        platform_chat_id="C1",
        value=value if value is not None else feedback_value(str(RUN_ID), helpful=True),
    )


class _World:
    """Every lookup the rating makes, answering the happy path unless told otherwise."""

    def __init__(self) -> None:
        self.bot = MagicMock(id=BOT_ID, organization_id=uuid.uuid4(), is_active=True)
        self.run = MagicMock(id=RUN_ID)
        self.answer = MagicMock(id=uuid.uuid4(), role="assistant")
        self.ctx = MagicMock(user_id=USER_ID)
        self.existing: Any = None
        self.adapter = MagicMock(
            settle_feedback=AsyncMock(), acknowledge=AsyncMock(), ask_feedback_comment=AsyncMock()
        )

    def patches(self) -> list[Any]:
        return [
            patch(f"{MODULE}.channel_bot_repo.get_for_inbound", AsyncMock(return_value=self.bot)),
            patch(f"{MODULE}.agent_run_repo.get_run", AsyncMock(return_value=self.run)),
            patch(f"{MODULE}.linked_member", AsyncMock(return_value=self.ctx)),
            patch(
                f"{MODULE}.conversation_repo.get_messages_by_run",
                AsyncMock(return_value=[MagicMock(role="user"), self.answer]),
            ),
            patch(
                f"{MODULE}.rating_repo.get_rating_by_message_and_user",
                AsyncMock(return_value=self.existing),
            ),
            patch(f"{MODULE}.rating_repo.create_rating", AsyncMock()),
            patch(f"{MODULE}.rating_repo.update_rating", AsyncMock()),
            patch(f"{MODULE}.get_adapter", return_value=self.adapter),
            patch(f"{MODULE}.unseal_bot_token", return_value="xoxb"),
        ]


async def _rate(world: _World, press: IncomingPress) -> tuple[bool, dict[str, Any]]:
    mocks: dict[str, Any] = {}
    patches = world.patches()
    for one in patches:
        mocks[one.attribute] = one.start()
    try:
        return await ChannelFeedback(MagicMock()).rate(press), mocks
    finally:
        for one in patches:
            one.stop()


async def _comment(world: _World, comment: FeedbackComment) -> tuple[bool, dict[str, Any]]:
    mocks: dict[str, Any] = {}
    patches = world.patches()
    for one in patches:
        mocks[one.attribute] = one.start()
    try:
        return await ChannelFeedback(MagicMock()).comment(comment), mocks
    finally:
        for one in patches:
            one.stop()


def _said(text: str = "Wrong dates", run: str | None = None) -> FeedbackComment:
    return FeedbackComment(
        platform="slack",
        bot_id=str(BOT_ID),
        platform_user_id="U1",
        run_id=run if run is not None else str(RUN_ID),
        text=text,
    )


async def test_a_thumbs_up_is_the_presser_s_rating_of_the_run_s_answer() -> None:
    world = _World()

    rated, mocks = await _rate(world, _press())

    assert rated
    assert mocks["create_rating"].await_args.kwargs == {
        "message_id": world.answer.id,
        "user_id": USER_ID,
        "rating": 1,
        "comment": None,
    }
    world.adapter.settle_feedback.assert_awaited_once()


async def test_pressing_again_changes_the_rating_rather_than_adding_one() -> None:
    world = _World()
    world.existing = MagicMock(rating=1, comment=None)

    rated, mocks = await _rate(world, _press(feedback_value(str(RUN_ID), helpful=False)))

    assert rated
    mocks["create_rating"].assert_not_awaited()
    assert mocks["update_rating"].await_args.kwargs == {"new_rating": -1, "comment": None}


async def test_a_thumbs_down_asks_what_was_wrong() -> None:
    world = _World()

    await _rate(world, _press(feedback_value(str(RUN_ID), helpful=False)))

    assert world.adapter.ask_feedback_comment.await_args.args[2] == str(RUN_ID)


async def test_a_form_that_would_not_open_leaves_the_rating() -> None:
    world = _World()
    world.adapter.ask_feedback_comment.side_effect = RuntimeError("no trigger")

    rated, _mocks = await _rate(world, _press(feedback_value(str(RUN_ID), helpful=False)))

    assert rated


async def test_what_was_wrong_is_kept_on_the_rating_it_follows() -> None:
    world = _World()
    world.existing = MagicMock(rating=-1, comment=None)

    kept, mocks = await _comment(world, _said())

    assert kept
    assert mocks["update_rating"].await_args.kwargs == {"new_rating": -1, "comment": "Wrong dates"}


async def test_a_comment_with_no_rating_yet_is_a_thumbs_down() -> None:
    world = _World()

    kept, mocks = await _comment(world, _said())

    assert kept
    assert mocks["create_rating"].await_args.kwargs["rating"] == -1
    assert mocks["create_rating"].await_args.kwargs["comment"] == "Wrong dates"


async def test_a_rating_without_a_comment_keeps_the_one_it_had() -> None:
    world = _World()
    world.existing = MagicMock(rating=-1, comment="Wrong dates")

    _rated, mocks = await _rate(world, _press())
    assert mocks["update_rating"].await_args.kwargs == {"new_rating": 1, "comment": "Wrong dates"}


@pytest.mark.parametrize("change", ["no_bot", "bad_run"])
async def test_a_comment_it_cannot_attribute_is_dropped(change: str) -> None:
    world = _World()
    if change == "no_bot":
        world.bot = None

    kept, mocks = await _comment(world, _said(run="nope" if change == "bad_run" else None))

    assert not kept
    mocks["create_rating"].assert_not_awaited()


async def test_a_comment_is_kept_in_the_background_and_a_failure_only_logged() -> None:
    module = "app.worker.background.channel"
    with (
        patch(f"{module}.get_db_context") as db_context,
        patch(f"{module}.ChannelFeedback") as feedback,
    ):
        db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)
        feedback.return_value.comment = AsyncMock()
        await process_feedback_comment(_said())
        feedback.return_value.comment.side_effect = RuntimeError("boom")
        await process_feedback_comment(_said())

    assert feedback.return_value.comment.await_count == 2


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("nothing", "aos:prompt:0"),
        ("nothing", "aosfb:not-a-uuid:+"),
        ("no_bot", None),
        ("inactive", None),
        ("no_run", None),
        ("unlinked", None),
        ("no_answer", None),
    ],
)
async def test_anything_it_cannot_attribute_is_not_recorded(change: str, value: str | None) -> None:
    world = _World()
    if change == "no_bot":
        world.bot = None
    elif change == "inactive":
        world.bot.is_active = False
    elif change == "no_run":
        world.run = None
    elif change == "unlinked":
        world.ctx = None
    elif change == "no_answer":
        world.answer.role = "user"

    rated, mocks = await _rate(world, _press(value))

    assert not rated
    mocks["create_rating"].assert_not_awaited()


async def test_a_thumbs_press_goes_to_the_rating_and_a_prompt_press_to_the_prompt() -> None:
    module = "app.worker.background.channel"
    with (
        patch(f"{module}.get_db_context") as db_context,
        patch(f"{module}.ChannelFeedback") as feedback,
        patch(f"{module}.ChannelPrompts") as prompts,
    ):
        db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        db_context.return_value.__aexit__ = AsyncMock(return_value=False)
        feedback.return_value.rate = AsyncMock()
        prompts.return_value.press = AsyncMock()

        await process_channel_press(_press())
        await process_channel_press(_press("aos:prompt:1"))

    feedback.return_value.rate.assert_awaited_once()
    prompts.return_value.press.assert_awaited_once()
