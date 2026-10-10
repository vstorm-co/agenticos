"""Approvals and questions in a chat, as buttons (#2064, #2067, #2068).

What has to hold: a press names a stored prompt and nothing else; the presser
acts as their linked member, with their own permissions; an approval continues
the run only once nothing is left pending, and a question only once every one of
its call's questions is answered; and whatever was decided is said in the chat.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.ask_user import QuestionChoice, QuestionItem
from app.core.exceptions import BadRequestError
from app.db.models.agent_run import ApprovalStatus
from app.db.models.channel_prompt import APPROVAL, QUESTION
from app.schemas.agent import ParkedCall, ParkedQuestion
from app.services.channels.base import (
    ChannelAdapter,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
    press_value,
    read_press,
)
from app.services.channels.prompts import ALREADY, LINK_FIRST, NOT_YOURS, SKIP, ChannelPrompts

pytestmark = pytest.mark.anyio

_MODULE = "app.services.channels.prompts"
ORG = uuid.uuid4()
USER = uuid.uuid4()
RUN = uuid.uuid4()


def _bot() -> MagicMock:
    return MagicMock(id=uuid.uuid4(), organization_id=ORG, is_active=True, api_base_url=None)


def _prompt(kind: str = APPROVAL, **fields: Any) -> MagicMock:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": kind,
        "run_id": RUN,
        "platform_chat_id": "C1:1.0",
        "approval_id": uuid.uuid4() if kind == APPROVAL else None,
        "tool_call_id": "ask-1" if kind == QUESTION else None,
        "question_index": 0 if kind == QUESTION else None,
        "choices": ["Approve", "Reject"] if kind == APPROVAL else ["Formal", "Casual"],
        "answer": None,
        "answered_at": None,
    }
    return MagicMock(**{**defaults, **fields})


def _press(prompt: MagicMock, choice: int | None, bot: MagicMock) -> IncomingPress:
    return IncomingPress(
        platform="slack",
        bot_id=str(bot.id),
        platform_user_id="U1",
        platform_chat_id="C1:1.0",
        value=press_value(prompt.id.hex, choice),
        message_id="9.9",
    )


class _Patched:
    """Everything a press reaches for, patched; what was said and settled recorded."""

    def __init__(self, *, bot: MagicMock, prompt: MagicMock | None, role: str | None) -> None:
        self.adapter = MagicMock()
        self.adapter.send_message = AsyncMock()
        self.adapter.send_prompt = AsyncMock()
        self.adapter.acknowledge = AsyncMock()
        self.adapter.settle_prompt = AsyncMock()
        identity = MagicMock(id=uuid.uuid4(), user_id=USER) if role is not None else None
        membership = MagicMock(role=role) if role is not None else None
        self.answered: list[dict[str, Any]] = []

        async def answer(db: Any, *, prompt: MagicMock, value: dict[str, Any]) -> MagicMock:
            prompt.answer = value
            prompt.answered_at = "now"
            self.answered.append(value)
            return prompt

        self.patches = [
            patch(f"{_MODULE}.get_adapter", return_value=self.adapter),
            patch(f"{_MODULE}.unseal_bot_token", return_value="xoxb"),
            patch(f"{_MODULE}.channel_bot_repo.get_for_inbound", new=AsyncMock(return_value=bot)),
            patch(f"{_MODULE}.channel_prompt_repo.claim", new=AsyncMock(return_value=prompt)),
            patch(f"{_MODULE}.channel_prompt_repo.answer", new=answer),
            patch(
                f"{_MODULE}.channel_identity_repo.get_by_platform_user",
                new=AsyncMock(return_value=identity),
            ),
            patch(f"{_MODULE}.member_repo.get_active", new=AsyncMock(return_value=membership)),
        ]

    def __enter__(self) -> _Patched:
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in reversed(self.patches):
            p.stop()

    def said(self) -> list[str]:
        return [call.args[1].text for call in self.adapter.send_message.await_args_list]


def _segment(output: str = "Sent.") -> MagicMock:
    return MagicMock(output=output)


class TestPressValues:
    def test_a_value_round_trips_and_fits_a_telegram_button(self):
        prompt_id = uuid.uuid4().hex
        assert read_press(press_value(prompt_id, 3)) == (prompt_id, 3)
        assert read_press(press_value(prompt_id, None)) == (prompt_id, None)
        assert len(press_value(prompt_id, 9).encode()) <= 64

    @pytest.mark.parametrize("value", ["other:abc", "aos:abc:x", "aos:abc:"])
    def test_anything_else_is_not_a_press(self, value: str):
        assert read_press(value) is None


class _Plain(ChannelAdapter):
    """A platform with no buttons - the base class's own behaviour."""

    platform = "plain"

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []

    async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None:
        self.sent.append(msg)

    async def start_polling(self, bot_id: str, bot_token: str) -> None: ...
    async def stop_polling(self, bot_id: str) -> None: ...
    async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool: ...
    async def delete_webhook(self, bot_token: str) -> bool: ...
    def verify_webhook_signature(self, headers: Any, secret: str, body: Any = None) -> bool: ...
    def parse_incoming(self, raw_payload: Any, bot_id: str) -> None: ...


class TestAPlatformWithNoButtons:
    async def test_writes_the_choices_out_and_settles_nothing(self):
        adapter = _Plain()
        prompt = PromptMessage(platform_chat_id="c", text="Approve it?", choices=[])
        prompt.choices = [MagicMock(label="Approve"), MagicMock(label="Reject")]

        await adapter.send_prompt("t", prompt)
        await adapter.acknowledge("t", MagicMock())
        await adapter.settle_prompt("t", MagicMock(), "Approved.")

        assert adapter.sent[0].text == "Approve it?\n- Approve\n- Reject"


class TestOffering:
    async def test_each_approval_and_each_question_is_its_own_message(self):
        bot = _bot()
        run = MagicMock(id=RUN, user_id=USER)
        approval = ParkedCall(
            id=uuid.uuid4(), tool_call_id="c1", tool_name="send_email", tool_args={"to": "a@b.c"}
        )
        asked = ParkedQuestion(
            tool_call_id="ask-1",
            questions=[
                QuestionItem(
                    question="How formal?",
                    header="Tone",
                    options=[QuestionChoice(label="Formal"), QuestionChoice(label="Casual")],
                ),
                QuestionItem(question="Anything else?", options=[QuestionChoice(label="No")]),
            ],
        )
        service = ChannelPrompts(MagicMock())
        created: list[dict[str, Any]] = []

        async def create(db: Any, **fields: Any) -> MagicMock:
            created.append(fields)
            return MagicMock(id=uuid.uuid4(), **fields)

        with _Patched(bot=bot, prompt=None, role="member") as env:
            with (
                patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
                patch(f"{_MODULE}.channel_prompt_repo.create", new=create),
                patch.object(
                    service.runner, "parked_calls", new=AsyncMock(return_value=[approval])
                ),
                patch.object(
                    service.runner, "parked_questions", new=AsyncMock(return_value=[asked])
                ),
            ):
                await service.offer(bot, platform="slack", platform_chat_id="C1:1.0", run_id=RUN)

            sent = [call.args[1] for call in env.adapter.send_prompt.await_args_list]

        assert [fields["kind"] for fields in created] == [APPROVAL, QUESTION, QUESTION]
        assert "`send_email`" in sent[0].text and '"to": "a@b.c"' in sent[0].text
        assert [(choice.label, choice.style) for choice in sent[0].choices] == [
            ("Approve", "primary"),
            ("Reject", "danger"),
        ]
        assert sent[1].text == "*Tone* - How formal?"
        assert [choice.label for choice in sent[1].choices] == ["Formal", "Casual", SKIP]
        assert sent[2].text == "Anything else?"
        assert sent[0].bot_id == str(bot.id)

    async def test_a_run_gone_or_a_failure_offers_nothing_and_raises_nothing(self):
        bot = _bot()
        service = ChannelPrompts(MagicMock())
        with _Patched(bot=bot, prompt=None, role="member") as env:
            with patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=None)):
                await service.offer(bot, platform="slack", platform_chat_id="C1", run_id=RUN)
            with patch(
                f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(side_effect=RuntimeError)
            ):
                await service.offer(bot, platform="slack", platform_chat_id="C1", run_id=RUN)

            env.adapter.send_prompt.assert_not_awaited()

    async def test_a_long_argument_list_is_cut_short(self):
        bot = _bot()
        service = ChannelPrompts(MagicMock())
        approval = ParkedCall(
            id=uuid.uuid4(), tool_call_id="c1", tool_name="write", tool_args={"body": "x" * 900}
        )
        with _Patched(bot=bot, prompt=None, role="member") as env:
            with (
                patch(
                    f"{_MODULE}.agent_run_repo.get_run",
                    new=AsyncMock(return_value=MagicMock(id=RUN, user_id=None)),
                ),
                patch(
                    f"{_MODULE}.channel_prompt_repo.create",
                    new=AsyncMock(
                        return_value=MagicMock(
                            id=uuid.uuid4(), kind=APPROVAL, choices=["Approve", "Reject"]
                        )
                    ),
                ),
                patch.object(
                    service.runner, "parked_calls", new=AsyncMock(return_value=[approval])
                ),
                patch.object(service.runner, "parked_questions", new=AsyncMock(return_value=[])),
            ):
                await service.offer(bot, platform="slack", platform_chat_id="C1", run_id=RUN)

            text = env.adapter.send_prompt.await_args.args[1].text
        assert "…" in text and len(text) < 450


class TestPressingAnApproval:
    async def _press(
        self, *, choice: int | None, role: str | None = "admin", pending: bool = False, prompt=None
    ):
        bot = _bot()
        prompt = prompt or _prompt()
        service = ChannelPrompts(MagicMock())
        approvals = [MagicMock(status=ApprovalStatus.PENDING.value)] if pending else []
        with _Patched(bot=bot, prompt=prompt, role=role) as env:
            with (
                patch(f"{_MODULE}.ApprovalService") as approvals_service,
                patch(
                    f"{_MODULE}.agent_run_repo.list_approvals_for_run",
                    new=AsyncMock(return_value=approvals),
                ),
                patch.object(service.runner, "resume", new=AsyncMock(return_value=_segment())),
                patch.object(service, "offer", new=AsyncMock()) as offered,
            ):
                approvals_service.return_value.decide = AsyncMock()
                resume = service.runner.resume
                await service.press(_press(prompt, choice, bot))
            return env, approvals_service.return_value.decide, resume, offered

    async def test_approving_decides_continues_and_says_what_it_said(self):
        env, decide, resume, offered = await self._press(choice=0)

        assert decide.await_args.kwargs == {"approved": True}
        resume.assert_awaited_once()
        assert env.said() == ["Sent."]
        assert env.adapter.settle_prompt.await_args.args[2] == "Approved."
        offered.assert_awaited_once()
        env.adapter.acknowledge.assert_awaited_once()

    async def test_rejecting_is_recorded_as_rejected(self):
        env, decide, _resume, _offered = await self._press(choice=1)

        assert decide.await_args.kwargs == {"approved": False}
        assert env.adapter.settle_prompt.await_args.args[2] == "Rejected."

    async def test_the_run_waits_while_another_call_is_still_undecided(self):
        env, _decide, resume, _offered = await self._press(choice=0, pending=True)

        resume.assert_not_awaited()
        assert env.said() == []
        env.adapter.settle_prompt.assert_awaited_once()

    @pytest.mark.security
    async def test_somebody_who_may_not_approve_is_refused(self):
        env, decide, _resume, _offered = await self._press(choice=0, role="viewer")

        decide.assert_not_awaited()
        assert env.said() == [NOT_YOURS]

    @pytest.mark.security
    async def test_an_unlinked_presser_is_told_to_link(self):
        env, decide, _resume, _offered = await self._press(choice=0, role=None)

        decide.assert_not_awaited()
        assert env.said() == [LINK_FIRST]

    async def test_a_prompt_already_answered_is_not_answered_again(self):
        env, decide, _resume, _offered = await self._press(
            choice=0, prompt=_prompt(answered_at="earlier")
        )

        decide.assert_not_awaited()
        assert env.said() == [ALREADY]


class TestPressingAQuestion:
    async def _press(self, *, choice: int | None, siblings: list[MagicMock], answer_raises=None):
        bot = _bot()
        prompt = siblings[0]
        service = ChannelPrompts(MagicMock())
        with _Patched(bot=bot, prompt=prompt, role="member") as env:
            with (
                patch(
                    f"{_MODULE}.channel_prompt_repo.for_call", new=AsyncMock(return_value=siblings)
                ),
                patch.object(
                    service.runner,
                    "answer",
                    new=AsyncMock(
                        return_value=_segment("Casual it is."), side_effect=answer_raises
                    ),
                ),
                patch.object(service, "offer", new=AsyncMock()),
            ):
                answer = service.runner.answer
                await service.press(_press(prompt, choice, bot))
            return env, answer

    async def test_the_last_question_answered_answers_the_call(self):
        env, answer = await self._press(choice=1, siblings=[_prompt(QUESTION)])

        assert answer.await_args.args[2] == {"ask-1": [{"selected": ["Casual"]}]}
        assert env.said() == ["Casual it is."]
        assert env.adapter.settle_prompt.await_args.args[2] == "Answered: Casual"

    async def test_a_call_waits_for_the_rest_of_its_questions(self):
        env, answer = await self._press(
            choice=0, siblings=[_prompt(QUESTION), _prompt(QUESTION, question_index=1)]
        )

        answer.assert_not_awaited()
        assert env.said() == []

    async def test_skip_is_an_answer_too(self):
        env, answer = await self._press(choice=None, siblings=[_prompt(QUESTION)])

        assert answer.await_args.args[2] == {"ask-1": [{"skipped": True}]}
        assert env.adapter.settle_prompt.await_args.args[2] == "Skipped."

    async def test_a_refusal_from_the_run_is_said_in_the_chat(self):
        env, _answer = await self._press(
            choice=0,
            siblings=[_prompt(QUESTION)],
            answer_raises=BadRequestError(message="This run is not waiting for an answer"),
        )

        assert env.said() == ["This run is not waiting for an answer"]

    async def test_an_empty_continuation_still_says_something(self):
        bot = _bot()
        prompt = _prompt(QUESTION)
        service = ChannelPrompts(MagicMock())
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(f"{_MODULE}.channel_prompt_repo.for_call", new=AsyncMock(return_value=[prompt])),
            patch.object(service.runner, "answer", new=AsyncMock(return_value=_segment(""))),
            patch.object(service, "offer", new=AsyncMock()),
        ):
            await service.press(_press(prompt, 0, bot))

        assert env.said() == ["Done."]


class TestPressesThatNameNothing:
    @pytest.mark.parametrize("value", ["not-ours", "aos:not-a-uuid:0"])
    async def test_a_value_that_is_no_prompt_does_nothing(self, value: str):
        bot = _bot()
        with _Patched(bot=bot, prompt=None, role="member") as env:
            press = IncomingPress(
                platform="slack",
                bot_id=str(bot.id),
                platform_user_id="U",
                platform_chat_id="C",
                value=value,
            )
            await ChannelPrompts(MagicMock()).press(press)

        env.adapter.acknowledge.assert_not_awaited()

    @pytest.mark.security
    async def test_a_prompt_another_bot_offered_is_not_found(self):
        """`claim` is scoped to the bot the press arrived on."""
        bot = _bot()
        with _Patched(bot=bot, prompt=None, role="member") as env:
            await ChannelPrompts(MagicMock()).press(_press(_prompt(), 0, bot))

        env.adapter.acknowledge.assert_not_awaited()

    async def test_a_press_on_an_inactive_bot_does_nothing(self):
        bot = _bot()
        bot.is_active = False
        with _Patched(bot=bot, prompt=_prompt(), role="member") as env:
            await ChannelPrompts(MagicMock()).press(_press(_prompt(), 0, bot))

        env.adapter.acknowledge.assert_not_awaited()

    async def test_a_former_member_is_told_to_link(self):
        bot = _bot()
        prompt = _prompt()
        # Entered in order, so this patch is the one in force over `_Patched`'s.
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(f"{_MODULE}.member_repo.get_active", new=AsyncMock(return_value=None)),
        ):
            await ChannelPrompts(MagicMock()).press(_press(prompt, 0, bot))

        assert env.said() == [LINK_FIRST]
