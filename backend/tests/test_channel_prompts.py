"""Approvals and questions in a chat, as buttons (#2064, #2067, #2068).

What has to hold: a press names a stored prompt and nothing else; the presser
acts as their linked member, with their own permissions; an approval continues
the run only once nothing is left pending, and a question only once every one of
its call's questions is answered; and whatever was decided is said in the chat.
"""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.ask_user import QuestionChoice, QuestionItem
from app.core.exceptions import BadRequestError
from app.db.models.agent_run import ApprovalStatus, RunStatus
from app.db.models.channel_prompt import APPROVAL, FOLLOW_UP, QUESTION
from app.schemas.agent import ParkedCall, ParkedQuestion
from app.services.agent_runner import RunSegment
from app.services.channels.base import (
    ChannelAdapter,
    IncomingPress,
    OutgoingMessage,
    PromptMessage,
    press_value,
    read_press,
)
from app.services.channels.prompts import (
    LINK_FIRST,
    NOT_ASKED,
    NOT_YOURS,
    SKIP,
    TYPE_IT,
    ChannelPrompts,
    approval_text,
    call_action,
    call_summary,
)

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
        "multi_select": False,
    }
    return MagicMock(**{**defaults, **fields})


def _session() -> MagicMock:
    """A session whose savepoint is recorded: what a refused resume takes back."""
    savepoint = MagicMock(is_active=True, rollback=AsyncMock(), commit=AsyncMock())
    return MagicMock(begin_nested=AsyncMock(return_value=savepoint), savepoint=savepoint)


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
        self.picked: list[list[str]] = []

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
            # The run asked the person pressing, unless a test says otherwise, and
            # is parked on the one call these prompts belong to.
            patch(
                f"{_MODULE}.agent_run_repo.get_run",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=RUN,
                        user_id=USER,
                        status=RunStatus.AWAITING_ANSWER.value,
                        paused_state={"messages": [], "tool_call_ids": {}, "questions": ["ask-1"]},
                    )
                ),
            ),
            # Still open, unless a test says somebody decided it elsewhere.
            patch(
                f"{_MODULE}.agent_run_repo.get_approval",
                new=AsyncMock(return_value=MagicMock(status=ApprovalStatus.PENDING.value)),
            ),
            patch(f"{_MODULE}.agent_run_repo.claim_parked_run", new=AsyncMock(return_value=None)),
            patch(f"{_MODULE}.channel_prompt_repo.pick", new=self._pick),
        ]

    async def _pick(self, db: Any, *, prompt: MagicMock, selected: list[str]) -> MagicMock:
        prompt.answer = {"selected": selected}
        self.picked.append(selected)
        return prompt

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
    return MagicMock(output=output, tool_calls=[], settled={}, generated_files=frozenset())


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

    async def test_names_no_server_for_a_channel(self):
        assert await _Plain().channel_server("t", "c") is None


class TestOffering:
    async def test_each_approval_and_each_question_is_its_own_message(self):
        bot = _bot()
        run = MagicMock(id=RUN, user_id=USER)
        approval = ParkedCall(
            id=uuid.uuid4(),
            tool_call_id="c1",
            tool_name="gmail_send_email",
            tool_args={"to": "a@b.c", "subject": "", "cc": []},
        )
        asked = ParkedQuestion(
            tool_call_id="ask-1",
            questions=[
                QuestionItem(
                    question="How formal?",
                    header="Tone",
                    options=[QuestionChoice(label="Formal"), QuestionChoice(label="Casual")],
                ),
                QuestionItem(
                    question="Anything else?",
                    options=[QuestionChoice(label="No")],
                    allow_custom=False,
                ),
                # Nothing to press but Skip: the only answer is a typed one.
                QuestionItem(question="Which city?", allow_custom=False),
            ],
        )
        service = ChannelPrompts(_session())
        created: list[dict[str, Any]] = []

        async def create(db: Any, **fields: Any) -> MagicMock:
            created.append(fields)
            return MagicMock(id=uuid.uuid4(), **{"multi_select": False, **fields})

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

        assert [fields["kind"] for fields in created] == [APPROVAL, QUESTION, QUESTION, QUESTION]
        assert [fields.get("allow_custom") for fields in created[1:]] == [True, False, True]
        # What it wants to do and what about, in the agent's voice - no tool id,
        # no JSON, no empty fields.
        assert sent[0].text == "I need your approval to *send email in Gmail*: “a@b.c”"
        assert [(choice.label, choice.style) for choice in sent[0].choices] == [
            ("Approve", "primary"),
            ("Reject", "danger"),
        ]
        assert sent[1].text == f"*Tone* - How formal?\n{TYPE_IT}"
        assert [choice.label for choice in sent[1].choices] == ["Formal", "Casual", SKIP]
        assert sent[2].text == "Anything else?"
        assert sent[3].text == f"Which city?\n{TYPE_IT}"
        assert sent[0].bot_id == str(bot.id)

    async def test_a_question_the_chat_never_got_leaves_no_row_behind(self):
        """Codex on #2062: a call is answered once all its rows are, so an
        undelivered one held the run forever."""
        bot = _bot()
        asked = ParkedQuestion(
            tool_call_id="ask-1",
            questions=[
                QuestionItem(question="One?", options=[QuestionChoice(label="A")]),
                QuestionItem(
                    question="Two?", options=[QuestionChoice(label="B")], multi_select=True
                ),
            ],
        )
        service = ChannelPrompts(_session())
        rows: list[MagicMock] = []

        async def create(db: Any, **fields: Any) -> MagicMock:
            rows.append(MagicMock(id=uuid.uuid4(), **fields))
            return rows[-1]

        with _Patched(bot=bot, prompt=None, role="member") as env:
            env.adapter.send_prompt = AsyncMock(side_effect=[None, RuntimeError("slack down")])
            with (
                patch(f"{_MODULE}.channel_prompt_repo.create", new=create),
                patch(f"{_MODULE}.channel_prompt_repo.delete", new=AsyncMock()) as delete,
                patch.object(service.runner, "parked_calls", new=AsyncMock(return_value=[])),
                patch.object(
                    service.runner, "parked_questions", new=AsyncMock(return_value=[asked])
                ),
            ):
                await service.offer(bot, platform="slack", platform_chat_id="C1", run_id=RUN)
            second = env.adapter.send_prompt.await_args_list[1].args[1]

        delete.assert_awaited_once_with(service.db, rows)
        assert [choice.label for choice in second.choices] == ["B", "Done", SKIP]

    async def test_a_run_gone_or_a_failure_offers_nothing_and_raises_nothing(self):
        bot = _bot()
        service = ChannelPrompts(_session())
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
        service = ChannelPrompts(_session())
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


class TestTheApprovalReadsAsARequest:
    def test_a_built_in_tool_is_named_in_words(self):
        assert call_action("write_memory") == "write memory"

    def test_a_server_that_names_itself_twice_is_named_once(self):
        assert call_action("notion_notion-search") == "search in Notion"

    def test_a_name_with_nothing_after_its_prefix_is_kept(self):
        assert call_action("notion_notion") == "notion notion"

    def test_the_telling_argument_leads_and_a_call_about_nothing_says_so(self):
        assert approval_text("execute", {"command": "ls -la\nrm x", "cwd": "/w"}) == (
            "I need your approval to *execute*: “ls -la”"
        )
        assert approval_text("clock_now", {"zone": ""}) == "I need your approval to *now in Clock*."
        assert call_summary({"size": 3}) is None

    def test_the_account_is_named_when_the_call_has_one(self):
        assert approval_text("gmail_send", {"to": "ana@example.com"}, "Work") == (
            "I need your approval to *send in Gmail* as *Work*: “ana@example.com”"
        )


class TestPressingAnApproval:
    async def _press(
        self,
        *,
        choice: int | None,
        role: str | None = "admin",
        pending: bool = False,
        prompt=None,
        segment=None,
    ):
        bot = _bot()
        prompt = prompt or _prompt()
        service = ChannelPrompts(_session())
        approvals = [MagicMock(status=ApprovalStatus.PENDING.value)] if pending else []
        with _Patched(bot=bot, prompt=prompt, role=role) as env:
            with (
                patch(f"{_MODULE}.ApprovalService") as approvals_service,
                patch(
                    f"{_MODULE}.agent_run_repo.list_approvals_for_run",
                    new=AsyncMock(return_value=approvals),
                ),
                patch.object(
                    service.runner, "resume", new=AsyncMock(return_value=segment or _segment())
                ),
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
        assert env.said() == []
        env.adapter.acknowledge.assert_awaited_once()
        env.adapter.settle_prompt.assert_not_awaited()


class TestSettlingAPress:
    """The savepoint around a press: kept when the run continues, taken back when
    it refuses, and left alone once the resume committed it away."""

    @pytest.fixture(autouse=True)
    def _lock(self):
        with patch(
            f"{_MODULE}.agent_run_repo.claim_parked_run",
            new=AsyncMock(return_value=MagicMock(paused_state=None)),
        ) as lock:
            self.lock = lock
            yield

    async def test_the_run_is_held_before_anything_is_written(self):
        """Codex on #2062: two presses on one run's questions each saw the other
        unanswered, and neither continued the run."""
        service = ChannelPrompts(_session())
        prompt = _prompt(QUESTION)
        ctx = MagicMock()

        with patch.object(service, "_answer", new=AsyncMock(return_value=None)):
            await service._settle(ctx, prompt, 0)

        self.lock.assert_awaited_once_with(
            service.db, prompt.run_id, organization_id=ctx.organization_id
        )

    @pytest.mark.parametrize("refused", [False, True])
    async def test_a_resume_that_committed_leaves_what_it_wrote(self, refused: bool):
        session = _session()
        session.savepoint.is_active = False
        service = ChannelPrompts(session)
        outcome = AsyncMock(side_effect=BadRequestError(message="no")) if refused else AsyncMock()

        with patch.object(service, "_answer", new=outcome):
            if refused:
                with pytest.raises(BadRequestError):
                    await service._settle(MagicMock(), _prompt(QUESTION), 0)
            else:
                await service._settle(MagicMock(), _prompt(QUESTION), 0)

        session.savepoint.rollback.assert_not_awaited()
        session.savepoint.commit.assert_not_awaited()

    async def test_a_run_that_continues_keeps_the_press(self):
        session = _session()
        service = ChannelPrompts(session)

        with patch.object(service, "_answer", new=AsyncMock(return_value=None)):
            await service._settle(MagicMock(), _prompt(QUESTION), 0)

        session.savepoint.commit.assert_awaited_once()


class TestPressingAQuestion:
    async def _press(
        self,
        *,
        choice: int | None,
        siblings: list[MagicMock],
        answer_raises=None,
        parked: list[str] | None = None,
        others: dict[str, list[MagicMock]] | None = None,
    ):
        bot = _bot()
        prompt = siblings[0]
        service = ChannelPrompts(_session())
        self.session = service.db
        calls = {"ask-1": siblings, **(others or {})}
        run = MagicMock(
            id=RUN,
            user_id=USER,
            status=RunStatus.AWAITING_ANSWER.value,
            paused_state={"messages": [], "tool_call_ids": {}, "questions": parked or ["ask-1"]},
        )
        with _Patched(bot=bot, prompt=prompt, role="member") as env:
            with (
                patch(
                    f"{_MODULE}.channel_prompt_repo.for_call",
                    new=AsyncMock(side_effect=lambda db, run_id, tool_call_id: calls[tool_call_id]),
                ),
                patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=run)),
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

    async def test_somebody_else_pressing_writes_nothing(self):
        """Codex on #2062: a colleague's press in a shared channel used the question up."""
        bot = _bot()
        prompt = _prompt(QUESTION)
        service = ChannelPrompts(_session())
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(
                f"{_MODULE}.agent_run_repo.get_run",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=RUN, user_id=uuid.uuid4(), status=RunStatus.AWAITING_ANSWER.value
                    )
                ),
            ),
        ):
            await service.press(_press(prompt, 0, bot))

        assert env.answered == []
        assert env.said() == [NOT_ASKED]

    async def test_a_multi_select_collects_choices_until_done(self):
        prompt = _prompt(QUESTION, multi_select=True)
        env, answer = await self._press(choice=0, siblings=[prompt])
        assert env.picked == [["Formal"]]
        assert env.said() == ["Picked: Formal. Press Done when that is all."]
        answer.assert_not_awaited()
        env.adapter.settle_prompt.assert_not_awaited()

        env, answer = await self._press(choice=1, siblings=[prompt])
        assert env.picked == [["Formal", "Casual"]]
        env, answer = await self._press(choice=0, siblings=[prompt])
        assert env.picked == [["Casual"]]
        await self._press(choice=0, siblings=[prompt])

        env, answer = await self._press(choice=len(prompt.choices), siblings=[prompt])
        assert answer.await_args.args[2] == {"ask-1": [{"selected": ["Casual", "Formal"]}]}
        assert env.adapter.settle_prompt.await_args.args[2] == "Answered: Casual, Formal"

    async def test_done_with_nothing_picked_is_a_skip(self):
        prompt = _prompt(QUESTION, multi_select=True)
        await self._press(choice=0, siblings=[prompt])
        env, _ = await self._press(choice=0, siblings=[prompt])
        assert env.said() == ["Nothing picked yet. Choose one or more, then press Done."]

        env, answer = await self._press(choice=2, siblings=[prompt])
        assert answer.await_args.args[2] == {"ask-1": [{"skipped": True}]}

    async def test_the_last_question_answered_answers_the_call(self):
        env, answer = await self._press(choice=1, siblings=[_prompt(QUESTION)])

        assert answer.await_args.args[2] == {"ask-1": [{"selected": ["Casual"]}]}
        assert env.said() == ["Casual it is."]
        assert env.adapter.settle_prompt.await_args.args[2] == "Answered: Casual"

    async def test_the_run_waits_for_every_call_it_asked_through(self):
        """Codex on #2062: the first call fully answered resumed the run, and the
        other call's questions, already posted, were answered as declined."""
        env, answer = await self._press(
            choice=1,
            siblings=[_prompt(QUESTION)],
            parked=["ask-1", "ask-2"],
            others={"ask-2": [_prompt(QUESTION, tool_call_id="ask-2")]},
        )

        answer.assert_not_awaited()

    async def test_a_call_the_chat_was_never_shown_is_left_to_the_runner(self):
        """Its prompts were taken back when they could not be sent; the chat cannot
        answer it, so it is not waited for - the runner declines it."""
        env, answer = await self._press(
            choice=1, siblings=[_prompt(QUESTION)], parked=["ask-1", "ask-2"], others={"ask-2": []}
        )

        assert answer.await_args.args[2] == {"ask-1": [{"selected": ["Casual"]}]}

    async def test_a_run_no_longer_parked_is_asked_and_refuses(self):
        """Nothing to collect: the runner is asked and says the run is not waiting."""
        bot = _bot()
        prompt = _prompt(QUESTION)
        service = ChannelPrompts(_session())
        gone = MagicMock(id=RUN, user_id=USER, paused_state=None)
        refusal = BadRequestError(message="This run is not waiting for an answer")
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(f"{_MODULE}.agent_run_repo.get_run", new=AsyncMock(return_value=gone)),
            patch.object(service.runner, "answer", new=AsyncMock(side_effect=refusal)) as answer,
        ):
            await service.press(_press(prompt, 0, bot))

        assert answer.await_args.args[2] == {}
        assert env.said() == ["This run is not waiting for an answer"]

    async def test_every_call_is_answered_together_once_the_last_one_is(self):
        other = _prompt(QUESTION, tool_call_id="ask-2", answer={"answer": "Kraków"})
        env, answer = await self._press(
            choice=1,
            siblings=[_prompt(QUESTION)],
            parked=["ask-1", "ask-2"],
            others={"ask-2": [other]},
        )

        assert answer.await_args.args[2] == {
            "ask-1": [{"selected": ["Casual"]}],
            "ask-2": [{"answer": "Kraków"}],
        }

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
        # The answer and the answered mark are taken back, so the question can be
        # pressed again once the run can take it.
        self.session.savepoint.rollback.assert_awaited_once()
        self.session.savepoint.commit.assert_not_awaited()

    async def test_an_empty_continuation_still_says_something(self):
        bot = _bot()
        prompt = _prompt(QUESTION)
        service = ChannelPrompts(_session())
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(f"{_MODULE}.channel_prompt_repo.for_call", new=AsyncMock(return_value=[prompt])),
            patch.object(service.runner, "answer", new=AsyncMock(return_value=_segment(""))),
            patch.object(service, "offer", new=AsyncMock()),
        ):
            await service.press(_press(prompt, 0, bot))

        assert env.said() == ["Done."]


class TestTypingAnAnswer:
    """A question that takes words is answered by the person's next message (Codex on #2062)."""

    async def _reply(
        self,
        *,
        prompt: MagicMock | None,
        siblings: list[MagicMock] | None = None,
        role: str | None = "member",
        text: str = "Kraków, please",
        answer_raises: Exception | None = None,
        segment=None,
    ) -> tuple[bool, _Patched, AsyncMock, AsyncMock]:
        bot = _bot()
        service = ChannelPrompts(_session())
        self.session = service.db
        claim = AsyncMock(return_value=prompt)
        with _Patched(bot=bot, prompt=None, role=role) as env:
            with (
                patch(f"{_MODULE}.channel_prompt_repo.claim_typed", new=claim),
                patch(
                    f"{_MODULE}.channel_prompt_repo.for_call",
                    new=AsyncMock(return_value=siblings or [prompt]),
                ),
                patch.object(
                    service.runner,
                    "answer",
                    new=AsyncMock(
                        return_value=segment or _segment("Kraków it is."), side_effect=answer_raises
                    ),
                ),
                patch.object(service, "offer", new=AsyncMock()),
            ):
                answer = service.runner.answer
                taken = await service.reply(
                    bot,
                    platform="slack",
                    platform_chat_id="C1:1.0",
                    platform_user_id="U1",
                    text=text,
                )
            return taken, env, answer, claim

    async def test_the_message_answers_the_question_and_continues_the_run(self):
        taken, env, answer, claim = await self._reply(prompt=_prompt(QUESTION, allow_custom=True))

        assert taken
        assert claim.await_args.kwargs["user_id"] == USER
        assert answer.await_args.args[2] == {"ask-1": [{"answer": "Kraków, please"}]}
        assert env.said() == ["Kraków it is."]

    async def test_with_questions_still_open_it_says_what_it_took(self):
        prompt = _prompt(QUESTION, allow_custom=True)
        taken, env, answer, _ = await self._reply(
            prompt=prompt, siblings=[prompt, _prompt(QUESTION, question_index=1)]
        )

        assert taken
        answer.assert_not_awaited()
        assert env.said() == ["Answered: Kraków, please"]

    async def test_a_refusal_is_said_and_the_answer_taken_back(self):
        taken, env, _, _ = await self._reply(
            prompt=_prompt(QUESTION, allow_custom=True),
            answer_raises=BadRequestError(message="This run is not waiting for an answer"),
        )

        assert taken
        assert env.said() == ["This run is not waiting for an answer"]
        self.session.savepoint.rollback.assert_awaited_once()

    @pytest.mark.parametrize(
        ("role", "prompt", "text"),
        [
            (None, _prompt(QUESTION, allow_custom=True), "hi"),
            ("member", None, "hi"),
            ("member", _prompt(QUESTION, allow_custom=True), "   "),
        ],
        ids=["unlinked", "nothing-asked", "blank"],
    )
    async def test_otherwise_the_message_is_a_turn(
        self, role: str | None, prompt: MagicMock | None, text: str
    ):
        taken, env, answer, _ = await self._reply(prompt=prompt, role=role, text=text)

        assert not taken
        answer.assert_not_awaited()
        assert env.said() == []


class TestAPressThatLostTheRace:
    """A console decision that lands while a press holds the prompt row.

    `settle_open` skips a row a press holds, so the press is what has to close it
    once it finds the request decided elsewhere. A refusal for any other reason
    leaves the buttons for whoever may use them.
    """

    async def _approval(self, *, approval_status: str, decide_raises: Exception, role="admin"):
        bot = _bot()
        prompt = _prompt()
        service = ChannelPrompts(_session())
        with (
            _Patched(bot=bot, prompt=prompt, role=role) as env,
            patch(
                f"{_MODULE}.agent_run_repo.get_approval",
                new=AsyncMock(return_value=MagicMock(status=approval_status)),
            ),
            patch(f"{_MODULE}.ApprovalService") as approvals_service,
        ):
            approvals_service.return_value.decide = AsyncMock(side_effect=decide_raises)
            await service.press(_press(prompt, 0, bot))
        return env, prompt

    @pytest.mark.security
    async def test_an_approval_decided_elsewhere_settles_the_row_and_says_so(self):
        gone = BadRequestError(message="This request was already approved")
        env, prompt = await self._approval(
            approval_status=ApprovalStatus.APPROVED.value, decide_raises=gone
        )

        assert env.answered == [{"settled": "decided"}]
        assert prompt.answered_at is not None
        assert env.said() == ["This request was already approved"]

    async def test_a_later_press_is_told_it_is_answered_and_changes_nothing(self):
        bot = _bot()
        prompt = _prompt()
        service = ChannelPrompts(_session())
        gone = BadRequestError(message="This request was already approved")
        with (
            _Patched(bot=bot, prompt=prompt, role="admin") as env,
            patch(
                f"{_MODULE}.agent_run_repo.get_approval",
                new=AsyncMock(return_value=MagicMock(status=ApprovalStatus.APPROVED.value)),
            ),
            patch(f"{_MODULE}.ApprovalService") as approvals_service,
        ):
            approvals_service.return_value.decide = AsyncMock(side_effect=gone)
            await service.press(_press(prompt, 0, bot))
            await service.press(_press(prompt, 1, bot))

        assert approvals_service.return_value.decide.await_count == 1
        assert env.answered == [{"settled": "decided"}]
        assert env.said() == ["This request was already approved"]

    @pytest.mark.security
    async def test_a_refusal_for_another_reason_leaves_the_row_open(self):
        env, prompt = await self._approval(
            approval_status=ApprovalStatus.PENDING.value,
            decide_raises=BadRequestError(message="This approval belongs to a live voice call"),
        )

        assert env.answered == []
        assert prompt.answered_at is None

    @pytest.mark.security
    async def test_somebody_who_may_not_decide_leaves_the_row_open(self):
        env, prompt = await self._approval(
            approval_status=ApprovalStatus.PENDING.value, decide_raises=None, role="viewer"
        )

        assert env.answered == []
        assert env.said() == [NOT_YOURS]

    async def test_a_question_answered_elsewhere_settles_the_row(self):
        bot = _bot()
        prompt = _prompt(QUESTION)
        service = ChannelPrompts(_session())
        gone = BadRequestError(message="This run is not waiting for an answer")
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(
                f"{_MODULE}.agent_run_repo.get_run",
                new=AsyncMock(
                    return_value=MagicMock(id=RUN, user_id=USER, status=RunStatus.RUNNING.value)
                ),
            ),
            patch.object(service, "_answer", new=AsyncMock(side_effect=gone)),
        ):
            await service.press(_press(prompt, 0, bot))

        assert env.answered == [{"settled": "answered"}]
        assert env.said() == ["This run is not waiting for an answer"]

    async def test_a_typed_answer_to_a_question_answered_elsewhere_settles_the_row(self):
        bot = _bot()
        prompt = _prompt(QUESTION, allow_custom=True)
        service = ChannelPrompts(_session())
        gone = BadRequestError(message="This run is not waiting for an answer")
        with (
            _Patched(bot=bot, prompt=None, role="member") as env,
            patch(
                f"{_MODULE}.channel_prompt_repo.claim_typed",
                new=AsyncMock(return_value=prompt),
            ),
            patch(
                f"{_MODULE}.agent_run_repo.get_run",
                new=AsyncMock(
                    return_value=MagicMock(id=RUN, user_id=USER, status=RunStatus.RUNNING.value)
                ),
            ),
            patch.object(service, "_answer", new=AsyncMock(side_effect=gone)),
        ):
            taken = await service.reply(
                bot,
                platform="slack",
                platform_chat_id="C1:1.0",
                platform_user_id="U1",
                text="Kraków",
            )

        assert taken
        assert env.answered == [{"settled": "answered"}]

    @pytest.mark.security
    async def test_a_question_refused_to_a_colleague_stays_open(self):
        bot = _bot()
        prompt = _prompt(QUESTION)
        service = ChannelPrompts(_session())
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(
                f"{_MODULE}.agent_run_repo.get_run",
                new=AsyncMock(
                    return_value=MagicMock(
                        id=RUN, user_id=uuid.uuid4(), status=RunStatus.AWAITING_ANSWER.value
                    )
                ),
            ),
        ):
            await service.press(_press(prompt, 0, bot))

        assert env.answered == []
        assert env.said() == [NOT_ASKED]


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
            await ChannelPrompts(_session()).press(press)

        env.adapter.acknowledge.assert_not_awaited()

    @pytest.mark.security
    async def test_a_prompt_another_bot_offered_is_not_found(self):
        """`claim` is scoped to the bot the press arrived on."""
        bot = _bot()
        with _Patched(bot=bot, prompt=None, role="member") as env:
            await ChannelPrompts(_session()).press(_press(_prompt(), 0, bot))

        env.adapter.acknowledge.assert_not_awaited()

    @pytest.mark.security
    async def test_next_steps_named_as_a_prompt_answer_nothing(self):
        """Next steps are pressed through their own value; one dressed as a
        prompt's press is a value nobody was offered (#2301)."""
        bot = _bot()
        steps = _prompt(FOLLOW_UP, choices=["Make it a table"], chat_type="private")
        with _Patched(bot=bot, prompt=steps, role="member") as env:
            await ChannelPrompts(_session()).press(_press(steps, 0, bot))

        env.adapter.acknowledge.assert_not_awaited()
        assert env.answered == []

    async def test_a_press_on_an_inactive_bot_does_nothing(self):
        bot = _bot()
        bot.is_active = False
        with _Patched(bot=bot, prompt=_prompt(), role="member") as env:
            await ChannelPrompts(_session()).press(_press(_prompt(), 0, bot))

        env.adapter.acknowledge.assert_not_awaited()

    async def test_a_former_member_is_told_to_link(self):
        bot = _bot()
        prompt = _prompt()
        # Entered in order, so this patch is the one in force over `_Patched`'s.
        with (
            _Patched(bot=bot, prompt=prompt, role="member") as env,
            patch(f"{_MODULE}.member_repo.get_active", new=AsyncMock(return_value=None)),
        ):
            await ChannelPrompts(_session()).press(_press(prompt, 0, bot))

        assert env.said() == [LINK_FIRST]


class TestTheRepository:
    """The two writes the service tests stub out, against a session double."""

    async def test_pick_records_the_choices_and_leaves_it_unanswered(self):
        from app.repositories import channel_prompt as repo

        db = AsyncMock()
        db.add = MagicMock()
        prompt = SimpleNamespace(answer=None, answered_at=None)

        await repo.pick(db, prompt=prompt, selected=["Casual", "Formal"])

        assert prompt.answer == {"selected": ["Casual", "Formal"]}
        assert prompt.answered_at is None
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once_with(prompt)

    async def test_delete_removes_every_prompt_offered(self):
        from app.repositories import channel_prompt as repo

        db = AsyncMock()
        prompts = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        await repo.delete(db, prompts)

        assert [call.args[0] for call in db.delete.await_args_list] == prompts
        db.flush.assert_awaited_once()


@pytest.mark.parametrize("delivery", ["press", "reply"])
async def test_a_completed_channel_continuation_defers_buttons_after_posting_its_answer(
    monkeypatch, delivery
):
    import app.services.channels.prompts as module

    segment = SimpleNamespace(
        output="Sent.",
        tool_calls=[],
        settled={},
        generated_files=frozenset(),
        run=SimpleNamespace(
            conversation_id=None,
            id=RUN,
            status="completed",
            channel_identity_id=uuid.uuid4(),
        ),
    )
    jobs = []
    monkeypatch.setattr(module, "spawn_after_commit", lambda _db, job, **_kw: jobs.append(job))
    offer = AsyncMock()
    monkeypatch.setattr(module, "offer_after_resume", offer)
    if delivery == "press":
        env, *_ = await TestPressingAnApproval()._press(choice=0, segment=segment)
    else:
        _, env, *_ = await TestTypingAnAnswer()._reply(
            prompt=_prompt(QUESTION, allow_custom=True), segment=segment
        )
    assert env.said() == ["Sent."]
    offer.assert_not_awaited()
    assert len(jobs) == 1
    await jobs[0]
    org, run_id, bot_id, chat_id = offer.await_args.args
    assert org == ORG and run_id == RUN
    assert isinstance(bot_id, uuid.UUID)
    assert chat_id == "C1:1.0"


async def test_a_continuation_without_a_channel_identity_never_schedules_buttons(monkeypatch):
    import app.services.channels.prompts as module

    queue = MagicMock()
    monkeypatch.setattr(module, "spawn_after_commit", queue)
    run = SimpleNamespace(id=RUN, status="completed", channel_identity_id=None)
    ChannelPrompts(_session())._follow_ups(_bot(), SimpleNamespace(run=run), "C1")
    queue.assert_not_called()


class TestDelivering:
    async def test_a_press_that_continues_the_run_posts_its_answer_once(self):
        """(pinning) The press's delivery today: one answer, then what the run waits on."""
        env, _decide, _resume, offered = await TestPressingAnApproval()._press(choice=0)

        assert env.said() == ["Sent."]
        env.adapter.send_message.assert_awaited_once()
        offered.assert_awaited_once()

    async def test_deliver_posts_the_answer_then_the_prompts_then_the_next_steps(self):
        service = ChannelPrompts(_session())
        order: list[str] = []
        bot, segment = _bot(), _segment()
        with (
            patch.object(
                service, "_send_segment", new=AsyncMock(side_effect=lambda *a: order.append("send"))
            ) as send,
            patch.object(
                service, "offer", new=AsyncMock(side_effect=lambda *a, **k: order.append("offer"))
            ) as offer,
            patch.object(service, "_follow_ups", side_effect=lambda *a: order.append("steps")),
        ):
            await service.deliver(bot, platform="slack", platform_chat_id="C1", segment=segment)

        assert order == ["send", "offer", "steps"]
        send.assert_awaited_once_with(bot, "slack", "C1", segment)
        offer.assert_awaited_once_with(
            bot, platform="slack", platform_chat_id="C1", run_id=segment.run.id
        )

    def test_inherited_calls_are_the_parked_calls_named_from_the_paused_transcript(self):
        from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart

        from app.services.transcript import RecordedToolCall

        messages = ModelMessagesTypeAdapter.dump_python(
            [
                ModelResponse(
                    parts=[
                        ToolCallPart("generate_image", {"prompt": "a cat"}, tool_call_id="c1"),
                        ToolCallPart("other", {}, tool_call_id="c2"),
                    ]
                )
            ],
            mode="json",
        )
        run = SimpleNamespace(
            paused_state={"messages": messages, "tool_call_ids": {"a1": "c1"}, "questions": []}
        )

        assert ChannelPrompts.inherited_calls(run) == [  # type: ignore[arg-type]
            RecordedToolCall("c1", "generate_image", {"prompt": "a cat"})
        ]
        assert ChannelPrompts.inherited_calls(None) == []
        assert ChannelPrompts.inherited_calls(SimpleNamespace(paused_state=None)) == []  # type: ignore[arg-type]

    def test_with_inherited_puts_the_approved_calls_return_first(self):
        from dataclasses import replace

        from app.services.transcript import RecordedToolCall

        c1 = RecordedToolCall("c1", "generate_image", {})
        later = RecordedToolCall("x", "later", {})
        run = MagicMock()
        segment = RunSegment(output="", run=run, tool_calls=[later], settled={"c1": "ok"})

        merged = ChannelPrompts.with_inherited(segment, [c1])
        untouched = ChannelPrompts.with_inherited(
            RunSegment(output="", run=run, tool_calls=[later], settled={}), [c1]
        )

        assert merged.tool_calls == [replace(c1, result="ok"), later]
        assert untouched.tool_calls == [later]
