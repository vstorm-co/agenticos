"""PostgreSQL enforces room dedupe, queue order and exclusive turn admission."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred
from app.core.exceptions import AlreadyExistsError, AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.project import Project
from app.db.models.room_submission import RoomSubmission
from app.db.models.user import User
from app.repositories import agent_run as run_repo
from app.repositories import conversation_task as turn_repo
from app.repositories import room_submission as room_repo
from app.schemas.room_submission import RoomMessageCreate
from app.services.room_submission import RoomSubmissionService
from app.worker.jobs import RUN_ROOM_REQUEST

pytestmark = pytest.mark.anyio


@dataclass
class Room:
    ctx: AuthContext
    user: User
    conversation: Conversation
    agent: Agent
    version: AgentVersion
    member: OrganizationMember


async def seed(db: AsyncSession) -> Room:
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Room test", slug=f"room-{uuid4().hex}", created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    member = OrganizationMember(id=uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    project = Project(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        name="Room project",
        backend="state",
        visibility="private",
    )
    agent = Agent(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        slug=f"agent-{uuid4().hex}",
        name="Responder",
        status="published",
        draft_spec={},
    )
    db.add_all([member, project, agent])
    await db.flush()
    version = AgentVersion(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={"name": "Responder", "model_profile_id": str(uuid4())},
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    conversation = Conversation(
        id=uuid4(), organization_id=org.id, user_id=user.id, project_id=project.id
    )
    db.add(conversation)
    await db.flush()
    return Room(
        AuthContext(user_id=user.id, organization_id=org.id, role="owner"),
        user,
        conversation,
        agent,
        version,
        member,
    )


async def post(db: AsyncSession, room: Room, token: str, *, agent: bool = True):
    return await RoomSubmissionService(db).post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id=token,
            content=f"Message {token}",
            agent_id=room.agent.id if agent else None,
        ),
        room.user,
    )


@pytest.mark.security
async def test_posts_and_queue_are_atomic_idempotent_and_tenant_scoped(db: AsyncSession) -> None:
    room = await seed(db)
    human = await post(db, room, "human", agent=False)
    first = await post(db, room, "agent")
    again = await post(db, room, "agent")
    assert human.request is None and first == again
    assert (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == room.conversation.id)
        )
        == 2
    )
    assert (
        await db.scalar(
            select(func.count())
            .select_from(BackgroundJob)
            .where(BackgroundJob.kind == RUN_ROOM_REQUEST.kind)
        )
        == 1
    )
    assert first.request is not None
    stored = await room_repo.get(db, first.request.id, organization_id=room.ctx.organization_id)
    assert stored is not None and stored.version_id == room.version.id
    assert stored.requester_id == room.ctx.user_id and stored.job_id is not None
    job = await db.get(BackgroundJob, stored.job_id)
    assert job is not None and job.max_attempts == 1
    assert job.concurrency_key == f"room:{room.conversation.id}"
    assert await room_repo.get(db, stored.id, organization_id=uuid4()) is None
    with pytest.raises(AlreadyExistsError):
        await RoomSubmissionService(db).post(
            room.ctx,
            room.conversation.id,
            RoomMessageCreate(
                client_message_id="agent", content="Different", agent_id=room.agent.id
            ),
            room.user,
        )
    discard_deferred(db)


async def test_first_request_and_parked_resume_exclude_legacy_and_later_turns(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    first, second = await post(db, room, "a"), await post(db, room, "b")
    assert first.request is not None and second.request is not None
    assert await turn_repo.claim_turn(db, room.conversation.id, background=False) is None
    assert (
        await turn_repo.claim_turn(
            db, room.conversation.id, background=True, room_request_id=second.request.id
        )
        is None
    )
    claim = await turn_repo.claim_turn(
        db, room.conversation.id, background=True, room_request_id=first.request.id
    )
    assert claim is not None
    assert (
        await turn_repo.claim_turn(
            db, room.conversation.id, background=True, room_request_id=first.request.id
        )
        is None
    )
    await turn_repo.release_turn(db, claim)
    row = await room_repo.get(
        db, first.request.id, organization_id=room.ctx.organization_id, lock=True
    )
    assert row is not None
    run = await run_repo.create_run(
        db,
        organization_id=room.ctx.organization_id,
        agent_id=room.agent.id,
        agent_version_id=room.version.id,
        user_id=room.user.id,
        conversation_id=room.conversation.id,
        surface="web",
        model_label="test",
        provider="test",
        started_at=datetime.now(UTC),
    )
    row.run_id, row.status = run.id, "awaiting_answer"
    await room_repo.save(db, row)
    assert await room_repo.for_run(db, run.id, organization_id=room.ctx.organization_id) is row
    assert await turn_repo.claim_turn(db, room.conversation.id, background=False) is None
    resumed = await turn_repo.claim_turn(
        db, room.conversation.id, background=False, resume_run_id=run.id
    )
    assert resumed is not None
    await turn_repo.release_turn(db, resumed)
    row.status = "completed"
    await room_repo.save(db, row)
    assert [item.id for item in await room_repo.ready(db)] == [second.request.id]
    later = await turn_repo.claim_turn(
        db, room.conversation.id, background=True, room_request_id=second.request.id
    )
    assert later is not None
    await turn_repo.release_turn(db, later)
    discard_deferred(db)


async def test_lost_membership_refuses_execution_and_queue_keeps_active_head_visible(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    first = await post(db, room, "first")
    assert first.request is not None
    row = await room_repo.get(db, first.request.id, organization_id=room.ctx.organization_id)
    assert row is not None
    for i in range(51):
        result = await post(db, room, str(i))
        assert result.request is not None
        await RoomSubmissionService(db).cancel(room.ctx, room.conversation.id, result.request.id)
    listed, total = await room_repo.list_requests(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        skip=0,
        limit=50,
    )
    assert total == 52 and listed[0].id == row.id
    await db.delete(room.member)
    await db.flush()
    with pytest.raises(AuthorizationError):
        await RoomSubmissionService(db).authority(row)
    discard_deferred(db)


async def test_reconciliation_selects_only_changed_active_runs_in_queue_order(
    db: AsyncSession,
) -> None:
    room = await seed(db)
    expected = []
    for index, (request_status, run_status) in enumerate(
        [
            ("running", "completed"),
            ("awaiting_approval", "running"),
            ("awaiting_answer", "cancelled"),
            ("running", "running"),
            ("awaiting_approval", "awaiting_approval"),
            ("awaiting_answer", "awaiting_answer"),
            ("queued", "completed"),
            ("completed", "running"),
        ]
    ):
        result = await post(db, room, f"reconcile-{index}")
        assert result.request is not None
        row = await room_repo.get(db, result.request.id, organization_id=room.ctx.organization_id)
        assert row is not None
        run = await run_repo.create_run(
            db,
            organization_id=room.ctx.organization_id,
            agent_id=room.agent.id,
            agent_version_id=room.version.id,
            user_id=room.user.id,
            conversation_id=room.conversation.id,
            surface="web",
            model_label="test",
            provider="test",
            started_at=datetime.now(UTC),
        )
        run.status = run_status
        row.run_id, row.status = run.id, request_status
        await room_repo.save(db, row)
        if index < 3:
            expected.append((row.id, run.id))

    without_run = await post(db, room, "no-run")
    assert without_run.request is not None
    row = await room_repo.get(db, without_run.request.id, organization_id=room.ctx.organization_id)
    assert row is not None
    row.status = "running"
    await room_repo.save(db, row)

    selected = await room_repo.unsettled_runs(db)
    assert [(submission.id, run.id) for submission, run in selected] == expected
    assert [submission.ordinal for submission, _ in selected] == sorted(
        submission.ordinal for submission, _ in selected
    )
    discard_deferred(db)


async def test_concurrent_http_retries_persist_one_message_and_one_request(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    room = await seed(db)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def retry():
        async with factory() as session:
            try:
                result = await post(session, room, "same")
                await session.commit()
                return result
            finally:
                discard_deferred(session)

    a, b = await asyncio.gather(retry(), retry())
    assert a == b
    assert (
        await db.scalar(
            select(func.count())
            .select_from(RoomSubmission)
            .where(RoomSubmission.conversation_id == room.conversation.id)
        )
        == 1
    )


async def seed_multiplayer(db: AsyncSession):
    from app.schemas.room_participant import RoomParticipantRef
    from app.services.room_participant import RoomParticipantService

    room = await seed(db)
    room.conversation.project_id = None
    second = Agent(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        owner_user_id=room.user.id,
        slug=f"agent-{uuid4().hex}",
        name="Reviewer",
        status="published",
        draft_spec={},
    )
    person = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add_all([second, person])
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid4(), organization_id=room.ctx.organization_id, user_id=person.id, role="viewer"
        )
    )
    version = AgentVersion(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        agent_id=second.id,
        version=1,
        spec={"name": "Reviewer", "model_profile_id": str(uuid4())},
    )
    db.add(version)
    await db.flush()
    second.current_version_id = version.id
    await db.flush()
    roster = RoomParticipantService(db)
    for kind, principal in (("agent", room.agent.id), ("agent", second.id), ("user", person.id)):
        await roster.add(
            room.ctx, room.conversation.id, RoomParticipantRef(kind=kind, id=principal)
        )
    return room, second, person


@pytest.mark.security
async def test_multi_bot_post_retries_preserve_one_message_and_two_ordered_jobs(db: AsyncSession):
    from app.db.models.notification import Notification, NotificationEventType
    from app.schemas.room_participant import RoomParticipantRef

    room, second, person = await seed_multiplayer(db)
    service = RoomSubmissionService(db)
    data = RoomMessageCreate(
        client_message_id="multi",
        content="@Responder @Reviewer @Alex compare the approaches",
        mentions=[
            RoomParticipantRef(kind="agent", id=room.agent.id),
            RoomParticipantRef(kind="agent", id=second.id),
            RoomParticipantRef(kind="user", id=person.id),
        ],
    )
    first = await service.post(room.ctx, room.conversation.id, data, room.user)
    again = await service.post(room.ctx, room.conversation.id, data, room.user)
    assert first == again and len(first.requests) == 2
    root = await room_repo.for_client(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        requester_id=room.user.id,
        client_message_id="multi",
    )
    assert root is not None
    rows = await room_repo.for_post(db, root=root)
    assert [row.agent_id for row in rows] == [room.agent.id, second.id]
    assert rows[1].parent_submission_id == rows[0].id
    assert rows[0].ordinal < rows[1].ordinal
    assert {row.message_id for row in rows} == {first.message.id}
    assert (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == room.conversation.id)
        )
        == 1
    )
    jobs = list(
        (
            await db.scalars(
                select(BackgroundJob).where(
                    BackgroundJob.kind == RUN_ROOM_REQUEST.kind,
                    BackgroundJob.organization_id == room.ctx.organization_id,
                )
            )
        ).all()
    )
    assert len(jobs) == 2 and len({job.dedupe_key for job in jobs}) == 2
    notices = list(
        (
            await db.scalars(
                select(Notification).where(
                    Notification.event_type == NotificationEventType.ROOM_MENTION,
                    Notification.organization_id == room.ctx.organization_id,
                )
            )
        ).all()
    )
    assert len(notices) == 1 and notices[0].recipient_user_id == person.id
    assert notices[0].occurrence_id == str(first.message.id)
    assert await room_repo.head(db, room.conversation.id) is rows[0]
    discard_deferred(db)


@pytest.mark.security
async def test_second_bot_history_includes_first_answer_but_not_later_human_questions(
    db: AsyncSession,
):
    from app.repositories import conversation as conversation_repo
    from app.schemas.room_participant import RoomParticipantRef

    room, second, _ = await seed_multiplayer(db)
    result = await RoomSubmissionService(db).post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id="shared",
            content="Please compare",
            mentions=[
                RoomParticipantRef(kind="agent", id=agent.id) for agent in (room.agent, second)
            ],
        ),
        room.user,
    )
    root = await room_repo.get(db, result.requests[0].id, organization_id=room.ctx.organization_id)
    child = await room_repo.get(db, result.requests[1].id, organization_id=room.ctx.organization_id)
    assert root is not None and child is not None
    later = await post(db, room, "later", agent=False)
    runs = []
    answers = []
    for row, agent in ((root, room.agent), (child, second)):
        run = await run_repo.create_run(
            db,
            organization_id=room.ctx.organization_id,
            agent_id=agent.id,
            agent_version_id=row.version_id,
            user_id=room.user.id,
            conversation_id=room.conversation.id,
            surface="web",
            model_label="test",
            provider="test",
            started_at=datetime.now(UTC),
        )
        row.run_id, row.status = run.id, "completed"
        await room_repo.save(db, row)
        answer = Message(
            id=uuid4(),
            conversation_id=room.conversation.id,
            role="assistant",
            content=f"{agent.name} answer",
            agent_id=agent.id,
            run_id=run.id,
        )
        db.add(answer)
        await db.flush()
        runs.append(run)
        answers.append(answer)
    await conversation_repo.link_message_to_run(
        db, message_id=result.message.id, run_id=runs[0].id, conversation_id=room.conversation.id
    )
    history = await conversation_repo.get_room_history_messages(
        db,
        room.conversation.id,
        request_message_id=result.message.id,
        request_id=child.id,
        limit=60,
    )
    assert history is not None
    assert [message.id for message in history] == [answers[0].id]
    assert later.message.id not in {message.id for message in history}
    assert (
        await conversation_repo.question_of_run(
            db, run_id=runs[1].id, organization_id=room.ctx.organization_id
        )
        == "Please compare"
    )
    assert (
        await conversation_repo.question_of_run(db, run_id=runs[1].id, organization_id=uuid4())
        is None
    )
    assert await conversation_repo.prompt_for_answer(db, answers[1]) == "Please compare"
    discard_deferred(db)


@pytest.mark.security
async def test_removed_person_cannot_read_a_previous_private_room_mention(db: AsyncSession):
    from app.db.models.notification import Notification, NotificationEventType
    from app.schemas.room_participant import RoomParticipantRef
    from app.services.notification_center import NotificationCenterService
    from app.services.room_participant import RoomParticipantService

    room, _, person = await seed_multiplayer(db)
    await RoomSubmissionService(db).post(
        room.ctx,
        room.conversation.id,
        RoomMessageCreate(
            client_message_id="person",
            content="Could you review?",
            mentions=[RoomParticipantRef(kind="user", id=person.id)],
        ),
        room.user,
    )
    notice = await db.scalar(
        select(Notification).where(
            Notification.event_type == NotificationEventType.ROOM_MENTION,
            Notification.recipient_user_id == person.id,
        )
    )
    assert notice is not None
    reader = AuthContext(user_id=person.id, organization_id=room.ctx.organization_id, role="viewer")
    center = NotificationCenterService(db)
    assert (await center.gate_for(reader, notice)).visible
    await RoomParticipantService(db).remove(
        room.ctx, room.conversation.id, RoomParticipantRef(kind="user", id=person.id)
    )
    assert not (await center.gate_for(reader, notice)).visible
    inbox, _, _ = await center.list_inbox(reader, after=None, limit=50)
    assert notice.id not in {item.id for item in inbox}
    discard_deferred(db)
