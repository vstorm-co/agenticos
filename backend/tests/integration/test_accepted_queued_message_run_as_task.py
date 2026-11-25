"""PostgreSQL coverage for accepted queued messages and Run as task transfer.

The queue receipt is the server-owned source of truth shared by the ordinary
chat drain and the task transfer. These tests exercise its uniqueness and
disposition locks against real database constraints; they intentionally do not
mock the receipt or task repositories.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.accepted_queued_message import AcceptedQueuedMessage
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_task import ConversationTask
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.room_participant import RoomParticipant
from app.db.models.user import User
from app.repositories import agent_run as agent_run_repo
from app.repositories import conversation as conversation_repo
from app.schemas.accepted_queued_message import AcceptedQueuedMessageCreate
from app.schemas.conversation import ChatPageContext
from app.schemas.local_target import LocalTarget
from app.services.accepted_queued_message import AcceptedQueuedMessageService
from app.services.agent import PersistedPrompt, persist_user_turn

pytestmark = pytest.mark.anyio


class Seed:
    def __init__(
        self,
        *,
        ctx: AuthContext,
        conversation: Conversation,
        agent: Agent,
        reply: Message,
        file: ChatFile,
    ) -> None:
        self.ctx = ctx
        self.conversation = conversation
        self.agent = agent
        self.reply = reply
        self.file = file


async def _seed(db: AsyncSession, *, room: bool = False) -> Seed:
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Acme", slug=f"acme-{uuid4().hex}", created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(id=uuid4(), organization_id=org.id, user_id=user.id, role="owner"))
    agent = Agent(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        slug=f"assistant-{uuid4().hex}",
        name="Assistant",
        status="published",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={
            "name": "Assistant",
            "model_profile_id": str(uuid4()),
            "capabilities": [],
        },
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    conversation = await conversation_repo.create_conversation(
        db, organization_id=org.id, user_id=user.id, title="Personal chat"
    )
    if room:
        conversation.room_visibility = "private"
        await db.flush()
    reply = await conversation_repo.create_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content="Earlier answer to quote",
        agent_id=agent.id,
        agent_version_id=version.id,
    )
    file = ChatFile(
        id=uuid4(),
        user_id=user.id,
        filename="brief.txt",
        mime_type="text/plain",
        size=12,
        storage_path=f"uploads/{uuid4().hex}.txt",
        file_type="text",
    )
    db.add(file)
    await db.flush()
    return Seed(
        ctx=AuthContext(user_id=user.id, organization_id=org.id, role="owner"),
        conversation=conversation,
        agent=agent,
        reply=reply,
        file=file,
    )


def _payload(seed: Seed, *, client_queue_id: UUID | None = None, content: str = "Run the report"):
    return AcceptedQueuedMessageCreate(
        client_queue_id=client_queue_id or uuid4(),
        agent_id=seed.agent.id,
        content=content,
        file_ids=[seed.file.id],
        mentions=[],
        reply_to_message_id=seed.reply.id,
        reply_to_excerpt="Earlier answer to quote",
    )


def _plain_payload(seed: Seed, *, content: str = "Continue with the report"):
    return AcceptedQueuedMessageCreate(
        client_queue_id=uuid4(),
        agent_id=seed.agent.id,
        content=content,
    )


async def _active_run(
    db: AsyncSession,
    seed: Seed,
    *,
    conversation_id: UUID | None = None,
    user_id: UUID | None = None,
    organization_id: UUID | None = None,
    agent_id: UUID | None = None,
    accepted_queue_id: UUID | None = None,
):
    return await agent_run_repo.create_run(
        db,
        organization_id=organization_id or seed.ctx.organization_id,
        agent_id=agent_id or seed.agent.id,
        agent_version_id=seed.agent.current_version_id,
        user_id=user_id or seed.ctx.subject_id,
        conversation_id=conversation_id or seed.conversation.id,
        surface="web",
        model_label="test-model",
        started_at=datetime.now(UTC),
        accepted_queue_id=accepted_queue_id,
    )


async def test_same_queue_key_is_idempotent_and_rejects_changed_payload(db: AsyncSession) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    payload = _payload(seed)

    first = await service.accept(seed.ctx, seed.conversation.id, payload)
    retry = await service.accept(seed.ctx, seed.conversation.id, payload)

    assert retry.id == first.id
    pending = await service.pending_for_conversation(
        organization_id=seed.ctx.organization_id,
        conversation_id=seed.conversation.id,
    )
    assert [row.id for row in pending] == [first.id]

    changed = payload.model_copy(update={"content": "Different message"})
    with pytest.raises(AlreadyExistsError, match="different queued message"):
        await service.accept(seed.ctx, seed.conversation.id, changed)

    contextual = payload.model_copy(
        update={
            "page_context": ChatPageContext(
                path="/tables/orders",
                title="Orders",
                captured_at="2026-11-20T00:00:00+00:00",
            ),
            "local_target": LocalTarget(
                folder="/work/orders",
                device_id=uuid4(),
                mode="read_only",
            ),
        }
    )
    with pytest.raises(AlreadyExistsError, match="different queued message"):
        await service.accept(seed.ctx, seed.conversation.id, contextual)


async def test_server_caps_pending_receipts_per_conversation(db: AsyncSession) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    for index in range(100):
        await service.accept(
            seed.ctx,
            seed.conversation.id,
            AcceptedQueuedMessageCreate(
                client_queue_id=uuid4(),
                agent_id=seed.agent.id,
                content=f"Queued message {index}",
            ),
        )

    with pytest.raises(AlreadyExistsError, match="100 queued messages"):
        await service.accept(
            seed.ctx,
            seed.conversation.id,
            AcceptedQueuedMessageCreate(
                client_queue_id=uuid4(),
                agent_id=seed.agent.id,
                content="One more than the queue limit",
            ),
        )


async def test_one_accepted_receipt_cannot_open_two_agent_runs(db: AsyncSession) -> None:
    seed = await _seed(db)
    receipt = await AcceptedQueuedMessageService(db).accept(
        seed.ctx, seed.conversation.id, _plain_payload(seed)
    )
    first = await _active_run(db, seed, accepted_queue_id=receipt.id)
    first_id = first.id
    await db.commit()

    with pytest.raises(IntegrityError):
        await _active_run(db, seed, accepted_queue_id=receipt.id)
    await db.rollback()
    await db.refresh(first)

    assert first.id == first_id
    assert first.accepted_queue_id == receipt.id
    assert (
        await db.scalar(
            select(func.count(AgentRun.id)).where(AgentRun.accepted_queue_id == receipt.id)
        )
        == 1
    )


async def test_run_as_task_freezes_quote_and_moves_owned_attachment_once(db: AsyncSession) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    receipt = await service.accept(seed.ctx, seed.conversation.id, _payload(seed))

    first = await service.run_as_task(seed.ctx, seed.conversation.id, receipt.id)
    retry = await service.run_as_task(seed.ctx, seed.conversation.id, receipt.id)

    assert retry.id == first.id
    task = await db.scalar(select(ConversationTask).where(ConversationTask.id == first.id))
    assert task is not None
    assert task.queue_receipt_id == receipt.id
    assert task.source_run_id is None and task.tool_call_id is None
    assert task.agent_id == seed.agent.id and task.version_id is not None
    topic = await conversation_repo.get_conversation_by_id(db, task.conversation_id)
    assert topic is not None and topic.user_id == seed.ctx.subject_id and topic.project_id is None
    messages = await conversation_repo.get_messages_by_conversation(db, task.conversation_id)
    user_message = next(message for message in messages if message.role == "user")
    assert user_message.content == (
        "Run the report\n\nQuoted earlier assistant message:\n> Earlier answer to quote"
    )
    assert user_message.reply_to_message_id is None  # Never point across conversations.
    assert user_message.reply_to_excerpt is None
    execution_prompt, seed_message_id, attachments = await service.task_input_for_worker(
        seed.ctx, task
    )
    assert seed_message_id == user_message.id
    assert execution_prompt == (
        "Run the report\n\nQuoted earlier assistant message:\n> Earlier answer to quote"
    )
    assert [attachment.id for attachment in attachments] == [seed.file.id]
    attached = await db.get(ChatFile, seed.file.id)
    assert attached is not None and attached.message_id == user_message.id
    assert attached.queue_receipt_id is None
    assert (
        await service.pending_for_conversation(
            organization_id=seed.ctx.organization_id,
            conversation_id=seed.conversation.id,
        )
        == []
    )


async def test_persisting_a_sent_receipt_reuses_its_frozen_seed_and_attachment(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    seed = await _seed(db)
    receipt = await AcceptedQueuedMessageService(db).accept(
        seed.ctx, seed.conversation.id, _payload(seed)
    )
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def database_context() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def persist(client_copy: str) -> PersistedPrompt:
        return await persist_user_turn(
            user=SimpleNamespace(id=seed.ctx.subject_id),
            user_message=client_copy,
            file_ids=[seed.file.id],
            requested_conversation_id=str(seed.conversation.id),
            current_conversation_id=str(seed.conversation.id),
            organization_id=seed.ctx.organization_id,
            # A retry's client copy cannot replace the quote frozen at acceptance.
            reply_to=str(uuid4()),
            reply_to_excerpt="Edited quote from a retry",
            accepted_queue_id=receipt.id,
            queue_context=seed.ctx,
        )

    link_files = AsyncMock()
    with (
        patch("app.services.agent.get_db_context", side_effect=database_context),
        patch("app.services.agent.ConversationService.link_files_to_message", new=link_files),
    ):
        first = await persist("Original-looking client body")
        retry = await persist("Modified retry body")

    assert first.message_id is not None
    assert retry.message_id == first.message_id
    link_files.assert_not_awaited()

    async with sessions() as reader:
        messages = list(
            await reader.scalars(select(Message).where(Message.accepted_queue_id == receipt.id))
        )
        assert len(messages) == 1
        stored = messages[0]
        assert stored.id == first.message_id
        assert stored.content == "Run the report"
        assert stored.reply_to_message_id == seed.reply.id
        assert stored.reply_to_excerpt == "Earlier answer to quote"
        attached = await reader.get(ChatFile, seed.file.id)
        assert attached is not None
        assert attached.message_id == stored.id
        assert attached.queue_receipt_id is None


async def test_run_as_task_preserves_bounded_page_and_local_context(db: AsyncSession) -> None:
    seed = await _seed(db)
    page = ChatPageContext(
        path="/tables/orders",
        title="Orders",
        captured_at="2026-11-20T00:00:00+00:00",
        summary="Three orders are open.",
        selected_ids=["order-1"],
    )
    local = LocalTarget(folder="/work/orders", device_id=uuid4(), mode="read_only")
    payload = _payload(seed).model_copy(update={"page_context": page, "local_target": local})
    service = AcceptedQueuedMessageService(db)

    receipt = await service.accept(seed.ctx, seed.conversation.id, payload)
    read = await service.get_for_owner(seed.ctx, seed.conversation.id, receipt.id)
    assert read.page_context == page
    assert read.local_target is not None
    assert read.local_target.model_dump(mode="json") == local.model_dump(mode="json")
    assert read.reply_to_role == "assistant"
    assert read.quote_excerpt == "Earlier answer to quote"

    created = await service.run_as_task(seed.ctx, seed.conversation.id, receipt.id)
    task = await db.scalar(select(ConversationTask).where(ConversationTask.id == created.id))
    assert task is not None
    assert task.local_target == local.model_dump(mode="json")
    execution_prompt, seed_message_id, attachments = await service.task_input_for_worker(
        seed.ctx, task
    )
    assert seed_message_id is not None
    assert [attachment.id for attachment in attachments] == [seed.file.id]
    assert "Orders" in execution_prompt
    assert "Three orders are open." in execution_prompt
    assert "untrusted reference data" in execution_prompt


@pytest.mark.security
async def test_run_as_task_refuses_untransferable_local_grants_but_keeps_receipt_pending(
    db: AsyncSession,
) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)

    no_device = await service.accept(
        seed.ctx,
        seed.conversation.id,
        _plain_payload(seed).model_copy(
            update={"local_target": LocalTarget(folder="/work/orders", mode="read_only")}
        ),
    )
    with pytest.raises(BadRequestError, match="specific computer"):
        await service.run_as_task(seed.ctx, seed.conversation.id, no_device.id)
    assert (
        await service.get_for_owner(seed.ctx, seed.conversation.id, no_device.id)
    ).state == "pending"

    whole_computer = await service.accept(
        seed.ctx,
        seed.conversation.id,
        _plain_payload(seed).model_copy(
            update={
                "local_target": LocalTarget(
                    folder="/computer/home",
                    device_id=uuid4(),
                    computer_grant=uuid4(),
                    mode="full_access",
                )
            }
        ),
    )
    with pytest.raises(BadRequestError, match="specific computer"):
        await service.run_as_task(seed.ctx, seed.conversation.id, whole_computer.id)
    assert (
        await service.get_for_owner(seed.ctx, seed.conversation.id, whole_computer.id)
    ).state == "pending"

    routine_target = LocalTarget(
        folder="/work/orders",
        device_id=uuid4(),
        mode="read_only",
        routine_grant=uuid4(),
        operations={"read": True, "write": False, "execute": False},
    )
    routine_receipt = await service.accept(
        seed.ctx,
        seed.conversation.id,
        _plain_payload(seed).model_copy(update={"local_target": routine_target}),
    )
    with pytest.raises(BadRequestError):
        await service.run_as_task(seed.ctx, seed.conversation.id, routine_receipt.id)
    assert (
        await service.get_for_owner(seed.ctx, seed.conversation.id, routine_receipt.id)
    ).state == "pending"


async def test_queued_receipt_rejects_unknown_local_target_fields() -> None:
    with pytest.raises(ValidationError, match="project_id"):
        AcceptedQueuedMessageCreate.model_validate(
            {
                "client_queue_id": uuid4(),
                "agent_id": uuid4(),
                "content": "Use the local folder",
                "local_target": {
                    "folder": "/work/orders",
                    "mode": "read_only",
                    "project_id": str(uuid4()),
                },
            }
        )


async def test_send_and_task_transfer_race_has_one_durable_winner(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    seed = await _seed(db)
    receipt = await AcceptedQueuedMessageService(db).accept(
        seed.ctx, seed.conversation.id, _payload(seed)
    )
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def send() -> object:
        async with sessions() as session, session.begin():
            return await AcceptedQueuedMessageService(session).claim_for_send(
                seed.ctx,
                seed.conversation.id,
                receipt.id,
                _payload(seed, client_queue_id=receipt.client_queue_id),
            )

    async def transfer() -> object:
        async with sessions() as session, session.begin():
            return await AcceptedQueuedMessageService(session).run_as_task(
                seed.ctx, seed.conversation.id, receipt.id
            )

    results = await asyncio.gather(send(), transfer(), return_exceptions=True)
    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], AlreadyExistsError)

    async with sessions() as session:
        settled = await AcceptedQueuedMessageService(session).get_for_owner(
            seed.ctx, seed.conversation.id, receipt.id
        )
        assert settled.state in {"sent", "task"}
        if settled.state == "sent":
            assert settled.message_id is not None
            assert (
                await session.scalar(
                    select(ConversationTask.id).where(
                        ConversationTask.queue_receipt_id == receipt.id
                    )
                )
                is None
            )
        else:
            assert (
                await session.scalar(
                    select(ConversationTask.id).where(
                        ConversationTask.queue_receipt_id == receipt.id
                    )
                )
                is not None
            )


async def test_send_task_and_steer_race_has_one_durable_disposition(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    payload = _plain_payload(seed)
    receipt = await service.accept(seed.ctx, seed.conversation.id, payload)
    run = await _active_run(db, seed)
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def send() -> object:
        async with sessions() as session, session.begin():
            return await AcceptedQueuedMessageService(session).claim_for_send(
                seed.ctx, seed.conversation.id, receipt.id, payload
            )

    async def transfer() -> object:
        async with sessions() as session, session.begin():
            return await AcceptedQueuedMessageService(session).run_as_task(
                seed.ctx, seed.conversation.id, receipt.id
            )

    async def steer() -> object:
        async with sessions() as session, session.begin():
            return await AcceptedQueuedMessageService(session).claim_for_steer(
                seed.ctx,
                seed.conversation.id,
                receipt.id,
                run_id=run.id,
                active_agent_id=seed.agent.id,
            )

    results = await asyncio.gather(send(), transfer(), steer(), return_exceptions=True)
    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 2
    assert all(isinstance(failure, AlreadyExistsError) for failure in failures)

    async with sessions() as session:
        settled = await AcceptedQueuedMessageService(session).get_for_owner(
            seed.ctx, seed.conversation.id, receipt.id
        )
        messages = await session.scalar(
            select(func.count(Message.id)).where(Message.accepted_queue_id == receipt.id)
        )
        tasks = await session.scalar(
            select(func.count(ConversationTask.id)).where(
                ConversationTask.queue_receipt_id == receipt.id
            )
        )
        if settled.state == "sent":
            assert messages == 1 and tasks == 0
            assert settled.message_id is not None
        elif settled.state == "task":
            assert messages == 1 and tasks == 1
            task = await session.scalar(
                select(ConversationTask).where(ConversationTask.queue_receipt_id == receipt.id)
            )
            assert task is not None and task.id is not None
        else:
            assert settled.state == "steering"
            assert settled.steering_run_id == run.id
            assert messages == 0 and tasks == 0


async def test_steer_claim_and_consumption_are_idempotent_and_terminal(
    db: AsyncSession,
) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    payload = _plain_payload(seed)
    receipt = await service.accept(seed.ctx, seed.conversation.id, payload)
    run = await _active_run(db, seed)

    claim = {
        "run_id": run.id,
        "active_agent_id": seed.agent.id,
    }
    assert (
        await service.claim_for_steer(seed.ctx, seed.conversation.id, receipt.id, **claim)
        == "claimed"
    )
    assert (
        await service.claim_for_steer(seed.ctx, seed.conversation.id, receipt.id, **claim)
        == "steering"
    )
    assert await service.finish_steer(seed.ctx, seed.conversation.id, receipt.id, run_id=run.id)
    assert not await service.finish_steer(seed.ctx, seed.conversation.id, receipt.id, run_id=run.id)
    assert (
        await service.claim_for_steer(seed.ctx, seed.conversation.id, receipt.id, **claim)
        == "steered"
    )
    assert not await service.release_unconsumed_steer(
        seed.ctx, seed.conversation.id, receipt.id, run_id=run.id
    )

    with pytest.raises(AlreadyExistsError):
        await service.claim_for_send(seed.ctx, seed.conversation.id, receipt.id, payload)
    with pytest.raises(AlreadyExistsError):
        await service.run_as_task(seed.ctx, seed.conversation.id, receipt.id)
    assert (
        await service.get_for_owner(seed.ctx, seed.conversation.id, receipt.id)
    ).state == "steered"
    assert (
        await db.scalar(select(Message.id).where(Message.accepted_queue_id == receipt.id)) is None
    )
    assert (
        await db.scalar(
            select(ConversationTask.id).where(ConversationTask.queue_receipt_id == receipt.id)
        )
        is None
    )


async def test_only_same_run_can_release_an_unconsumed_steer(db: AsyncSession) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    payload = _plain_payload(seed)
    receipt = await service.accept(seed.ctx, seed.conversation.id, payload)
    run = await _active_run(db, seed)

    assert (
        await service.claim_for_steer(
            seed.ctx,
            seed.conversation.id,
            receipt.id,
            run_id=run.id,
            active_agent_id=seed.agent.id,
        )
        == "claimed"
    )
    assert not await service.release_unconsumed_steer(
        seed.ctx, seed.conversation.id, receipt.id, run_id=uuid4()
    )
    assert await service.release_unconsumed_steer(
        seed.ctx, seed.conversation.id, receipt.id, run_id=run.id
    )
    released = await service.get_for_owner(seed.ctx, seed.conversation.id, receipt.id)
    assert released.state == "pending" and released.steering_run_id is None

    sent = await service.claim_for_send(seed.ctx, seed.conversation.id, receipt.id, payload)
    assert sent.accepted_queue_id == receipt.id
    assert (await service.get_for_owner(seed.ctx, seed.conversation.id, receipt.id)).state == "sent"


@pytest.mark.security
async def test_deleted_steering_run_keeps_receipt_blocked_and_visible(
    db: AsyncSession,
) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    payload = _plain_payload(seed)
    receipt = await service.accept(seed.ctx, seed.conversation.id, payload)
    run = await _active_run(db, seed)
    assert (
        await service.claim_for_steer(
            seed.ctx,
            seed.conversation.id,
            receipt.id,
            run_id=run.id,
            active_agent_id=seed.agent.id,
        )
        == "claimed"
    )
    receipt_row = await db.get(AcceptedQueuedMessage, receipt.id)
    assert receipt_row is not None
    await db.delete(run)
    await db.flush()
    await db.refresh(receipt_row)

    retained = await service.get_for_owner(seed.ctx, seed.conversation.id, receipt.id)
    assert retained.state == "steering" and retained.steering_run_id is None
    visible = await service.list_pending(seed.ctx, seed.conversation.id)
    assert any(item.id == receipt.id and item.state == "steering" for item in visible.items)
    new_run = await _active_run(db, seed)

    with pytest.raises(AlreadyExistsError):
        await service.claim_for_send(seed.ctx, seed.conversation.id, receipt.id, payload)
    with pytest.raises(AlreadyExistsError):
        await service.run_as_task(seed.ctx, seed.conversation.id, receipt.id)
    with pytest.raises(AlreadyExistsError):
        await service.claim_for_steer(
            seed.ctx,
            seed.conversation.id,
            receipt.id,
            run_id=new_run.id,
            active_agent_id=seed.agent.id,
        )
    assert (
        await db.scalar(select(Message.id).where(Message.accepted_queue_id == receipt.id)) is None
    )
    assert (
        await db.scalar(
            select(ConversationTask.id).where(ConversationTask.queue_receipt_id == receipt.id)
        )
        is None
    )


async def test_steering_receipts_count_toward_cap_and_fresh_chat_guard(
    db: AsyncSession,
) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    steering = await service.accept(seed.ctx, seed.conversation.id, _plain_payload(seed))
    run = await _active_run(db, seed)
    assert (
        await service.claim_for_steer(
            seed.ctx,
            seed.conversation.id,
            steering.id,
            run_id=run.id,
            active_agent_id=seed.agent.id,
        )
        == "claimed"
    )

    for index in range(99):
        await service.accept(
            seed.ctx,
            seed.conversation.id,
            _plain_payload(seed, content=f"Queued item {index}"),
        )

    listed = await service.list_pending(seed.ctx, seed.conversation.id)
    assert len(listed.items) == 100
    assert any(item.id == steering.id and item.state == "steering" for item in listed.items)
    with pytest.raises(AlreadyExistsError, match="100 queued messages"):
        await service.accept(seed.ctx, seed.conversation.id, _plain_payload(seed))

    for item in listed.items:
        if item.id != steering.id:
            await service.cancel(seed.ctx, seed.conversation.id, item.id)
    unresolved = await service.pending_for_conversation(
        organization_id=seed.ctx.organization_id,
        conversation_id=seed.conversation.id,
    )
    assert len(unresolved) == 1
    assert unresolved[0].id == steering.id and unresolved[0].state == "steering"


async def test_active_run_binding_requires_owner_conversation_and_agent(
    db: AsyncSession,
) -> None:
    seed, other_owner = await _seed(db), await _seed(db)
    service = AcceptedQueuedMessageService(db)
    receipt = await service.accept(seed.ctx, seed.conversation.id, _plain_payload(seed))
    valid_run = await _active_run(db, seed)
    other_conversation = await conversation_repo.create_conversation(
        db,
        organization_id=seed.ctx.organization_id,
        user_id=seed.ctx.subject_id,
        title="Another personal chat",
    )
    wrong_conversation_run = await _active_run(db, seed, conversation_id=other_conversation.id)
    foreign_owner_run = await _active_run(db, other_owner)

    for run_id, agent_id in (
        (wrong_conversation_run.id, seed.agent.id),
        (foreign_owner_run.id, seed.agent.id),
        (valid_run.id, other_owner.agent.id),
    ):
        with pytest.raises(AlreadyExistsError):
            await service.claim_for_steer(
                seed.ctx,
                seed.conversation.id,
                receipt.id,
                run_id=run_id,
                active_agent_id=agent_id,
            )
        assert (
            await service.get_for_owner(seed.ctx, seed.conversation.id, receipt.id)
        ).state == "pending"

    assert (
        await service.claim_for_steer(
            seed.ctx,
            seed.conversation.id,
            receipt.id,
            run_id=valid_run.id,
            active_agent_id=seed.agent.id,
        )
        == "claimed"
    )


@pytest.mark.security
@pytest.mark.parametrize("revocation", ["membership", "archived_agent"])
async def test_authority_is_rechecked_when_claiming_accepted_receipts(
    db: AsyncSession,
    engine: AsyncEngine,
    revocation: str,
) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)
    payloads = [
        _plain_payload(seed, content=f"{action} this item") for action in ("send", "task", "steer")
    ]
    receipts = [
        await service.accept(seed.ctx, seed.conversation.id, payload) for payload in payloads
    ]
    run = await _active_run(db, seed)
    await db.commit()

    if revocation == "membership":
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.organization_id == seed.ctx.organization_id,
                OrganizationMember.user_id == seed.ctx.subject_id,
            )
        )
    else:
        agent = await db.get(Agent, seed.agent.id)
        assert agent is not None
        agent.status = "archived"
    await db.commit()

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    failures = (
        (AuthorizationError, NotFoundError)
        if revocation == "membership"
        else (AuthorizationError, BadRequestError, NotFoundError)
    )
    for action, receipt, payload in zip(("send", "task", "steer"), receipts, payloads):
        async with sessions() as session, session.begin():
            current = AcceptedQueuedMessageService(session)
            with pytest.raises(failures):
                if action == "send":
                    await current.claim_for_send(
                        seed.ctx, seed.conversation.id, receipt.id, payload
                    )
                elif action == "task":
                    await current.run_as_task(seed.ctx, seed.conversation.id, receipt.id)
                else:
                    await current.claim_for_steer(
                        seed.ctx,
                        seed.conversation.id,
                        receipt.id,
                        run_id=run.id,
                        active_agent_id=seed.agent.id,
                    )
            retained = await session.get(AcceptedQueuedMessage, receipt.id)
            assert retained is not None and retained.state == "pending"
            assert (
                await session.scalar(
                    select(Message.id).where(Message.accepted_queue_id == receipt.id)
                )
                is None
            )
            assert (
                await session.scalar(
                    select(ConversationTask.id).where(
                        ConversationTask.queue_receipt_id == receipt.id
                    )
                )
                is None
            )


async def test_two_receipts_cannot_reserve_the_same_attachment(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    seed = await _seed(db)
    file_payloads = [
        _payload(seed, content="Use the uploaded brief").model_copy(
            update={"client_queue_id": uuid4()}
        )
        for _ in range(2)
    ]
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def accept(payload: AcceptedQueuedMessageCreate) -> object:
        async with sessions() as session, session.begin():
            return await AcceptedQueuedMessageService(session).accept(
                seed.ctx, seed.conversation.id, payload
            )

    results = await asyncio.gather(
        *(accept(payload) for payload in file_payloads), return_exceptions=True
    )
    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1 and isinstance(failures[0], AlreadyExistsError)

    async with sessions() as session:
        attached = await session.get(ChatFile, seed.file.id)
        assert attached is not None
        assert attached.queue_receipt_id == successes[0].id
        assert attached.message_id is None


async def test_consumed_dispositions_conflict_in_both_directions(db: AsyncSession) -> None:
    seed = await _seed(db)
    service = AcceptedQueuedMessageService(db)

    task_payload = _plain_payload(seed)
    task_receipt = await service.accept(seed.ctx, seed.conversation.id, task_payload)
    await service.run_as_task(seed.ctx, seed.conversation.id, task_receipt.id)
    with pytest.raises(AlreadyExistsError):
        await service.claim_for_send(
            seed.ctx,
            seed.conversation.id,
            task_receipt.id,
            task_payload,
        )

    send_payload = _plain_payload(seed)
    send_receipt = await service.accept(seed.ctx, seed.conversation.id, send_payload)
    await service.claim_for_send(
        seed.ctx,
        seed.conversation.id,
        send_receipt.id,
        send_payload,
    )
    with pytest.raises(AlreadyExistsError):
        await service.run_as_task(seed.ctx, seed.conversation.id, send_receipt.id)


@pytest.mark.security
async def test_receipts_are_private_and_only_personal_chats_are_transferable(
    db: AsyncSession,
) -> None:
    owner, stranger = await _seed(db), await _seed(db)
    db.add(
        OrganizationMember(
            id=uuid4(),
            organization_id=owner.ctx.organization_id,
            user_id=stranger.ctx.subject_id,
            role="member",
        )
    )
    await db.flush()
    service = AcceptedQueuedMessageService(db)
    receipt = await service.accept(owner.ctx, owner.conversation.id, _payload(owner))

    stranger_ctx = AuthContext(
        user_id=stranger.ctx.subject_id,
        organization_id=owner.ctx.organization_id,
        role="member",
    )
    with pytest.raises(NotFoundError):
        await service.run_as_task(stranger_ctx, owner.conversation.id, receipt.id)
    with pytest.raises((AuthorizationError, NotFoundError)):
        await service.accept(owner.ctx, stranger.conversation.id, _payload(owner))

    room = await _seed(db, room=True)
    db.add(
        RoomParticipant(
            id=uuid4(),
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            user_id=room.ctx.subject_id,
        )
    )
    await db.flush()
    accessible_room = await service.conversations.get_conversation(
        room.conversation.id,
        organization_id=room.ctx.organization_id,
        user_id=room.ctx.subject_id,
        for_write=True,
        turn=True,
        include_favourite=False,
        ctx=room.ctx,
    )
    assert accessible_room.room_visibility == "private"
    with pytest.raises(NotFoundError, match="personal chats"):
        await service.accept(room.ctx, room.conversation.id, _payload(room))
