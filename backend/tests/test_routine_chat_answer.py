"""The job that posts a stored routine answer to the private chat it came from."""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ExternalServiceError
from app.services.channels import routine_answer
from app.services.channels.routine_answer import (
    ROUTINE_CHAT_PLATFORMS,
    send_routine_answer,
    settle_lost_routine_answer,
)
from app.worker.jobs import RoutineChatAnswer

pytestmark = pytest.mark.anyio

TOKEN = "123456:SECRET-bot-token"


class _World:
    """One consistent chat world; each test breaks one fact of it."""

    def __init__(self) -> None:
        org, creator = uuid4(), uuid4()
        self.org, self.creator = org, creator
        self.job = RoutineChatAnswer(
            organization_id=org,
            trigger_id=uuid4(),
            run_id=uuid4(),
            conversation_id=uuid4(),
            session_id=uuid4(),
            message_id=uuid4(),
        )
        self.trigger = SimpleNamespace(
            id=self.job.trigger_id,
            organization_id=org,
            created_by_user_id=creator,
            agent_id=uuid4(),
            name="Nightly",
            last_run_id=self.job.run_id,
            last_delivery_status="pending",
        )
        self.run_chat = uuid4()
        self.run = SimpleNamespace(
            id=self.job.run_id,
            conversation_id=self.run_chat,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        )
        self.agent = SimpleNamespace(id=self.trigger.agent_id, name="Agent")
        self.identity = SimpleNamespace(
            id=uuid4(),
            user_id=creator,
            is_active=True,
            platform="telegram",
            platform_user_id="777001",
            server_url="",
        )
        self.session = SimpleNamespace(
            id=self.job.session_id,
            bot_id=uuid4(),
            identity_id=self.identity.id,
            conversation_id=self.job.conversation_id,
            platform_chat_id="777001",
            chat_type="private",
            is_active=True,
        )
        self.bot = SimpleNamespace(
            id=self.session.bot_id,
            organization_id=org,
            platform="telegram",
            is_active=True,
            api_base_url=None,
        )
        self.conversation = SimpleNamespace(
            id=self.job.conversation_id,
            organization_id=org,
            user_id=creator,
            is_archived=False,
        )
        self.message = SimpleNamespace(
            id=self.job.message_id,
            conversation_id=self.run_chat,
            run_id=self.job.run_id,
            content="Three PRs merged.",
        )
        self.verdict = "admitted"
        self.open_sessions = 0
        self.sent_while_open: list[int] = []
        self.adapter = MagicMock()
        self.adapter.send_message = AsyncMock(side_effect=self._send)
        self.blocked = AsyncMock()
        self.resolved = AsyncMock()
        self.bot_for_org: SimpleNamespace | None = self.bot
        self.admission_subject: object = None
        self.trigger_get = AsyncMock(return_value=self.trigger)
        self.found: dict[str, bool] = {"session": True, "identity": True, "message": True}
        self.run_found = True

    async def _send(self, token: str, message: object) -> None:
        self.sent_while_open.append(self.open_sessions)
        self.sent = (token, message)

    @asynccontextmanager
    async def context(self) -> AsyncIterator[MagicMock]:
        self.open_sessions += 1
        try:
            yield MagicMock(name="db")
        finally:
            self.open_sessions -= 1


@pytest.fixture
def world() -> Iterator[_World]:
    w = _World()

    async def admission(_self: object, _db: object, run: object, incoming: object) -> object:
        w.admission_subject = (run, incoming)
        return SimpleNamespace(verdict=w.verdict, reason=w.verdict)

    with (
        patch.object(routine_answer, "get_db_context", w.context),
        patch.object(routine_answer.agent_trigger_repo, "get", new=w.trigger_get),
        patch.object(
            routine_answer.agent_run_repo,
            "get_run",
            new=AsyncMock(side_effect=lambda *_a, **_k: w.run if w.run_found else None),
        ),
        patch.object(routine_answer.agent_repo, "get", new=AsyncMock(return_value=w.agent)),
        patch.object(
            routine_answer.channel_session_repo,
            "get_by_id",
            new=AsyncMock(side_effect=lambda *_a: w.session if w.found["session"] else None),
        ),
        patch.object(
            routine_answer.channel_bot_repo,
            "get_for_org",
            new=AsyncMock(side_effect=lambda *_a, **_k: w.bot_for_org),
        ),
        patch.object(
            routine_answer.channel_identity_repo,
            "get_by_id",
            new=AsyncMock(side_effect=lambda *_a: w.identity if w.found["identity"] else None),
        ),
        patch.object(
            routine_answer.conversation_repo,
            "get_conversation_by_id",
            new=AsyncMock(return_value=w.conversation),
        ),
        patch.object(
            routine_answer.conversation_repo,
            "get_message_by_id",
            new=AsyncMock(side_effect=lambda *_a: w.message if w.found["message"] else None),
        ),
        patch("app.services.channels.router.ChannelMessageRouter.admission", admission),
        patch.object(routine_answer, "get_adapter", return_value=w.adapter),
        patch.object(routine_answer, "unseal_bot_token", return_value=TOKEN),
        patch("app.services.notifications.NotificationService.routine_blocked", w.blocked),
        patch("app.services.outcome.OutcomeService.resolve_routine_failure", w.resolved),
    ):
        yield w


def _broken(world: _World, case: str) -> None:
    """Make exactly one fact of the world false."""
    if case in ("session_missing", "identity_missing", "message_missing"):
        world.found[case.split("_")[0]] = False
    elif case == "session_inactive":
        world.session.is_active = False
    elif case == "session_now_a_group":
        world.session.chat_type = "group"
    elif case == "session_moved":
        world.session.conversation_id = uuid4()
    elif case == "bot_missing_or_other_org":
        world.bot_for_org = None
    elif case == "bot_inactive":
        world.bot.is_active = False
    elif case == "bot_sms":
        world.bot.platform = "sms"
    elif case == "conversation_archived":
        world.conversation.is_archived = True
    elif case == "conversation_other_org":
        world.conversation.organization_id = uuid4()
    elif case == "conversation_other_owner":
        world.conversation.user_id = uuid4()
    elif case == "message_other_conversation":
        world.message.conversation_id = uuid4()
    elif case == "message_other_run":
        world.message.run_id = uuid4()
    elif case == "identity_inactive":
        world.identity.is_active = False
    elif case == "creator_unlinked":
        world.trigger.created_by_user_id = None
    elif case in ("binding", "not_a_member"):
        world.verdict = "refused"
    else:  # pragma: no cover - a typo in a test
        raise AssertionError(case)


CASES = [
    "session_missing",
    "identity_missing",
    "message_missing",
    "session_inactive",
    "session_now_a_group",
    "session_moved",
    "bot_missing_or_other_org",
    "bot_inactive",
    "bot_sms",
    "conversation_archived",
    "conversation_other_org",
    "conversation_other_owner",
    "message_other_conversation",
    "message_other_run",
    "identity_inactive",
    "creator_unlinked",
    "binding",
    "not_a_member",
]


@pytest.mark.security
@pytest.mark.parametrize("case", CASES)
async def test_a_chat_that_no_longer_admits_the_creator_is_not_sent_the_answer(
    world: _World, case: str
) -> None:
    _broken(world, case)

    await send_routine_answer(world.job)

    world.adapter.send_message.assert_not_awaited()
    assert world.trigger.last_delivery_status == "unavailable"
    world.blocked.assert_awaited_once()
    assert world.blocked.await_args.kwargs["detail"] == "chat_unavailable"
    assert world.blocked.await_args.kwargs["reason"] == "delivery"
    world.resolved.assert_not_awaited()


@pytest.mark.security
async def test_another_users_identity_is_refused_even_in_the_creators_conversation(
    world: _World,
) -> None:
    world.identity.user_id = uuid4()
    world.verdict = "refused"

    await send_routine_answer(world.job)

    run, incoming = world.admission_subject
    assert run.user_id == world.creator
    assert incoming.platform_user_id == world.identity.platform_user_id
    world.adapter.send_message.assert_not_awaited()


async def test_a_removed_routine_sends_and_writes_nothing(world: _World) -> None:
    with patch.object(routine_answer.agent_trigger_repo, "get", new=AsyncMock(return_value=None)):
        await send_routine_answer(world.job)

    world.adapter.send_message.assert_not_awaited()
    world.blocked.assert_not_awaited()


@pytest.mark.security
async def test_an_already_settled_answer_is_not_sent_again(world: _World) -> None:
    world.trigger.last_delivery_status = "delivered"

    await send_routine_answer(world.job)

    world.adapter.send_message.assert_not_awaited()
    world.resolved.assert_not_awaited()


async def test_the_answer_is_posted_to_the_private_chat_with_the_bots_current_token_then_reads_delivered(
    world: _World,
) -> None:
    await send_routine_answer(world.job)

    token, message = world.sent
    assert token == TOKEN
    assert message.platform_chat_id == "777001"
    # The fire's answer from its own chat, under the routine's name as in the console.
    assert message.text == "**Nightly**\n\nThree PRs merged."
    assert world.trigger.last_delivery_status == "delivered"
    world.resolved.assert_awaited_once()
    assert world.resolved.await_args.kwargs["reason"] == "delivery"
    world.blocked.assert_not_awaited()
    assert world.trigger_get.await_args_list[-1].kwargs["for_update"] is True


async def test_the_creator_is_judged_by_the_same_admission_as_a_run(world: _World) -> None:
    await send_routine_answer(world.job)

    run, incoming = world.admission_subject
    assert run.organization_id == world.org
    assert run.surface == "telegram"
    assert run.conversation_id == world.job.conversation_id
    assert run.channel_identity_id == world.identity.id
    assert run.agent_id == world.trigger.agent_id
    assert run.initiated_by_publisher_fallback is False
    assert run.user_id == world.creator
    assert incoming.chat_type == "private"
    assert incoming.bot_id == str(world.bot.id)


async def test_a_matrix_identity_carries_its_server_into_the_admission(world: _World) -> None:
    world.bot.platform = "matrix"
    world.identity.platform = "matrix"
    world.identity.server_url = "https://matrix.example"

    await send_routine_answer(world.job)

    assert world.admission_subject[1].raw == {"server_url": "https://matrix.example"}


async def test_no_session_is_open_while_the_platform_is_called(world: _World) -> None:
    await send_routine_answer(world.job)

    assert world.sent_while_open == [0]


@pytest.mark.security
async def test_a_send_for_an_older_fire_sends_but_never_overwrites_the_newer_status(
    world: _World,
) -> None:
    async def newer_fire(*_a: object, **_k: object) -> None:
        world.trigger.last_run_id = uuid4()

    world.adapter.send_message = AsyncMock(side_effect=newer_fire)

    await send_routine_answer(world.job)

    world.adapter.send_message.assert_awaited_once()
    assert world.trigger.last_delivery_status == "pending"
    world.resolved.assert_not_awaited()


@pytest.mark.security
async def test_a_platform_failure_is_retried_with_no_platform_text_in_the_error(
    world: _World, caplog: pytest.LogCaptureFixture
) -> None:
    world.adapter.send_message = AsyncMock(side_effect=RuntimeError(f"bad url bot{TOKEN}/send"))

    with caplog.at_level(logging.ERROR), pytest.raises(ExternalServiceError) as raised:
        await send_routine_answer(world.job)

    assert TOKEN not in str(raised.value)
    assert TOKEN not in repr(raised.value.details)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert any(r.message == "routine_chat_answer_failed" for r in caplog.records)
    assert world.trigger.last_delivery_status == "pending"


@pytest.mark.parametrize("why", ["a failure", "cancelled", "dead"])
async def test_an_ended_send_reads_unavailable_and_tells_the_owner(world: _World, why: str) -> None:
    await settle_lost_routine_answer(world.job, why)

    assert world.trigger.last_delivery_status == "unavailable"
    assert world.trigger_get.await_args_list[-1].kwargs["for_update"] is True
    world.blocked.assert_awaited_once()
    assert world.blocked.await_args.kwargs["name"] == "Nightly"
    world.adapter.send_message.assert_not_awaited()


@pytest.mark.parametrize("status", ["delivered", "unavailable"])
async def test_the_settler_leaves_a_delivered_or_settled_status_alone(
    world: _World, status: str
) -> None:
    world.trigger.last_delivery_status = status

    await settle_lost_routine_answer(world.job, "dead")

    assert world.trigger.last_delivery_status == status
    world.blocked.assert_not_awaited()


async def test_the_settler_leaves_a_newer_fires_status_alone(world: _World) -> None:
    world.trigger.last_run_id = uuid4()

    await settle_lost_routine_answer(world.job, "dead")

    assert world.trigger.last_delivery_status == "pending"
    world.blocked.assert_not_awaited()


async def test_the_settler_ignores_a_removed_routine(world: _World) -> None:
    with patch.object(routine_answer.agent_trigger_repo, "get", new=AsyncMock(return_value=None)):
        await settle_lost_routine_answer(world.job, "dead")

    world.blocked.assert_not_awaited()


def test_the_chat_platforms_are_the_six_that_chat() -> None:
    assert {
        "telegram",
        "slack",
        "mattermost",
        "teams",
        "discord",
        "matrix",
    } == ROUTINE_CHAT_PLATFORMS


async def test_the_worker_runs_and_settles_routine_chat_answers() -> None:
    from app.worker import handlers, jobs

    assert jobs.ROUTINE_CHAT_ANSWER.kind in handlers.production()
    assert jobs.ROUTINE_CHAT_ANSWER.kind in jobs.TASKS
    with patch("app.worker.tasks.channel_tasks.settle_lost_routine_answer", new=AsyncMock()) as s:
        handlers._settlers.cache_clear()
        payload = RoutineChatAnswer(
            organization_id=uuid4(),
            trigger_id=uuid4(),
            run_id=uuid4(),
            conversation_id=uuid4(),
            session_id=uuid4(),
            message_id=uuid4(),
        )
        await handlers.settle_ended(
            jobs.ROUTINE_CHAT_ANSWER.kind, jobs.ROUTINE_CHAT_ANSWER.dump(payload), "dead"
        )
        handlers._settlers.cache_clear()
    s.assert_awaited_once()
    assert s.await_args.args == (payload, "dead")


async def test_the_task_handler_registers_adapters_then_sends() -> None:
    from app.worker.tasks import channel_tasks

    job = MagicMock()
    with (
        patch.object(channel_tasks, "ensure_channel_adapters") as ensure,
        patch.object(channel_tasks, "send_routine_answer", new=AsyncMock()) as send,
    ):
        await channel_tasks.deliver_routine_answer(job)

    ensure.assert_called_once()
    send.assert_awaited_once_with(job)


def test_the_api_schema_reads_a_pending_delivery_status() -> None:
    from pydantic import TypeAdapter

    from app.schemas.agent_trigger import TriggerRead

    annotation = TriggerRead.model_fields["last_delivery_status"].annotation
    assert TypeAdapter(annotation).validate_python("pending").value == "pending"


async def test_a_delivery_with_no_recorded_run_is_closed_without_a_notice(world: _World) -> None:
    with patch.object(routine_answer.agent_run_repo, "get_run", new=AsyncMock(return_value=None)):
        await settle_lost_routine_answer(world.job, "dead")

    assert world.trigger.last_delivery_status == "unavailable"
    world.blocked.assert_not_awaited()


async def test_a_routine_answer_longer_than_a_telegram_message_is_delivered_in_pieces(
    world: _World,
) -> None:
    """Telegram refuses a message over 4096 characters; the answer arrives split instead."""
    from aiogram.exceptions import TelegramBadRequest

    from app.services.channels.telegram import TelegramAdapter

    sent: list[str] = []

    async def send_message(*, text: str, **_: object) -> MagicMock:
        if len(text) > 4096:
            raise TelegramBadRequest(MagicMock(), "Bad Request: message is too long")
        sent.append(text)
        return MagicMock(message_id=1)

    telegram = MagicMock(send_message=AsyncMock(side_effect=send_message))

    @asynccontextmanager
    async def fake_bot(token: str, **_: object) -> AsyncIterator[MagicMock]:
        yield telegram

    world.message.content = "\n".join(f"**Finding {i}**: merged & deployed" for i in range(400))
    with (
        patch.object(TelegramAdapter, "_bot", staticmethod(fake_bot)),
        patch.object(routine_answer, "get_adapter", return_value=TelegramAdapter()),
    ):
        await send_routine_answer(world.job)

    assert len(sent) > 1
    assert world.trigger.last_delivery_status == "delivered"


async def test_an_answer_that_arrived_in_part_is_not_sent_again(world: _World) -> None:
    """A retry would post the pieces already in the chat a second time."""
    from app.services.channels.exceptions import PartlyDelivered

    world.adapter.send_message.side_effect = PartlyDelivered(
        message="x", details={"platform": "telegram", "delivered": 1, "pieces": 3}
    )

    await send_routine_answer(world.job)

    assert world.trigger.last_delivery_status == "unavailable"
    world.blocked.assert_awaited_once()


async def test_an_answer_whose_run_is_gone_is_not_sent(world: _World) -> None:
    world.run_found = False

    await send_routine_answer(world.job)

    world.adapter.send_message.assert_not_awaited()
    assert world.trigger.last_delivery_status == "unavailable"


async def test_the_worker_settler_hands_the_job_to_the_routine_settler() -> None:
    from app.worker.tasks import channel_tasks

    job = MagicMock()
    with patch.object(channel_tasks, "settle_unsent_answer", new=AsyncMock()) as settle:
        await channel_tasks.settle_lost_routine_answer(job, "dead")

    settle.assert_awaited_once_with(job, "dead")


async def test_an_unnamed_routine_is_posted_under_its_agents_name(world: _World) -> None:
    world.trigger.name = None

    await send_routine_answer(world.job)

    assert world.sent[1].text == "**Agent**\n\nThree PRs merged."


async def test_an_unnamed_routine_whose_agent_is_gone_is_posted_without_a_title(
    world: _World,
) -> None:
    world.trigger.name = None
    with patch.object(routine_answer.agent_repo, "get", new=AsyncMock(return_value=None)):
        await send_routine_answer(world.job)

    assert world.sent[1].text == "Three PRs merged."
