"""Range snapshots remain complete and fence stale model projections."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.guardrails import GuardrailBlocked
from app.db.models.conversation import Conversation, Message
from app.db.models.room_submission import RoomSubmission
from app.db.models.room_thread import RoomThread
from app.repositories import agent_run as run_repo
from app.repositories import conversation as conversation_repo
from app.schemas.room_submission import RoomMessageCreate
from app.services.conversation import ConversationService, check_history_snapshot
from app.services.message_history import ModelHistory
from app.services.room_submission import RoomSubmissionService, fingerprint
from tests.integration.test_room_submissions import Room, seed

pytestmark = pytest.mark.anyio


async def context_rows(
    db: AsyncSession, room: Room, *, count: int = 500, moved: bool = False
) -> tuple[list[Message], Message, RoomThread]:
    rows = [
        Message(
            id=uuid4(),
            conversation_id=room.conversation.id,
            role="user",
            content=f"Selected message {index}",
            author_user_id=room.user.id,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for index in range(count)
    ]
    db.add_all(rows)
    await db.flush()
    root = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Selected context",
        author_user_id=room.user.id,
    )
    db.add(root)
    await db.flush()
    thread = RoomThread(
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        root_message_id=root.id,
        context_source_conversation_id=room.conversation.id,
        context_start_message_id=rows[0].id,
        context_end_message_id=rows[-1].id,
        context_first_ordinal=rows[0].ordinal,
        context_last_ordinal=rows[-1].ordinal,
        context_excluded_message_ids=[],
        context_message_ids=[row.id for row in rows],
        context_moved=moved,
        context_revision=1,
    )
    db.add(thread)
    if moved:
        for row in rows:
            row.thread_root_message_id = root.id
    await db.flush()
    return rows, root, thread


@pytest.mark.parametrize("moved", [False, True])
async def test_a_saved_five_hundred_message_range_is_not_trimmed_to_the_room_window(
    db: AsyncSession, moved: bool
) -> None:
    room = await seed(db)
    selected, root, _ = await context_rows(db, room, moved=moved)
    reply = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        thread_root_message_id=root.id,
        role="user",
        content="The actual thread reply",
        author_user_id=room.user.id,
    )
    db.add(reply)
    await db.flush()

    history = await conversation_repo.get_thread_history_messages(
        db, room.conversation.id, root_message_id=root.id, limit=60
    )
    assert history is not None
    assert [row.id for row in history] == [*[row.id for row in selected], root.id, reply.id]
    page = await RoomSubmissionService(db).thread(room.ctx, room.conversation.id, root.id)
    assert [row.id for row in page.context_messages] == [row.id for row in selected]
    assert [row.id for row in page.items] == [reply.id]
    assert page.total == page.root.thread_reply_count == 1


async def test_a_moved_prompt_keeps_its_accepted_request_scope(db: AsyncSession) -> None:
    room = await seed(db)
    selected, root, _ = await context_rows(db, room, count=2, moved=True)
    run = await run_repo.create_run(
        db,
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        user_id=room.user.id,
        conversation_id=room.conversation.id,
        surface="web",
        model_label=None,
        started_at=datetime.now(UTC),
    )
    run.status = "completed"
    payload = RoomMessageCreate(
        client_message_id=uuid4().hex, content=selected[0].content, agent_id=room.agent.id
    )
    accepted = RoomSubmission(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        requester_id=room.user.id,
        message_id=selected[0].id,
        thread_root_message_id=None,
        client_message_id=payload.client_message_id,
        fingerprint=fingerprint(payload),
        agent_id=room.agent.id,
        version_id=room.version.id,
        run_id=run.id,
        status="completed",
    )
    db.add(accepted)
    await db.flush()
    await db.refresh(accepted)

    assert selected[0].thread_root_message_id == root.id
    assert accepted.thread_root_message_id is None
    assert (
        await conversation_repo.room_thread_for_run(
            db,
            run_id=run.id,
            conversation_id=room.conversation.id,
            organization_id=room.ctx.organization_id,
        )
        is None
    )
    assert (
        await conversation_repo.get_room_history_messages(
            db,
            room.conversation.id,
            request_message_id=selected[0].id,
            request_id=accepted.id,
            limit=60,
        )
        == []
    )


async def test_a_topology_change_clears_summary_and_refuses_an_old_projection(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    room.conversation.summary_messages = []
    room.conversation.summary_ordinal = 0
    await db.flush()
    before = await conversation_repo.get_guardrail_revision(db, room.conversation.id)
    assert before is not None
    old_history = ModelHistory([], revision=before)

    await conversation_repo.invalidate_thread_context_history(
        db, conversation_ids={room.conversation.id}
    )
    await db.refresh(room.conversation)

    assert room.conversation.summary_messages is None
    assert room.conversation.summary_ordinal is None
    assert await conversation_repo.get_guardrail_revision(db, room.conversation.id) == before + 1
    with pytest.raises(GuardrailBlocked):
        await check_history_snapshot(db, room.conversation.id, old_history)
    assert not await conversation_repo.set_summary(
        db, db_conversation=room.conversation, messages=[], ordinal=0, expected_revision=before
    )
    assert room.conversation.summary_messages is None


@pytest.mark.security
async def test_a_source_refusal_fences_a_destination_that_references_the_source(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    selected, source_root, _ = await context_rows(db, room, count=2)
    destination = Conversation(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        user_id=room.user.id,
        project_id=room.conversation.project_id,
    )
    db.add(destination)
    await db.flush()
    destination_root = Message(
        id=uuid4(),
        conversation_id=destination.id,
        author_user_id=room.user.id,
        role="user",
        content="External context",
    )
    db.add(destination_root)
    await db.flush()
    db.add(
        RoomThread(
            organization_id=room.ctx.organization_id,
            conversation_id=destination.id,
            root_message_id=destination_root.id,
            context_source_conversation_id=room.conversation.id,
            context_start_message_id=selected[0].id,
            context_end_message_id=selected[-1].id,
            context_first_ordinal=selected[0].ordinal,
            context_last_ordinal=selected[-1].ordinal,
            context_excluded_message_ids=[],
            context_message_ids=[row.id for row in selected],
            context_moved=False,
            context_revision=1,
        )
    )
    await db.flush()
    before = await conversation_repo.get_guardrail_revision(db, destination.id)
    assert before is not None
    history = ModelHistory([], revision=before)
    run = await run_repo.create_run(
        db,
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        user_id=room.user.id,
        conversation_id=room.conversation.id,
        surface="web",
        model_label=None,
        started_at=datetime.now(UTC),
    )
    selected[0].run_id = run.id
    await db.flush()
    await conversation_repo.mark_run_messages_refused(db, run_id=run.id)

    assert await conversation_repo.get_guardrail_revision(db, destination.id) == before + 1
    with pytest.raises(GuardrailBlocked):
        await check_history_snapshot(db, destination.id, history)
    refreshed = await ConversationService(db).model_history(
        destination.id, limit=60, thread_root_message_id=destination_root.id
    )
    assert refreshed.revision == before + 1
    assert await db.scalar(select(Message.guardrail_refused).where(Message.id == selected[0].id))
    assert source_root.conversation_id != destination_root.conversation_id


@pytest.mark.security
async def test_excluded_context_cannot_return_through_an_automatic_quote(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    selected, root, thread = await context_rows(db, room, count=3)
    selected[0].content = "EXCLUDED_CONTEXT_SECRET"
    selected[1].reply_to_message_id = selected[0].id
    selected[1].reply_to_excerpt = "EXCLUDED_CONTEXT_SECRET"
    thread.context_excluded_message_ids = [selected[0].id]
    thread.context_message_ids = [row.id for row in selected[1:]]
    await db.flush()

    history = await ConversationService(db).model_history(
        room.conversation.id, limit=60, thread_root_message_id=root.id
    )

    text = "\n".join(str(part.content) for message in history for part in message.parts)
    assert "Selected message 1" in text
    assert "Selected message 2" in text
    assert "EXCLUDED_CONTEXT_SECRET" not in text


async def test_moved_stubs_survive_when_only_the_new_marker_remains(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    selected, root, _ = await context_rows(db, room, count=3, moved=True)

    stubs = await conversation_repo.moved_thread_stubs(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        page_message_ids=[root.id],
        before=None,
        latest=True,
    )

    assert len(stubs) == 1
    assert stubs[0][0].root_message_id == root.id
    assert stubs[0][0].context_first_ordinal == selected[0].ordinal
    assert stubs[0][1] == root.content


async def test_moved_stubs_appear_on_the_page_containing_their_original_position(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    earlier = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="Before the selected range",
        author_user_id=room.user.id,
    )
    db.add(earlier)
    await db.flush()
    _, root, _ = await context_rows(db, room, count=3, moved=True)
    latest = Message(
        id=uuid4(),
        conversation_id=room.conversation.id,
        role="user",
        content="After the range marker",
        author_user_id=room.user.id,
    )
    db.add(latest)
    await db.flush()

    newest = await conversation_repo.moved_thread_stubs(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        page_message_ids=[latest.id],
        before=None,
        latest=True,
    )
    older = await conversation_repo.moved_thread_stubs(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        page_message_ids=[earlier.id, root.id],
        before=latest.id,
        latest=True,
    )

    assert newest == []
    assert [row.root_message_id for row, _ in older] == [root.id]


@pytest.mark.security
async def test_a_deleted_middle_context_row_refuses_history_and_fences_the_old_snapshot(
    db: AsyncSession,
) -> None:
    from app.core.exceptions import ConflictError
    from app.services.room_thread_context_read import RoomThreadContextReadService

    room = await seed(db)
    selected, root, _ = await context_rows(db, room, count=3)
    old_history = await ConversationService(db).model_history(
        room.conversation.id, limit=60, thread_root_message_id=root.id
    )

    assert await conversation_repo.delete_message(db, selected[1].id)

    with pytest.raises(GuardrailBlocked):
        await check_history_snapshot(db, room.conversation.id, old_history)
    with pytest.raises(ConflictError, match="saved context changed"):
        await RoomThreadContextReadService(db).assert_history(
            destination=room.conversation, root_message_id=root.id, actor=room.ctx
        )
    context, visible = await RoomThreadContextReadService(db).detail(
        room.ctx, room.conversation.id, root.id
    )
    assert context is not None and context.stale
    assert context.message_ids == [row.id for row in selected]
    assert visible == []
    candidates = await RoomThreadContextReadService(db).candidates(
        room.ctx, room.conversation.id, root.id
    )
    assert [row.id for row in candidates.items] == [selected[0].id, selected[2].id]
    assert (
        await conversation_repo.get_thread_history_messages(
            db, room.conversation.id, root_message_id=root.id, limit=60
        )
        is None
    )


@pytest.mark.parametrize("moved,protected", [(False, "boundary"), (True, "middle"), (True, "root")])
async def test_deleting_saved_boundaries_or_moved_context_preserves_originals(
    db: AsyncSession, moved: bool, protected: str
) -> None:
    from app.core.exceptions import ConflictError

    room = await seed(db)
    selected, root, _ = await context_rows(db, room, count=3, moved=moved)
    message_id = {
        "boundary": selected[0].id,
        "middle": selected[1].id,
        "root": root.id,
    }[protected]

    with pytest.raises(ConflictError, match="saved thread context"):
        await ConversationService(db).delete_message(message_id)

    remaining = await db.scalars(
        select(Message.id).where(Message.conversation_id == room.conversation.id)
    )
    assert set(remaining.all()) == {root.id, *(row.id for row in selected)}
