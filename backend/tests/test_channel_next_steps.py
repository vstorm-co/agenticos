"""Next steps as buttons in a chat (#2301).

What has to hold: the steps an answer offered reach the chat as buttons; a press
names a stored row and an index and nothing else, is taken once, and becomes the
presser's next message in the chat it was offered in - routed like any other, so
the link, the access policy and the rate limit apply to it as they do to typing.
"""

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.channel_prompt import FOLLOW_UP, QUESTION
from app.services.channels.base import IncomingMessage, IncomingPress
from app.services.channels.next_steps import (
    OFFERED,
    ChannelNextSteps,
    next_steps_of,
    next_value,
    read_next,
)
from app.services.transcript import RecordedToolCall
from app.worker.background.channel import process_channel_press

pytestmark = pytest.mark.anyio

_MODULE = "app.services.channels.next_steps"
ORG = uuid.uuid4()
RUN = uuid.uuid4()


def _bot(**fields: Any) -> MagicMock:
    return MagicMock(
        **{"id": uuid.uuid4(), "organization_id": ORG, "is_active": True, "api_base_url": None}
        | fields
    )


def _row(**fields: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": FOLLOW_UP,
        "run_id": RUN,
        "platform_chat_id": "C1:1.0",
        "chat_type": "group",
        "choices": ["Make it a table", "Do this every Monday"],
        "answered_at": None,
    }
    return MagicMock(**defaults | fields)


def _press(bot: MagicMock, value: str) -> IncomingPress:
    return IncomingPress(
        platform="slack",
        bot_id=str(bot.id),
        platform_user_id="U2",
        platform_chat_id="C1:1.0",
        value=value,
        platform_username="ada",
        message_id="9.9",
    )


def _called(name: str, result: str | None) -> RecordedToolCall:
    return RecordedToolCall(tool_call_id="c", tool_name=name, args={}, result=result)


class _Patched:
    """What a press or an offer reaches for, patched; what was answered recorded."""

    def __init__(self, *, bot: MagicMock | None, row: MagicMock | None) -> None:
        self.adapter = MagicMock(
            send_prompt=AsyncMock(), acknowledge=AsyncMock(), settle_prompt=AsyncMock()
        )
        self.answered: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []

        async def answer(db: Any, *, prompt: MagicMock, value: dict[str, Any]) -> MagicMock:
            prompt.answered_at = "now"
            self.answered.append(value)
            return prompt

        async def create(db: Any, **fields: Any) -> MagicMock:
            self.created.append(fields)
            return _row(**fields)

        self.patches = [
            patch(f"{_MODULE}.get_adapter", return_value=self.adapter),
            patch(f"{_MODULE}.unseal_bot_token", return_value="xoxb"),
            patch(f"{_MODULE}.channel_bot_repo.get_for_inbound", new=AsyncMock(return_value=bot)),
            patch(f"{_MODULE}.channel_prompt_repo.claim", new=AsyncMock(return_value=row)),
            patch(f"{_MODULE}.channel_prompt_repo.answer", new=answer),
            patch(f"{_MODULE}.channel_prompt_repo.create", new=create),
        ]

    def __enter__(self) -> _Patched:
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in reversed(self.patches):
            p.stop()


class TestTheValues:
    def test_a_value_round_trips_and_fits_a_telegram_button(self):
        row_id = uuid.uuid4().hex
        assert read_next(next_value(row_id, 2)) == (row_id, 2)
        assert len(next_value(row_id, 2).encode()) <= 64

    @pytest.mark.parametrize("value", ["aos:abc:0", "aosfb:run:+", "aosnx:abc:x", "aosnx:abc"])
    def test_anything_else_is_not_a_step(self, value: str):
        assert read_next(value) is None


class TestTheStepsATurnOffered:
    def test_the_last_offer_is_the_one_shown(self):
        called = [
            _called("suggest_next_steps", json.dumps({"steps": ["Old"]})),
            _called("web_search", "results"),
            _called("suggest_next_steps", json.dumps({"steps": ["Make it a table", 3]})),
        ]

        assert next_steps_of(called) == ["Make it a table"]

    def test_a_call_that_never_returned_is_passed_over(self):
        called = [
            _called("suggest_next_steps", json.dumps({"steps": ["Earlier"]})),
            _called("suggest_next_steps", None),
        ]

        assert next_steps_of(called) == ["Earlier"]

    @pytest.mark.parametrize(
        "result",
        [
            "Offer at most 3 next steps; keep the most useful.",
            '["a list"]',
            '{"steps": "one string"}',
        ],
    )
    def test_a_result_that_is_not_the_tool_s_answer_offers_nothing(self, result: str):
        """A retry notice - the tool sent the call back - is not a set of steps."""
        assert next_steps_of([_called("suggest_next_steps", result)]) == []

    def test_a_turn_that_offered_nothing_has_nothing(self):
        assert next_steps_of([_called("web_search", "results")]) == []


class TestOffering:
    async def test_the_steps_are_buttons_under_the_answer(self):
        bot = _bot()
        incoming = IncomingMessage(
            platform="slack",
            bot_id=str(bot.id),
            platform_user_id="U1",
            platform_chat_id="C1:1.0",
            chat_type="group",
            text="Compare the vendors",
        )
        with _Patched(bot=bot, row=None) as env:
            await ChannelNextSteps(MagicMock()).offer(
                bot, incoming, run_id=RUN, steps=["Make it a table", "Do this every Monday"]
            )

        assert env.created[0] | {"organization_id": ORG} == env.created[0]
        assert env.created[0]["kind"] == FOLLOW_UP
        assert env.created[0]["chat_type"] == "group"
        sent = env.adapter.send_prompt.await_args.args[1]
        assert sent.text == OFFERED
        assert sent.platform_chat_id == "C1:1.0"
        assert [choice.label for choice in sent.choices] == [
            "Make it a table",
            "Do this every Monday",
        ]
        assert [read_next(choice.value)[1] for choice in sent.choices] == [0, 1]

    async def test_a_platform_that_refuses_them_costs_nothing_else(self):
        bot = _bot()
        incoming = MagicMock(platform="telegram", platform_chat_id="42", chat_type="private")
        with _Patched(bot=bot, row=None) as env:
            env.adapter.send_prompt.side_effect = RuntimeError("Telegram is down")
            await ChannelNextSteps(MagicMock()).offer(bot, incoming, run_id=RUN, steps=["Again"])


class TestPressing:
    async def test_a_press_is_the_presser_saying_the_step_in_that_chat(self):
        bot = _bot()
        row = _row()
        with _Patched(bot=bot, row=row) as env:
            said = await ChannelNextSteps(MagicMock()).take(_press(bot, next_value(row.id.hex, 1)))

        assert said == IncomingMessage(
            platform="slack",
            bot_id=str(bot.id),
            platform_user_id="U2",
            platform_chat_id="C1:1.0",
            chat_type="group",
            text="Do this every Monday",
            platform_username="ada",
            message_id="9.9",
            addressed=True,
        )
        assert env.answered == [{"step": "Do this every Monday"}]
        env.adapter.acknowledge.assert_awaited_once()
        assert env.adapter.settle_prompt.await_args.args[2] == "→ Do this every Monday"

    async def test_a_second_press_says_nothing_twice(self):
        bot = _bot()
        row = _row(answered_at="earlier")
        with _Patched(bot=bot, row=row) as env:
            said = await ChannelNextSteps(MagicMock()).take(_press(bot, next_value(row.id.hex, 0)))

        assert said is None
        assert env.answered == []
        # Still told it arrived, so Telegram stops spinning the button.
        env.adapter.acknowledge.assert_awaited_once()

    @pytest.mark.security
    @pytest.mark.parametrize(
        "row",
        [
            pytest.param(_row(kind=QUESTION), id="a question's row"),
            pytest.param(_row(choices=["Only one"]), id="a step it never offered"),
        ],
    )
    async def test_a_value_naming_what_was_never_offered_says_nothing(self, row: MagicMock):
        bot = _bot()
        with _Patched(bot=bot, row=row) as env:
            said = await ChannelNextSteps(MagicMock()).take(_press(bot, next_value(row.id.hex, 1)))

        assert said is None
        assert env.answered == []

    @pytest.mark.security
    async def test_a_row_another_bot_offered_is_not_found(self):
        """`claim` is scoped to the bot the press arrived on."""
        bot = _bot()
        with _Patched(bot=bot, row=None) as env:
            said = await ChannelNextSteps(MagicMock()).take(
                _press(bot, next_value(uuid.uuid4().hex, 0))
            )

        assert said is None
        env.adapter.acknowledge.assert_not_awaited()

    @pytest.mark.parametrize(
        ("bot", "value"),
        [
            pytest.param(None, None, id="a bot that is gone"),
            pytest.param(_bot(is_active=False), None, id="a bot switched off"),
            pytest.param(_bot(), "aosnx:not-hex:0", id="a row id that is no id"),
            pytest.param(_bot(), "aos:abc:0", id="another button"),
        ],
    )
    async def test_a_press_that_names_nothing_does_nothing(
        self, bot: MagicMock | None, value: str | None
    ):
        row = _row()
        pressed_on = bot or _bot()
        with _Patched(bot=bot, row=row) as env:
            said = await ChannelNextSteps(MagicMock()).take(
                _press(pressed_on, value or next_value(row.id.hex, 0))
            )

        assert said is None
        env.adapter.acknowledge.assert_not_awaited()


class TestTheBackgroundHandler:
    async def test_a_press_is_routed_as_the_next_message(self):
        module = "app.worker.background.channel"
        said = MagicMock()
        with (
            patch(f"{module}.get_db_context") as db_context,
            patch(f"{module}.ChannelNextSteps") as next_steps,
            patch(f"{module}.ChannelMessageRouter") as router,
            patch(f"{module}.ChannelPrompts") as prompts,
        ):
            db_context.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            db_context.return_value.__aexit__ = AsyncMock(return_value=False)
            next_steps.return_value.take = AsyncMock(side_effect=[said, None])
            router.return_value.route = AsyncMock()
            prompts.return_value.press = AsyncMock()
            await process_channel_press(MagicMock(value=next_value(uuid.uuid4().hex, 0)))
            await process_channel_press(MagicMock(value=next_value(uuid.uuid4().hex, 0)))

        router.return_value.route.assert_awaited_once()
        assert router.return_value.route.await_args.args[0] is said
        prompts.return_value.press.assert_not_awaited()
