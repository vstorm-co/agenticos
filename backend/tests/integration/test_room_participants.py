"""Real PostgreSQL coverage of room roster and access boundaries."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.conversation import Message
from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.repositories import room_participant as room_participant_repo
from app.schemas.conversation import ConversationRead
from app.schemas.room_participant import RoomCreate, RoomParticipantRef
from app.services.room_participant import RoomParticipantService
from app.services.room_submission import RoomSubmissionService
from tests.integration.test_room_submissions import seed

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def add_member(db: AsyncSession, room, *, role: str = "builder", active: bool = True):
    user = User(
        id=uuid4(),
        email=f"{uuid4()}@example.com",
        hashed_password="x",
        is_active=active,
    )
    db.add(user)
    await db.flush()
    member = OrganizationMember(
        id=uuid4(), organization_id=room.ctx.organization_id, user_id=user.id, role=role
    )
    db.add(member)
    await db.flush()
    return (
        user,
        member,
        AuthContext(user_id=user.id, organization_id=room.ctx.organization_id, role=role),
    )


async def add_agent(db: AsyncSession, room, *, published: bool = True) -> Agent:
    agent = Agent(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        owner_user_id=room.user.id,
        slug=f"agent-{uuid4().hex}",
        name="Another responder",
        status="published" if published else "draft",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid4(),
        organization_id=room.ctx.organization_id,
        agent_id=agent.id,
        version=1,
        spec={"name": agent.name, "model_profile_id": str(uuid4())},
    )
    db.add(version)
    await db.flush()
    if published:
        agent.current_version_id = version.id
        await db.flush()
    return agent


async def personal_room(db: AsyncSession):
    room = await seed(db)
    room.conversation.project_id = None
    await db.flush()
    return room


@pytest.fixture
async def room(db: AsyncSession):
    value = await seed(db)
    yield value
    from app.core.background import discard_deferred

    discard_deferred(db)


async def test_conversion_seeds_historical_agents_once_and_does_not_resurrect_removed_bot(
    db: AsyncSession,
):
    room = await personal_room(db)
    db.add(
        Message(
            id=uuid4(),
            conversation_id=room.conversation.id,
            role="assistant",
            content="Earlier answer",
            agent_id=room.agent.id,
        )
    )
    await db.flush()
    service = RoomParticipantService(db)
    await service.ensure_room(room.ctx, room.conversation.id)
    assert room.conversation.room_visibility == "private"
    assert await room_participant_repo.has_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=room.agent.id,
    )

    await service.remove(
        room.ctx,
        room.conversation.id,
        RoomParticipantRef(kind="agent", id=room.agent.id),
    )
    another = await add_agent(db, room)
    await service.add(
        room.ctx,
        room.conversation.id,
        RoomParticipantRef(kind="agent", id=another.id),
    )
    assert not await room_participant_repo.has_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=room.agent.id,
    )


async def test_conversation_owner_cannot_be_removed_from_the_room(db: AsyncSession):
    room = await personal_room(db)
    service = RoomParticipantService(db)
    await service.ensure_room(room.ctx, room.conversation.id)
    with pytest.raises(BadRequestError, match="owner cannot be removed"):
        await service.remove(
            room.ctx,
            room.conversation.id,
            RoomParticipantRef(kind="user", id=room.user.id),
        )


async def test_room_member_may_add_a_runnable_agent_but_not_a_person_or_draft(
    db: AsyncSession,
):
    room = await personal_room(db)
    service = RoomParticipantService(db)
    await service.ensure_room(room.ctx, room.conversation.id)
    member, _, member_ctx = await add_member(db, room, role="builder")
    await service.add(room.ctx, room.conversation.id, RoomParticipantRef(kind="user", id=member.id))

    candidate = await add_agent(db, room)
    await service.add(
        member_ctx,
        room.conversation.id,
        RoomParticipantRef(kind="agent", id=candidate.id),
    )
    assert await room_participant_repo.has_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=candidate.id,
    )

    stranger, _, _ = await add_member(db, room, role="builder")
    with pytest.raises(AuthorizationError, match="Only a room manager may add people"):
        await service.add(
            member_ctx,
            room.conversation.id,
            RoomParticipantRef(kind="user", id=stranger.id),
        )

    draft = await add_agent(db, room, published=False)
    with pytest.raises((AuthorizationError, BadRequestError, NotFoundError)):
        await service.add(
            member_ctx,
            room.conversation.id,
            RoomParticipantRef(kind="agent", id=draft.id),
        )
    assert not await room_participant_repo.has_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=draft.id,
    )


async def test_a_created_room_serializes_without_further_database_io(db: AsyncSession):
    room = await seed(db)
    created = await RoomParticipantService(db).create_room(
        room.ctx, RoomCreate(title="Launch planning", visibility="private")
    )
    assert ConversationRead.model_validate(created).title == "Launch planning"


async def test_public_room_is_readable_before_join_but_write_requires_join(
    db: AsyncSession,
):
    room = await seed(db)
    service = RoomParticipantService(db)
    public = await service.create_room(
        room.ctx,
        RoomCreate(title="Open room", visibility="public"),
    )
    _, _, reader_ctx = await add_member(db, room, role="viewer")
    participants = await service.participants(reader_ctx, public.id)
    assert participants.visibility == "public"
    assert participants.can_post is False
    with pytest.raises(NotFoundError):
        await RoomSubmissionService(db).room(reader_ctx, public.id, for_write=True)

    await service.join_public_room(reader_ctx, public.id)
    participants = await service.participants(reader_ctx, public.id)
    assert participants.can_post is True
    assert (
        await RoomSubmissionService(db).room(reader_ctx, public.id, for_write=True)
    ).id == public.id


async def test_project_human_audience_tracks_project_view_and_is_not_a_room_grant(
    db: AsyncSession,
):
    room = await seed(db)
    teammate, membership, _ = await add_member(db, room, role="owner")
    service = RoomParticipantService(db)

    listed = await service.participants(room.ctx, room.conversation.id)
    teammate_read = next(item for item in listed.items if item.id == teammate.id)
    assert teammate_read.kind == "user"
    assert teammate_read.is_member and teammate_read.can_mention
    assert not await room_participant_repo.has_member(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        user_id=teammate.id,
    )
    with pytest.raises(BadRequestError, match="managed by project access"):
        await service.add(
            room.ctx,
            room.conversation.id,
            RoomParticipantRef(kind="user", id=teammate.id),
        )

    membership.role = "builder"
    await db.flush()
    listed = await service.participants(room.ctx, room.conversation.id)
    assert all(item.id != teammate.id for item in listed.items)
    with pytest.raises(AuthorizationError, match="no longer has room access"):
        await service.validate_mentions(
            room.ctx,
            room.conversation.id,
            [RoomParticipantRef(kind="user", id=teammate.id)],
        )


async def test_room_mutations_reject_api_key_and_impersonated_contexts(db: AsyncSession):
    room = await personal_room(db)
    service = RoomParticipantService(db)
    await service.ensure_room(room.ctx, room.conversation.id)
    candidate = await add_agent(db, room)
    reference = RoomParticipantRef(kind="agent", id=candidate.id)
    for ctx in (
        replace(room.ctx, api_key_id=uuid4()),
        replace(room.ctx, is_impersonated=True),
    ):
        with pytest.raises(AuthorizationError, match="signed-in organization member"):
            await service.add(ctx, room.conversation.id, reference)


async def test_inactive_organization_member_cannot_read_or_mutate_room(db: AsyncSession):
    room = await seed(db)
    inactive, _, inactive_ctx = await add_member(db, room, role="owner", active=False)
    service = RoomParticipantService(db)
    with pytest.raises(AuthorizationError, match="active organization member"):
        await service.participants(inactive_ctx, room.conversation.id)
    with pytest.raises(AuthorizationError, match="active organization member"):
        await service.add(
            inactive_ctx,
            room.conversation.id,
            RoomParticipantRef(kind="agent", id=room.agent.id),
        )
    assert not await room_participant_repo.has_member(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        user_id=inactive.id,
    )
