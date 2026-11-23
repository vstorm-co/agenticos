"""A routine answer stored in a private chat's conversation is posted by the channel bot.

Storing the answer shows it in the console only. When the delivery conversation
belongs to a private chat on a chat platform, the fire queues one send and the
status reads `pending` until that job settles it. Group chats, SMS and plain web
conversations keep the stored answer and read `delivered`.
"""

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import OrgRoleName
from app.db.models.agent_run import RunStatus
from app.worker.jobs import ROUTINE_CHAT_ANSWER, RoutineChatAnswer
from tests.test_agent_triggers import (  # noqa: F401 - autouse fixtures
    _agent,
    _service,
    _trigger,
    device_waits_are_separate_from_existing_trigger_unit_contracts,
    discard_mocked_live_updates,
    organization_model_surface,
    routine_notices,
)

pytestmark = pytest.mark.anyio

CHAT_ID = "777001"


class _Fired:
    def __init__(self) -> None:
        self.enqueue = AsyncMock(return_value=uuid.uuid4())
        self.session_lookup = AsyncMock()
        self.bot_lookup = AsyncMock()
        self.resolve = AsyncMock()
        self.run = MagicMock(id=uuid.uuid4(), status=RunStatus.COMPLETED.value)
        self.agent = _agent(name="Nightly")
        self.service = _service(self.agent)


@pytest.fixture
def fired() -> Iterator[_Fired]:
    yield _Fired()


def _session(target: uuid.UUID, *, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        bot_id=uuid.uuid4(),
        conversation_id=target,
        platform_chat_id=CHAT_ID,
        chat_type=chat_type,
    )


def _bot(platform: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), platform=platform)


async def _fire(
    fired: _Fired,
    trigger: MagicMock,
    *,
    session: SimpleNamespace | None,
    bot: SimpleNamespace | None,
    archived: bool = False,
    answer: str = "Three PRs merged.",
) -> None:
    fired.session_lookup.return_value = session
    fired.bot_lookup.return_value = bot
    with (
        patch("app.services.agent_trigger.agent_trigger_repo") as repo,
        patch("app.services.agent_trigger.member_repo") as members,
        patch("app.services.agent_trigger.conversation_repo") as conversations,
        patch("app.services.agent_trigger.record_audit", new=AsyncMock()),
        patch("app.services.agent_trigger.ConversationService") as access,
        patch("app.services.agent_runner.AgentRunnerService") as runner_cls,
        patch("app.services.agent_trigger.enqueue", new=fired.enqueue),
        patch("app.services.agent_trigger.channel_session_repo") as sessions,
        patch("app.services.agent_trigger.channel_bot_repo") as bots,
        patch("app.services.agent_trigger.OutcomeService") as outcomes,
    ):
        outcomes.return_value.resolve_routine_budget = AsyncMock()
        outcomes.return_value.resolve_routine_failure = fired.resolve
        sessions.get_for_conversation = fired.session_lookup
        bots.get_for_org = fired.bot_lookup
        access.return_value.get_conversation = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=trigger)
        members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER))
        conversations.get_conversation_by_id = AsyncMock(
            side_effect=lambda _db, target, **kw: MagicMock(
                is_archived=archived,
                id=target,
                organization_id=trigger.organization_id,
                user_id=trigger.created_by_user_id,
            )
        )
        conversations.create_conversation = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        conversations.create_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        runner_cls.return_value.execute = AsyncMock(return_value=(answer, fired.run))
        fired.service.agents.get = AsyncMock(return_value=fired.agent)
        await fired.service.fire(trigger.id)
        fired.messages = conversations.create_message


async def test_a_group_chat_answer_queues_no_send_and_reads_delivered(fired: _Fired) -> None:
    target = uuid.uuid4()
    trigger = _trigger(answer_to="conversation", delivery_conversation_id=target)

    await _fire(fired, trigger, session=_session(target, chat_type="group"), bot=_bot("telegram"))

    fired.enqueue.assert_not_awaited()
    assert trigger.last_delivery_status == "delivered"


async def test_an_sms_conversation_queues_no_send_and_reads_delivered(fired: _Fired) -> None:
    target = uuid.uuid4()
    trigger = _trigger(answer_to="conversation", delivery_conversation_id=target)

    await _fire(fired, trigger, session=_session(target), bot=_bot("sms"))

    fired.enqueue.assert_not_awaited()
    assert trigger.last_delivery_status == "delivered"


async def test_a_plain_web_conversation_is_delivered_without_a_chat_send(fired: _Fired) -> None:
    target = uuid.uuid4()
    trigger = _trigger(answer_to="conversation", delivery_conversation_id=target)

    await _fire(fired, trigger, session=None, bot=None)

    fired.enqueue.assert_not_awaited()
    assert trigger.last_delivery_status == "delivered"
    fired.resolve.assert_awaited_once()


async def test_an_answer_that_could_not_be_stored_queues_no_send(fired: _Fired) -> None:
    target = uuid.uuid4()
    trigger = _trigger(answer_to="conversation", delivery_conversation_id=target)

    await _fire(fired, trigger, session=_session(target), bot=_bot("telegram"), archived=True)

    fired.enqueue.assert_not_awaited()
    assert trigger.last_delivery_status == "unavailable"


async def test_a_run_log_routine_never_looks_for_a_chat(fired: _Fired) -> None:
    trigger = _trigger(answer_to="run_log")

    await _fire(fired, trigger, session=_session(uuid.uuid4()), bot=_bot("telegram"))

    fired.session_lookup.assert_not_awaited()
    fired.enqueue.assert_not_awaited()
    assert trigger.last_delivery_status == "run_log"


async def test_a_private_chat_bound_answer_queues_one_send_and_reads_pending(
    fired: _Fired,
) -> None:
    target = uuid.uuid4()
    trigger = _trigger(answer_to="conversation", delivery_conversation_id=target)
    session = _session(target)

    await _fire(fired, trigger, session=session, bot=_bot("telegram"))

    fired.enqueue.assert_awaited_once()
    args, kwargs = fired.enqueue.await_args
    assert args[1] is ROUTINE_CHAT_ANSWER
    payload = args[2]
    stored = fired.messages.await_args
    assert isinstance(payload, RoutineChatAnswer)
    assert payload.model_dump() == {
        "organization_id": trigger.organization_id,
        "trigger_id": trigger.id,
        "run_id": fired.run.id,
        "conversation_id": target,
        "session_id": session.id,
        "message_id": fired.messages.return_value.id,
    }
    assert stored.kwargs["content"].endswith("Three PRs merged.")
    assert kwargs["organization_id"] == trigger.organization_id
    assert kwargs["dedupe_key"] == f"routine-chat-answer:{fired.run.id}"
    assert kwargs["concurrency_key"] == f"channel-handback:{session.bot_id}:{CHAT_ID}"
    assert trigger.last_delivery_status == "pending"
    assert trigger.last_run_id == fired.run.id
    fired.resolve.assert_not_awaited()


async def test_a_private_chat_on_another_chat_platform_also_queues_a_send(
    fired: _Fired,
) -> None:
    target = uuid.uuid4()
    trigger = _trigger(answer_to="conversation", delivery_conversation_id=target)

    await _fire(fired, trigger, session=_session(target), bot=_bot("slack"))

    fired.enqueue.assert_awaited_once()
    assert trigger.last_delivery_status == "pending"


async def test_a_private_chat_whose_bot_is_gone_still_queues_so_the_job_settles_it(
    fired: _Fired,
) -> None:
    target = uuid.uuid4()
    trigger = _trigger(answer_to="conversation", delivery_conversation_id=target)

    await _fire(fired, trigger, session=_session(target), bot=None)

    fired.enqueue.assert_awaited_once()
    assert trigger.last_delivery_status == "pending"
