"""Subthreads retain their roots, ordering and model scope in PostgreSQL."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_task import ConversationTask
from app.db.models.organization import OrganizationMember
from app.db.models.project import Project
from app.db.models.resource_grant import ResourceGrant
from app.db.models.room_submission import RoomSubmission
from app.db.models.user import User
from app.repositories import agent_run as run_repo
from app.repositories import conversation as conversation_repo
from app.repositories import conversation_task as task_repo
from app.repositories import project as project_repo
from app.schemas.room_submission import RoomMessageCreate
from app.services.conversation import ConversationService
from app.services.conversation_tasks import ConversationTaskService
from app.services.room_submission import RoomSubmissionService, fingerprint
from app.services.transcript import TranscriptService
from tests.integration.test_room_submissions import Room, seed

pytestmark = pytest.mark.anyio

AT = datetime(2026, 1, 1, tzinfo=UTC)


async def message(
    db: AsyncSession,
    room: Room,
    content: str,
    *,
    root: Message | None = None,
    quote: Message | None = None,
    role: str = "user",
    at: datetime = AT,
    run_id: UUID | None = None,
) -> Message:
    row = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role=role,
        content=content,
        author_user_id=room.user.id if role == "user" else None,
        thread_root_message_id=root.id if root else None,
        reply_to_message_id=quote.id if quote else None,
        created_at=at,
        run_id=run_id,
    )
    db.add(row)
    await db.flush()
    return row


async def request(
    db: AsyncSession, room: Room, content: str, *, root: Message | None = None
) -> tuple[Message, RoomSubmission]:
    row = await message(db, room, content, root=root)
    payload = RoomMessageCreate(
        client_message_id=uuid4().hex,
        content=content,
        agent_id=room.agent.id,
        thread_root_message_id=root.id if root else None,
    )
    submission = RoomSubmission(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        requester_id=room.user.id,
        message_id=row.id,
        client_message_id=payload.client_message_id,
        fingerprint=fingerprint(payload),
        agent_id=room.agent.id,
        version_id=room.version.id,
        status="queued",
    )
    db.add(submission)
    await db.flush()
    return row, submission


async def completed_answer(
    db: AsyncSession,
    room: Room,
    submission: RoomSubmission,
    content: str,
    *,
    root: Message | None = None,
) -> Message:
    run = await run_repo.create_run(
        db,
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        user_id=room.user.id,
        conversation_id=room.conversation.id,
        surface="web",
        model_label=None,
        started_at=AT,
    )
    run.status = "completed"
    submission.run_id = run.id
    submission.status = "completed"
    await db.flush()
    return await message(db, room, content, root=root, role="assistant", run_id=run.id)


@pytest.mark.security
async def test_thread_foreign_key_rejects_other_rooms_missing_roots_and_self(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    other = await seed(db)
    foreign_root = await message(db, other, "Other room")
    for root_id, own_id in ((foreign_root.id, uuid4()), (uuid4(), uuid4())):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(
                    Message(
                        id=own_id,
                        conversation_id=room.conversation.id,
                        role="user",
                        content="Invalid thread",
                        thread_root_message_id=root_id,
                    )
                )
                await db.flush()
        assert await db.scalar(select(Message.id).where(Message.id == own_id)) is None

    self_id = uuid4()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                Message(
                    id=self_id,
                    conversation_id=room.conversation.id,
                    role="user",
                    content="Self root",
                    thread_root_message_id=self_id,
                )
            )
            await db.flush()
    assert (
        await db.scalar(select(Message.id).where(Message.id == foreign_root.id)) == foreign_root.id
    )


async def test_deleting_a_root_removes_its_replies_and_requests_but_keeps_main_quotes(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root")
    reply, submission = await request(db, room, "Thread request", root=root)
    answer = await message(db, room, "Thread answer", root=root, quote=reply, role="assistant")
    main_quote = await message(db, room, "Main quote", quote=root)
    other_root = await message(db, room, "Other root")
    other_reply = await message(db, room, "Other reply", root=other_root)
    deleted_ids = {root.id, reply.id, answer.id}
    submission_id = submission.id
    kept_ids = {main_quote.id, other_root.id, other_reply.id}

    assert await conversation_repo.delete_message(db, root.id)
    remaining = set(
        await db.scalars(select(Message.id).where(Message.conversation_id == room.conversation.id))
    )
    assert remaining == kept_ids
    assert not remaining.intersection(deleted_ids)
    assert (
        await db.scalar(select(RoomSubmission.id).where(RoomSubmission.id == submission_id)) is None
    )
    assert (
        await db.scalar(select(Message.reply_to_message_id).where(Message.id == main_quote.id))
        is None
    )


async def test_thread_pages_keep_the_root_and_count_replies_outside_the_page(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root", role="assistant")
    first = await message(db, room, "First", root=root)
    other_root = await message(db, room, "Sibling root")
    unrelated = await message(db, room, "Sibling reply", root=other_root)
    second = await message(db, room, "Second", root=root, quote=first)
    third = await message(db, room, "Third", root=root)
    service = RoomSubmissionService(db)

    latest = await service.thread(room.ctx, room.conversation.id, root.id, limit=2)
    assert latest.root.id == root.id
    assert [row.id for row in latest.items] == [second.id, third.id]
    assert latest.root.thread_reply_count == latest.total == 3
    assert latest.can_post
    assert latest.items[0].reply_to is not None
    assert latest.items[0].reply_to.message_id == first.id

    older = await service.thread(room.ctx, room.conversation.id, root.id, limit=2, before=second.id)
    assert older.root.id == root.id
    assert [row.id for row in older.items] == [first.id]
    assert older.total == 3
    for cursor in (unrelated.id, other_root.id, uuid4()):
        outside = await service.thread(
            room.ctx, room.conversation.id, root.id, limit=2, before=cursor
        )
        assert outside.root.id == root.id
        assert outside.items == []
        assert outside.total == 3


@pytest.mark.security
async def test_thread_roots_must_be_top_level_non_system_messages_in_the_room(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    other = await seed(db)
    root = await message(db, room, "Root")
    reply = await message(db, room, "Reply", root=root)
    system = await message(db, room, "System", role="system")
    foreign_root = await message(db, other, "Foreign root")
    service = RoomSubmissionService(db)
    for invalid_id in (reply.id, system.id, foreign_root.id, uuid4()):
        with pytest.raises(NotFoundError):
            await service.thread(room.ctx, room.conversation.id, invalid_id)


async def test_main_history_is_opt_in_and_aggregates_are_not_limited_by_the_page(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root")
    first = await message(db, room, "First", root=root, at=AT + timedelta(seconds=1))
    second = await message(db, room, "Second", root=root, at=AT + timedelta(seconds=3))
    quote = await message(db, room, "A quote stays in main", quote=root)
    empty_root = await message(db, room, "Empty root")
    assert await conversation_repo.count_messages(db, room.conversation.id) == 5
    assert (
        await conversation_repo.count_messages(db, room.conversation.id, top_level_only=True) == 3
    )
    assert (
        await conversation_repo.count_messages(
            db, room.conversation.id, thread_root_message_id=root.id
        )
        == 2
    )
    all_rows = await conversation_repo.get_messages_by_conversation(db, room.conversation.id)
    assert [row.id for row in all_rows] == [root.id, first.id, second.id, quote.id, empty_root.id]
    page, total, _ = await ConversationService(db).transcript(
        room.conversation.id,
        organization_id=room.ctx.organization_id,
        user_id=room.user.id,
        ctx=room.ctx,
        top_level_only=True,
        include_tool_calls=True,
        limit=1,
    )
    assert [row.id for row in page] == [root.id]
    assert total == 3
    assert page[0].thread_reply_count == 2
    assert page[0].thread_last_activity_at == second.created_at
    summaries = await conversation_repo.thread_summaries(
        db, conversation_id=room.conversation.id, root_ids={root.id, quote.id, empty_root.id}
    )
    assert set(summaries) == {root.id}
    assert summaries[root.id].reply_count == 2
    assert summaries[root.id].last_activity_at == second.created_at


async def test_fork_remaps_thread_roots_and_quotes_and_keeps_only_its_prefix(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root")
    first = await message(db, room, "First", root=root, quote=root)
    main_quote = await message(db, room, "Main quote", quote=root)
    sibling = await message(db, room, "Sibling")
    sibling_reply = await message(db, room, "Sibling reply", root=sibling)
    through = await message(db, room, "Through", root=root, quote=first, role="assistant")
    await message(db, room, "Too late", root=root)
    fork = await conversation_repo.fork_conversation(
        db, source=room.conversation, through=through, copy_bytes=0
    )
    copies = await conversation_repo.get_messages_by_conversation(db, fork.id)
    by_content = {row.content: row for row in copies}
    assert list(by_content) == [
        "Root",
        "First",
        "Main quote",
        "Sibling",
        "Sibling reply",
        "Through",
    ]
    assert {row.id for row in copies}.isdisjoint(
        {root.id, first.id, main_quote.id, sibling.id, sibling_reply.id, through.id}
    )
    assert by_content["Root"].thread_root_message_id is None
    for content in ("First", "Through"):
        assert by_content[content].thread_root_message_id == by_content["Root"].id
    assert by_content["First"].reply_to_message_id == by_content["Root"].id
    assert by_content["Through"].reply_to_message_id == by_content["First"].id
    assert by_content["Main quote"].thread_root_message_id is None
    assert by_content["Main quote"].reply_to_message_id == by_content["Root"].id
    assert by_content["Sibling reply"].thread_root_message_id == by_content["Sibling"].id

    await conversation_repo.delete_message(db, root.id)
    assert await conversation_repo.count_messages(db, fork.id) == 6
    assert await db.scalar(select(Conversation.id).where(Conversation.id == fork.id)) == fork.id


@pytest.mark.parametrize("reply_count", [2, 65])
async def test_model_history_prioritizes_root_and_replies_before_earlier_main_context(
    db: AsyncSession, reply_count: int
) -> None:
    room = await seed(db)
    earlier = [await message(db, room, f"Earlier main {index}") for index in range(3)]
    old_thread = await message(db, room, "Old sibling reply", root=earlier[0])
    root = await message(db, room, "Selected root")
    sibling = await message(db, room, "Later sibling root")
    sibling_reply = await message(db, room, "Sibling reply", root=sibling)
    replies = [
        await message(db, room, f"Thread reply {index}", root=root) for index in range(reply_count)
    ]
    later_main = await message(db, room, "Later main")
    current, _ = await request(db, room, "Current request", root=root)
    await message(db, room, "Future thread reply", root=root)

    rows = await conversation_repo.get_room_history_messages(
        db, room.conversation.id, request_message_id=current.id, limit=60
    )
    assert rows is not None
    selected_replies = replies[-59:]
    remaining = 59 - len(selected_replies)
    expected = [*(earlier[-remaining:] if remaining else []), root, *selected_replies]
    assert [row.id for row in rows] == [row.id for row in expected]
    assert len(rows) <= 60
    assert not {
        old_thread.id,
        sibling.id,
        sibling_reply.id,
        later_main.id,
        current.id,
    }.intersection(row.id for row in rows)
    root_only = await conversation_repo.get_room_history_messages(
        db, room.conversation.id, request_message_id=current.id, limit=1
    )
    assert root_only is not None and [row.id for row in root_only] == [root.id]
    assert (
        await conversation_repo.get_room_history_messages(
            db, room.conversation.id, request_message_id=current.id, limit=0
        )
        == []
    )


async def test_late_agent_answers_enter_only_their_own_thread_and_preceding_request(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = await message(db, room, "Selected root")
    sibling = await message(db, room, "Sibling root")
    _, main_request = await request(db, room, "Earlier main request")
    previous, previous_request = await request(db, room, "Previous request", root=root)
    _, sibling_request = await request(db, room, "Earlier sibling request", root=sibling)
    current, _ = await request(db, room, "Current request", root=root)
    accepted = await completed_answer(db, room, previous_request, "Own late answer", root=root)
    await completed_answer(db, room, main_request, "Main late answer")
    await completed_answer(db, room, sibling_request, "Sibling late answer", root=sibling)
    _, future_request = await request(db, room, "Future request", root=root)
    await completed_answer(db, room, future_request, "Future answer", root=root)

    rows = await conversation_repo.get_room_history_messages(
        db, room.conversation.id, request_message_id=current.id, limit=60
    )
    assert rows is not None
    assert [row.id for row in rows] == [root.id, previous.id, accepted.id]
    assert previous_request.run_id is not None
    assert (
        await conversation_repo.room_thread_for_run(
            db,
            run_id=previous_request.run_id,
            conversation_id=room.conversation.id,
            organization_id=room.ctx.organization_id,
        )
        == root.id
    )


async def test_main_request_history_excludes_all_subthread_replies(db: AsyncSession) -> None:
    room = await seed(db)
    root = await message(db, room, "Root")
    await message(db, room, "Hidden thread reply", root=root)
    main = await message(db, room, "Main message")
    current, _ = await request(db, room, "Main request")
    await message(db, room, "Future main")
    rows = await conversation_repo.get_room_history_messages(
        db, room.conversation.id, request_message_id=current.id, limit=60
    )
    assert rows is not None
    assert [row.id for row in rows] == [root.id, main.id]


@pytest.mark.parametrize("root_deleted", [False, True])
async def test_answer_keeps_admitted_thread_and_deleted_root_does_not_poison_accounting(
    db: AsyncSession, root_deleted: bool
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root")
    root_id = root.id
    run = await run_repo.create_run(
        db,
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        user_id=room.user.id,
        conversation_id=room.conversation.id,
        surface="web",
        model_label=None,
        started_at=AT,
    )
    run.input_tokens = 10
    run.output_tokens = 3
    run.cost_usd = Decimal("0.25")
    await db.flush()
    if root_deleted:
        await conversation_repo.delete_message(db, root_id)

    answer_id = await TranscriptService(db).record(
        run, prompt=None, answer="Only in this thread", thread_root_message_id=root_id
    )
    if root_deleted:
        assert answer_id is None
        assert await conversation_repo.count_messages(db, room.conversation.id) == 0
    else:
        assert answer_id is not None
        assert (
            await db.scalar(select(Message.thread_root_message_id).where(Message.id == answer_id))
            == root_id
        )
        assert (
            await conversation_repo.count_messages(db, room.conversation.id, top_level_only=True)
            == 1
        )

    # The failed transcript savepoint must leave the run's outer transaction usable.
    run.status = "completed"
    await db.flush()
    status, input_tokens, cost = (
        await db.execute(
            select(AgentRun.status, AgentRun.input_tokens, AgentRun.cost_usd).where(
                AgentRun.id == run.id
            )
        )
    ).one()
    assert (status, input_tokens, cost) == ("completed", 10, Decimal("0.25"))


@pytest.mark.security
@pytest.mark.parametrize("kind", ["missing", "other_room", "other_tenant", "nested", "system"])
async def test_post_refuses_invalid_roots_before_admitting_a_message_or_agent_job(
    db: AsyncSession, kind: str
) -> None:
    room = await seed(db)
    if kind == "other_room":
        other_room = Conversation(
            id=uuid4(),
            organization_id=room.ctx.organization_id,
            user_id=room.user.id,
            project_id=room.conversation.project_id,
        )
        db.add(other_room)
        await db.flush()
        invalid = Message(
            id=uuid4(), conversation_id=other_room.id, role="user", content="Another room's root"
        )
        db.add(invalid)
        await db.flush()
        invalid_id = invalid.id
    elif kind == "other_tenant":
        other = await seed(db)
        invalid_id = (await message(db, other, "Another tenant's root")).id
    elif kind == "nested":
        root = await message(db, room, "Root")
        invalid_id = (await message(db, room, "Already a reply", root=root)).id
    elif kind == "system":
        invalid_id = (await message(db, room, "System root", role="system")).id
    else:
        invalid_id = uuid4()
    count_before = await conversation_repo.count_messages(db, room.conversation.id)
    with pytest.raises(BadRequestError, match="top-level message"):
        await RoomSubmissionService(db).post(
            room.ctx,
            room.conversation.id,
            RoomMessageCreate(
                client_message_id=uuid4().hex,
                content="Must not be admitted",
                agent_id=room.agent.id,
                thread_root_message_id=invalid_id,
            ),
            room.user,
        )
    assert await conversation_repo.count_messages(db, room.conversation.id) == count_before
    assert list(await db.scalars(select(RoomSubmission.id))) == []
    assert list(await db.scalars(select(BackgroundJob.id))) == []


@pytest.mark.parametrize("root_role", ["user", "assistant"])
async def test_thread_posts_quote_only_their_own_root_or_replies(
    db: AsyncSession, root_role: str
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root", role=root_role)
    own_reply = await message(db, room, "Own reply", root=root)
    other_root = await message(db, room, "Other main message")
    other_reply = await message(db, room, "Other thread reply", root=other_root)
    foreign_room = await seed(db)
    foreign = await message(db, foreign_room, "Foreign quote")
    service = RoomSubmissionService(db)
    for target in (root, own_reply):
        saved = await service.post(
            room.ctx,
            room.conversation.id,
            RoomMessageCreate(
                client_message_id=uuid4().hex,
                content="Quote this thread",
                thread_root_message_id=root.id,
                reply_to_message_id=target.id,
            ),
            room.user,
        )
        assert saved.message.thread_root_message_id == root.id
        assert saved.message.reply_to is not None
        assert saved.message.reply_to.message_id == target.id
        assert saved.request is None
    count_before = await conversation_repo.count_messages(db, room.conversation.id)
    for target in (other_root, other_reply, foreign):
        with pytest.raises(BadRequestError):
            await service.post(
                room.ctx,
                room.conversation.id,
                RoomMessageCreate(
                    client_message_id=uuid4().hex,
                    content="Must not cross thread scope",
                    thread_root_message_id=root.id,
                    reply_to_message_id=target.id,
                ),
                room.user,
            )
    assert await conversation_repo.count_messages(db, room.conversation.id) == count_before
    assert len(list(await db.scalars(select(RoomSubmission.id)))) == 2
    assert list(await db.scalars(select(BackgroundJob.id))) == []


async def test_retry_retains_its_thread_and_quote_alone_does_not_create_one(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root")
    other_root = await message(db, room, "Other root")
    service = RoomSubmissionService(db)
    payload = RoomMessageCreate(
        client_message_id=uuid4().hex,
        content="One durable request",
        agent_id=room.agent.id,
        thread_root_message_id=root.id,
    )
    saved = await service.post(room.ctx, room.conversation.id, payload, room.user)
    retried = await service.post(room.ctx, room.conversation.id, payload, room.user)
    assert saved.message.id == retried.message.id
    assert saved.request is not None and retried.request is not None
    assert saved.request.id == retried.request.id
    assert saved.request.thread_root_message_id == root.id
    assert saved.message.thread_root_message_id == root.id
    for changed_scope in (other_root.id, None):
        with pytest.raises(AlreadyExistsError):
            await service.post(
                room.ctx,
                room.conversation.id,
                payload.model_copy(update={"thread_root_message_id": changed_scope}),
                room.user,
            )
    assert await conversation_repo.count_messages(db, room.conversation.id) == 3
    assert len(list(await db.scalars(select(RoomSubmission.id)))) == 1
    [job] = list(await db.scalars(select(BackgroundJob)))
    assert job.concurrency_key == f"room:{room.conversation.id}"

    quoted_in_main = await service.post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id=uuid4().hex, content="Only a quote", reply_to_message_id=root.id
        ),
        room.user,
    )
    assert quoted_in_main.message.thread_root_message_id is None
    assert quoted_in_main.message.reply_to is not None
    assert quoted_in_main.message.reply_to.message_id == root.id
    assert quoted_in_main.request is None


@pytest.mark.parametrize("summarized", [False, True])
async def test_ordinary_main_model_history_excludes_replies_even_after_a_summary(
    db: AsyncSession, summarized: bool
) -> None:
    room = await seed(db)
    root = await message(db, room, "Main root context")
    await message(db, room, "Hidden subthread context", root=root)
    await message(db, room, "Main continuation context")
    if summarized:
        room.conversation.summary_messages = ModelMessagesTypeAdapter.dump_python(
            [ModelRequest(parts=[UserPromptPart("Main root context")])], mode="json"
        )
        room.conversation.summary_ordinal = root.ordinal
        await db.flush()

    history = await ConversationService(db).model_history(room.conversation.id, limit=60)
    serialized = json.dumps(ModelMessagesTypeAdapter.dump_python(history, mode="json"))
    assert "Main root context" in serialized
    assert "Main continuation context" in serialized
    assert "Hidden subthread context" not in serialized


@pytest.mark.security
async def test_project_reader_can_read_thread_but_cannot_post_or_enqueue(db: AsyncSession) -> None:
    room = await seed(db)
    root = await message(db, room, "Thread root")
    reply = await message(db, room, "Existing reply", root=root)
    reader = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(reader)
    await db.flush()
    assert room.conversation.project_id is not None
    db.add_all(
        [
            OrganizationMember(
                id=uuid4(),
                organization_id=room.ctx.organization_id,
                user_id=reader.id,
                role="member",
            ),
            ResourceGrant(
                organization_id=room.ctx.organization_id,
                resource_type="project",
                resource_id=room.conversation.project_id,
                subject_user_id=reader.id,
                level="read",
            ),
        ]
    )
    await db.flush()
    ctx = AuthContext(user_id=reader.id, organization_id=room.ctx.organization_id, role="member")
    service = RoomSubmissionService(db)

    page = await service.thread(ctx, room.conversation.id, root.id)
    assert page.root.id == root.id
    assert [row.id for row in page.items] == [reply.id]
    assert page.total == 1
    assert not page.can_post
    with pytest.raises(NotFoundError, match="Conversation not found"):
        await service.post(
            ctx,
            room.conversation.id,
            RoomMessageCreate(
                client_message_id=uuid4().hex,
                content="A reader must not enqueue an agent",
                thread_root_message_id=root.id,
                agent_id=room.agent.id,
            ),
            reader,
        )
    assert await conversation_repo.count_messages(db, room.conversation.id) == 2
    assert list(await db.scalars(select(RoomSubmission.id))) == []
    assert list(await db.scalars(select(BackgroundJob.id))) == []


@pytest.mark.security
async def test_detached_thread_stays_readable_by_starter_but_not_its_former_project_member(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    root = await message(db, room, "Main context retained after project deletion")
    peer = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(peer)
    await db.flush()
    project = await db.get(Project, room.conversation.project_id)
    assert project is not None
    db.add_all(
        [
            OrganizationMember(
                id=uuid4(), organization_id=room.ctx.organization_id, user_id=peer.id, role="member"
            ),
            ResourceGrant(
                organization_id=room.ctx.organization_id,
                resource_type="project",
                resource_id=project.id,
                subject_user_id=peer.id,
                level="use",
            ),
        ]
    )
    await db.flush()
    peer_ctx = AuthContext(user_id=peer.id, organization_id=room.ctx.organization_id, role="member")
    service = RoomSubmissionService(db)
    posted = await service.post(
        peer_ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id=uuid4().hex,
            content="Existing subthread reply",
            thread_root_message_id=root.id,
        ),
        peer,
    )
    before = await service.thread(peer_ctx, room.conversation.id, root.id)
    assert before.can_post
    assert [row.id for row in before.items] == [posted.message.id]

    await project_repo.detach_conversations(db, project=project)
    await project_repo.delete(db, project)
    await db.refresh(room.conversation)
    assert room.conversation.project_id is None

    kept = await service.thread(room.ctx, room.conversation.id, root.id)
    assert kept.root.id == root.id
    assert [row.id for row in kept.items] == [posted.message.id]
    assert kept.total == 1
    assert not kept.can_post
    with pytest.raises(NotFoundError):
        await service.thread(peer_ctx, room.conversation.id, root.id)
    with pytest.raises(BadRequestError, match="project chat"):
        await service.post(
            room.ctx,
            room.conversation.id,
            RoomMessageCreate(
                client_message_id=uuid4().hex,
                content="Must not reopen detached thread",
                thread_root_message_id=root.id,
            ),
            room.user,
        )
    history = await ConversationService(db).model_history(room.conversation.id, limit=60)
    serialized = json.dumps(ModelMessagesTypeAdapter.dump_python(history, mode="json"))
    assert "Main context retained after project deletion" in serialized
    assert "Existing subthread reply" not in serialized


async def source_run(db: AsyncSession, room: Room) -> AgentRun:
    run = await run_repo.create_run(
        db,
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        user_id=room.user.id,
        conversation_id=room.conversation.id,
        surface="web",
        model_label=None,
        started_at=AT,
    )
    run.status = "completed"
    await db.flush()
    return run


@pytest.mark.security
@pytest.mark.parametrize("parked_status", ["awaiting_answer", "awaiting_approval"])
async def test_legacy_park_keeps_thread_agent_queued_but_allows_its_resume_and_human_posts(
    db: AsyncSession, parked_status: str
) -> None:
    room = await seed(db)
    root = await message(db, room, "A new subthread root")
    legacy = await source_run(db, room)
    legacy.status = parked_status
    await message(
        db, room, "Legacy main run waiting for its person", role="assistant", run_id=legacy.id
    )
    service = RoomSubmissionService(db)
    human = await service.post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id=uuid4().hex,
            content="People can still discuss the thread",
            thread_root_message_id=root.id,
        ),
        room.user,
    )
    queued = await service.post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id=uuid4().hex,
            content="Ask the thread agent after the legacy run finishes",
            thread_root_message_id=root.id,
            agent_id=room.agent.id,
        ),
        room.user,
    )
    assert human.request is None
    assert human.message.thread_root_message_id == root.id
    assert queued.request is not None and queued.request.status == "queued"
    assert (
        await task_repo.claim_turn(
            db, room.conversation.id, background=True, room_request_id=queued.request.id
        )
        is None
    )
    assert (
        await task_repo.claim_turn(
            db, room.conversation.id, background=False, resume_run_id=uuid4()
        )
        is None
    )

    # The queued head must not strand the older run that it is waiting for.
    resumed = await task_repo.claim_turn(
        db, room.conversation.id, background=False, resume_run_id=legacy.id
    )
    assert resumed is not None
    assert (
        await task_repo.claim_turn(
            db, room.conversation.id, background=True, room_request_id=queued.request.id
        )
        is None
    )
    await task_repo.release_turn(db, resumed)
    legacy.status = "completed"
    await db.flush()

    admitted = await task_repo.claim_turn(
        db, room.conversation.id, background=True, room_request_id=queued.request.id
    )
    assert admitted is not None
    await task_repo.release_turn(db, admitted)
    assert len(list(await db.scalars(select(BackgroundJob.id)))) == 1


@pytest.mark.security
@pytest.mark.parametrize("kind", ["main", "thread", "missing", "mixed"])
async def test_task_source_scope_requires_consistent_surviving_rows_in_its_tenant(
    db: AsyncSession, kind: str
) -> None:
    room = await seed(db)
    root = await message(db, room, "Root")
    source = await source_run(db, room)
    if kind in {"main", "mixed"}:
        await message(db, room, "Main source segment", role="assistant", run_id=source.id)
    if kind in {"thread", "mixed"}:
        await message(
            db, room, "Thread source segment", root=root, role="assistant", run_id=source.id
        )
    scope = await conversation_repo.message_scope_for_run(
        db,
        run_id=source.id,
        conversation_id=room.conversation.id,
        organization_id=room.ctx.organization_id,
    )
    if kind in {"missing", "mixed"}:
        assert scope is None
    else:
        assert scope is not None
        assert scope.thread_root_message_id == (root.id if kind == "thread" else None)
    assert (
        await conversation_repo.message_scope_for_run(
            db,
            run_id=source.id,
            conversation_id=room.conversation.id,
            organization_id=uuid4(),
        )
        is None
    )
    assert (
        await conversation_repo.message_scope_for_run(
            db,
            run_id=source.id,
            conversation_id=uuid4(),
            organization_id=room.ctx.organization_id,
        )
        is None
    )


@pytest.mark.parametrize("state", ["main", "thread", "deleted", "detached", "archived"])
async def test_task_result_rechecks_its_source_discussion_before_returning(
    db: AsyncSession, state: str
) -> None:
    room = await seed(db)
    root = await message(db, room, "Source root")
    source = await source_run(db, room)
    await message(
        db,
        room,
        "The original delegation",
        root=None if state == "main" else root,
        role="assistant",
        run_id=source.id,
    )
    topic = Conversation(id=uuid4(), organization_id=room.ctx.organization_id, user_id=room.user.id)
    db.add(topic)
    await db.flush()
    task = ConversationTask(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        user_id=room.user.id,
        source_conversation_id=room.conversation.id,
        conversation_id=topic.id,
        source_run_id=source.id,
        source_agent_id=room.agent.id,
        source_version_id=room.version.id,
        agent_id=room.agent.id,
        version_id=room.version.id,
        tool_call_id=uuid4().hex,
        title="Delegated work",
        prompt="Return this result to its source discussion",
        status="completed",
        delivery="pending",
    )
    db.add(task)
    await db.flush()
    if state == "deleted":
        await conversation_repo.delete_message(db, root.id)
    elif state == "detached":
        project = await db.get(Project, room.conversation.project_id)
        assert project is not None
        await project_repo.detach_conversations(db, project=project)
        await project_repo.delete(db, project)
        await db.refresh(room.conversation)
    elif state == "archived":
        room.conversation.is_archived = True
        await db.flush()

    service = ConversationTaskService(db)
    if state in {"main", "thread"}:
        ctx, destination = await service.return_context(task)
        assert ctx.subject_id == room.user.id
        assert ctx.organization_id == room.ctx.organization_id
        assert destination == (None if state == "main" else root.id)
    else:
        with pytest.raises(NotFoundError):
            await service.return_context(task)
    assert task.return_run_id is None
    assert list(await db.scalars(select(BackgroundJob.id))) == []


@pytest.mark.parametrize("reply_count", [2, 65])
async def test_current_thread_history_for_task_return_is_bounded_and_ignores_main_summary(
    db: AsyncSession, reply_count: int
) -> None:
    room = await seed(db)
    earlier = [await message(db, room, f"Earlier main {index}") for index in range(3)]
    root = await message(db, room, "Selected root")
    sibling = await message(db, room, "Later sibling root")
    await message(db, room, "Excluded sibling reply", root=sibling)
    replies = [
        await message(db, room, f"Selected reply {index}", root=root)
        for index in range(reply_count)
    ]
    await message(db, room, "Excluded later main")
    room.conversation.summary_messages = ModelMessagesTypeAdapter.dump_python(
        [ModelRequest(parts=[UserPromptPart("Excluded main summary")])], mode="json"
    )
    room.conversation.summary_ordinal = replies[-1].ordinal
    await db.flush()

    rows = await conversation_repo.get_thread_history_messages(
        db,
        room.conversation.id,
        root_message_id=root.id,
        limit=60,
    )
    selected_replies = replies[-59:]
    remaining = 59 - len(selected_replies)
    expected = [*(earlier[-remaining:] if remaining else []), root, *selected_replies]
    assert rows is not None
    assert [row.id for row in rows] == [row.id for row in expected]
    history = await ConversationService(db).model_history(
        room.conversation.id,
        limit=60,
        thread_root_message_id=root.id,
    )
    serialized = json.dumps(ModelMessagesTypeAdapter.dump_python(history, mode="json"))
    assert "Selected root" in serialized
    assert replies[-1].content in serialized
    assert "Excluded" not in serialized
    assert "Later sibling root" not in serialized
    assert (
        await conversation_repo.get_thread_history_messages(
            db,
            room.conversation.id,
            root_message_id=root.id,
            limit=0,
        )
        == []
    )
    assert (
        await conversation_repo.get_thread_history_messages(
            db,
            room.conversation.id,
            root_message_id=uuid4(),
            limit=60,
        )
        is None
    )
