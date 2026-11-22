"""Room roster rules that only a real database can prove: who may change it, and how."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.room_participant as room_participant_service
from app.core.background import discard_deferred
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation, Message
from app.db.models.conversation_share import ConversationShare
from app.db.models.conversation_task import ConversationTurnClaim
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.room_participant import RoomParticipant
from app.db.models.user import User
from app.repositories import room_participant as room_participant_repo
from app.schemas.room_participant import RoomCreate, RoomParticipantRead, RoomParticipantRef
from app.services.room_participant import RoomParticipantService, mention_reads
from tests.integration.test_room_participants import add_agent, add_member, personal_room
from tests.integration.test_room_submissions import Room, seed

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def drop_deferred_announcements(db: AsyncSession):
    yield
    discard_deferred(db)


def user_ref(user_id) -> RoomParticipantRef:
    return RoomParticipantRef(kind="user", id=user_id)


def agent_ref(agent_id) -> RoomParticipantRef:
    return RoomParticipantRef(kind="agent", id=agent_id)


async def roster(db: AsyncSession, room: Room, conversation_id=None) -> list[RoomParticipant]:
    return await room_participant_repo.list_for_conversation(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=conversation_id or room.conversation.id,
    )


async def stored_auto_replies(db: AsyncSession, room: Room) -> list[tuple[object, bool]]:
    rows = await db.execute(
        select(RoomParticipant.agent_id, RoomParticipant.auto_reply).where(
            RoomParticipant.conversation_id == room.conversation.id
        )
    )
    return [(agent_id, auto_reply) for agent_id, auto_reply in rows.all()]


async def share(db: AsyncSession, room: Room, user: User, permission: str) -> None:
    db.add(
        ConversationShare(
            id=uuid4(),
            conversation_id=room.conversation.id,
            shared_by=room.user.id,
            shared_with=user.id,
            permission=permission,
        )
    )
    await db.flush()


async def converted_room(db: AsyncSession) -> tuple[Room, RoomParticipantService]:
    room = await personal_room(db)
    service = RoomParticipantService(db)
    await service.ensure_room(room.ctx, room.conversation.id)
    return room, service


async def test_a_legacy_chat_previews_its_seed_roster_without_storing_it(db: AsyncSession):
    room = await personal_room(db)
    other_org = Organization(
        id=uuid4(), name="Elsewhere", slug=f"else-{uuid4().hex}", created_by_user_id=room.user.id
    )
    db.add(other_org)
    await db.flush()
    foreign = Agent(
        id=uuid4(),
        organization_id=other_org.id,
        owner_user_id=room.user.id,
        slug=f"agent-{uuid4().hex}",
        name="Foreign",
        status="published",
        draft_spec={},
    )
    db.add(foreign)
    await db.flush()
    db.add_all(
        [
            Message(
                id=uuid4(),
                conversation_id=room.conversation.id,
                role="assistant",
                content="Earlier answer",
                agent_id=room.agent.id,
            ),
            Message(
                id=uuid4(),
                conversation_id=room.conversation.id,
                role="assistant",
                content="From another tenant",
                agent_id=foreign.id,
            ),
        ]
    )
    await db.flush()

    listed = await RoomParticipantService(db).participants(room.ctx, room.conversation.id)

    assert listed.visibility is None
    by_kind = {item.kind: item for item in listed.items}
    assert len(listed.items) == 2
    assert by_kind["user"].id == room.user.id and not by_kind["user"].is_member
    assert by_kind["agent"].id == room.agent.id
    assert by_kind["agent"].can_add and not by_kind["agent"].can_mention
    assert await roster(db, room) == []


async def test_mentionables_offer_members_first_then_only_runnable_agents_and_active_people(
    db: AsyncSession,
):
    room, service = await converted_room(db)
    candidate = await add_agent(db, room)
    await add_agent(db, room, published=False)
    teammate, _, _ = await add_member(db, room, role="builder")
    await add_member(db, room, role="builder", active=False)

    offered = (await service.mentionables(room.ctx, room.conversation.id)).items
    keys = {(item.kind, item.id): item for item in offered}

    owner = keys[("user", room.user.id)]
    assert owner.is_member and owner.can_mention
    assert offered[0].is_member
    assert keys[("user", teammate.id)].can_add and not keys[("user", teammate.id)].is_member
    assert not keys[("user", teammate.id)].can_mention
    assert keys[("agent", candidate.id)].can_add and not keys[("agent", candidate.id)].is_member
    assert keys[("agent", room.agent.id)].can_add
    assert len(offered) == 4
    assert len({(item.kind, item.id) for item in offered}) == len(offered)


async def test_a_member_who_cannot_manage_is_offered_no_one_to_add_but_agents(db: AsyncSession):
    room, service = await converted_room(db)
    member, _, member_ctx = await add_member(db, room, role="viewer")
    await service.add(room.ctx, room.conversation.id, user_ref(member.id))
    await add_member(db, room, role="builder")

    offered = (await service.mentionables(member_ctx, room.conversation.id)).items

    assert all(item.is_member for item in offered if item.kind == "user")
    assert all(not item.can_add for item in offered if item.kind == "user")


async def test_a_project_chat_lists_teammates_as_members_and_offers_no_one_to_add(
    db: AsyncSession,
):
    room = await seed(db)
    service = RoomParticipantService(db)
    teammate, _, _ = await add_member(db, room, role="owner")
    await add_member(db, room, role="viewer")
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    offered = (await service.mentionables(room.ctx, room.conversation.id)).items

    people = [item for item in offered if item.kind == "user"]
    assert {item.id for item in people} == {room.user.id, teammate.id}
    assert all(item.is_member and item.can_mention and not item.can_add for item in people)
    assert [item.id for item in offered if item.kind == "agent"] == [room.agent.id]
    assert next(item for item in offered if item.kind == "agent").can_mention


async def test_a_viewer_with_only_a_view_share_cannot_convert_a_chat(db: AsyncSession):
    room = await personal_room(db)
    viewer, _, viewer_ctx = await add_member(db, room, role="viewer")
    await share(db, room, viewer, "view")

    with pytest.raises(AuthorizationError, match="Only a room manager may convert"):
        await RoomParticipantService(db).ensure_room(viewer_ctx, room.conversation.id)

    assert room.conversation.room_visibility is None
    assert await roster(db, room) == []


async def test_converting_twice_leaves_the_roster_unchanged(db: AsyncSession):
    room, service = await converted_room(db)
    before = [row.id for row in await roster(db, room)]

    again = await service.ensure_room(room.ctx, room.conversation.id)

    assert again.room_visibility == "private"
    assert [row.id for row in await roster(db, room)] == before


async def test_a_chat_with_work_in_flight_cannot_be_converted(db: AsyncSession):
    room = await personal_room(db)
    db.add(
        ConversationTurnClaim(
            id=uuid4(),
            conversation_id=room.conversation.id,
            background=False,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    await db.flush()

    with pytest.raises(ConflictError, match="current work to finish"):
        await RoomParticipantService(db).ensure_room(room.ctx, room.conversation.id)

    assert room.conversation.room_visibility is None
    assert await roster(db, room) == []


async def test_an_ownerless_chat_cannot_become_a_room(db: AsyncSession):
    room = await personal_room(db)
    editor, _, editor_ctx = await add_member(db, room, role="builder")
    ownerless = Conversation(
        id=uuid4(), organization_id=room.ctx.organization_id, user_id=None, project_id=None
    )
    db.add(ownerless)
    await db.flush()
    db.add(
        ConversationShare(
            id=uuid4(),
            conversation_id=ownerless.id,
            shared_by=room.user.id,
            shared_with=editor.id,
            permission="edit",
        )
    )
    await db.flush()

    with pytest.raises(BadRequestError, match="Only a personal conversation"):
        await RoomParticipantService(db).ensure_room(editor_ctx, ownerless.id)

    assert ownerless.room_visibility is None


async def test_conversion_by_an_editor_skips_an_owner_who_left_the_organization(
    db: AsyncSession,
):
    room = await personal_room(db)
    editor, _, editor_ctx = await add_member(db, room, role="builder")
    await share(db, room, editor, "edit")
    db.add(
        Message(
            id=uuid4(),
            conversation_id=room.conversation.id,
            role="assistant",
            content="Earlier answer",
            agent_id=room.agent.id,
        )
    )
    await db.execute(delete(OrganizationMember).where(OrganizationMember.id == room.member.id))
    await db.flush()

    await RoomParticipantService(db).ensure_room(editor_ctx, room.conversation.id)

    rows = await roster(db, room)
    assert [(row.user_id, row.agent_id) for row in rows] == [(None, room.agent.id)]


async def test_an_edit_share_holder_may_add_themselves_without_notifying_themselves(
    db: AsyncSession,
):
    room, service = await converted_room(db)
    editor, _, editor_ctx = await add_member(db, room, role="builder")
    await share(db, room, editor, "edit")

    added = await service.add(editor_ctx, room.conversation.id, user_ref(editor.id))

    assert added.id == editor.id and added.is_member
    assert await room_participant_repo.has_member(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        user_id=editor.id,
    )


async def test_adding_someone_outside_the_organization_is_refused(db: AsyncSession):
    room, service = await converted_room(db)
    outsider = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(outsider)
    await db.flush()

    for missing in (uuid4(), outsider.id):
        with pytest.raises(NotFoundError, match="User not found"):
            await service.add(room.ctx, room.conversation.id, user_ref(missing))

    assert len(await roster(db, room)) == 1


async def test_adding_a_present_participant_again_changes_nothing(db: AsyncSession):
    room, service = await converted_room(db)
    member, _, _ = await add_member(db, room, role="builder")
    first = await service.add(room.ctx, room.conversation.id, user_ref(member.id))
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))
    before = len(await roster(db, room))

    again = await service.add(room.ctx, room.conversation.id, user_ref(member.id))
    again_agent = await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    assert again.id == first.id and again_agent.id == room.agent.id
    assert len(await roster(db, room)) == before


async def test_a_reader_who_has_not_joined_cannot_add_an_agent_to_a_public_room(
    db: AsyncSession,
):
    room = await seed(db)
    service = RoomParticipantService(db)
    public = await service.create_room(room.ctx, RoomCreate(title="Open", visibility="public"))
    _, _, reader_ctx = await add_member(db, room, role="viewer")

    with pytest.raises(AuthorizationError, match="Join the room before adding an agent"):
        await service.add(reader_ctx, public.id, agent_ref(room.agent.id))

    assert not await room_participant_repo.has_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=public.id,
        agent_id=room.agent.id,
    )


async def test_a_person_without_an_organization_membership_cannot_create_a_room(
    db: AsyncSession,
):
    room = await seed(db)
    stranger = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(stranger)
    await db.flush()
    ctx = AuthContext(user_id=stranger.id, organization_id=room.ctx.organization_id, role="owner")

    with pytest.raises(AuthorizationError, match="active organization member"):
        await RoomParticipantService(db).create_room(ctx, RoomCreate(title="Sneaky"))

    assert (
        await db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_id == stranger.id)
        )
        == 0
    )


async def test_a_room_created_with_repeated_participants_lists_each_once(db: AsyncSession):
    room = await seed(db)
    teammate, _, _ = await add_member(db, room, role="builder")

    created = await RoomParticipantService(db).create_room(
        room.ctx,
        RoomCreate(
            title="Planning",
            participants=[
                user_ref(room.user.id),
                user_ref(teammate.id),
                user_ref(teammate.id),
                agent_ref(room.agent.id),
                agent_ref(room.agent.id),
            ],
        ),
    )

    rows = await roster(db, room, created.id)
    assert sorted(((row.user_id is None), row.user_id or row.agent_id) for row in rows) == sorted(
        [(False, room.user.id), (False, teammate.id), (True, room.agent.id)]
    )


async def test_removal_needs_a_manager_and_an_existing_participant(db: AsyncSession):
    room, service = await converted_room(db)
    member, _, member_ctx = await add_member(db, room, role="viewer")
    await service.add(room.ctx, room.conversation.id, user_ref(member.id))
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    with pytest.raises(AuthorizationError, match="Only a room manager may remove"):
        await service.remove(member_ctx, room.conversation.id, agent_ref(room.agent.id))
    assert await room_participant_repo.has_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=room.agent.id,
    )

    stranger, _, _ = await add_member(db, room, role="builder")
    with pytest.raises(NotFoundError, match="Room participant not found"):
        await service.remove(room.ctx, room.conversation.id, user_ref(stranger.id))
    with pytest.raises(NotFoundError, match="Room participant not found"):
        await service.remove(room.ctx, room.conversation.id, agent_ref(uuid4()))


async def test_a_manager_turns_an_agents_automatic_reply_on_and_off(db: AsyncSession):
    room, service = await converted_room(db)
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    on = await service.set_auto_reply(
        room.ctx, room.conversation.id, room.agent.id, auto_reply=True
    )
    assert on.auto_reply is True
    assert [item.id for item in await service.automatic_agents(room.ctx, room.conversation.id)] == [
        room.agent.id
    ]
    stored = await room_participant_repo.get_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=room.agent.id,
    )
    assert stored is not None and stored.auto_reply is True

    same = await service.set_auto_reply(
        room.ctx, room.conversation.id, room.agent.id, auto_reply=True
    )
    assert same.auto_reply is True

    off = await service.set_auto_reply(
        room.ctx, room.conversation.id, room.agent.id, auto_reply=False
    )
    assert off.auto_reply is False
    assert await service.automatic_agents(room.ctx, room.conversation.id) == []


async def test_automatic_reply_settings_are_refused_to_non_managers_and_for_absent_agents(
    db: AsyncSession,
):
    room, service = await converted_room(db)
    member, _, member_ctx = await add_member(db, room, role="viewer")
    await service.add(room.ctx, room.conversation.id, user_ref(member.id))
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    with pytest.raises(AuthorizationError, match="Only a room manager may change agent"):
        await service.set_auto_reply(
            member_ctx, room.conversation.id, room.agent.id, auto_reply=True
        )
    with pytest.raises(NotFoundError, match="Room agent not found"):
        await service.set_auto_reply(room.ctx, room.conversation.id, uuid4(), auto_reply=True)

    stored = await room_participant_repo.get_agent(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=room.agent.id,
    )
    assert stored is not None and stored.auto_reply is False


async def test_automatic_agents_skip_unrunnable_agents_and_stop_at_the_cap(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    room, service = await converted_room(db)
    second = await add_agent(db, room)
    third = await add_agent(db, room)
    for agent in (room.agent, second, third):
        await service.add(room.ctx, room.conversation.id, agent_ref(agent.id))
        await service.set_auto_reply(room.ctx, room.conversation.id, agent.id, auto_reply=True)
    third.current_version_id = None
    third.status = "draft"
    await db.flush()

    runnable = await service.automatic_agents(room.ctx, room.conversation.id)
    assert {item.id for item in runnable} == {room.agent.id, second.id}

    monkeypatch.setattr(room_participant_service, "MAX_AUTOMATIC_AGENTS", 1)
    capped = await service.automatic_agents(room.ctx, room.conversation.id)
    assert len(capped) == 1


async def test_an_agent_that_stopped_being_runnable_stays_listed_but_cannot_be_mentioned(
    db: AsyncSession,
):
    room, service = await converted_room(db)
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))
    room.agent.current_version_id = None
    room.agent.status = "draft"
    await db.flush()

    listed = await service.participants(room.ctx, room.conversation.id)

    agent = next(item for item in listed.items if item.kind == "agent")
    assert agent.is_member and not agent.can_mention
    with pytest.raises((AuthorizationError, BadRequestError, NotFoundError)):
        await service.validate_mentions(room.ctx, room.conversation.id, [agent_ref(room.agent.id)])


async def test_mentions_resolve_roster_members_once_and_expose_only_mentionable_ones(
    db: AsyncSession,
):
    room, service = await converted_room(db)
    member, _, _ = await add_member(db, room, role="builder")
    await service.add(room.ctx, room.conversation.id, user_ref(member.id))
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))
    await service.set_auto_reply(room.ctx, room.conversation.id, room.agent.id, auto_reply=True)

    resolved = await service.validate_mentions(
        room.ctx,
        room.conversation.id,
        [
            user_ref(member.id),
            user_ref(member.id),
            agent_ref(room.agent.id),
            agent_ref(room.agent.id),
        ],
    )

    assert [(item.kind, item.id) for item in resolved] == [
        ("user", member.id),
        ("agent", room.agent.id),
    ]
    assert resolved[1].auto_reply is True
    assert [item.id for item in mention_reads(resolved)] == [member.id, room.agent.id]


async def test_mention_reads_drop_entries_that_cannot_be_mentioned():
    mentionable = RoomParticipantRead(kind="user", id=uuid4(), name="Ada", can_mention=True)
    silent = RoomParticipantRead(kind="agent", id=uuid4(), name="Bot", can_mention=False)

    reads = mention_reads([silent, mentionable])

    assert [(item.kind, item.id, item.name) for item in reads] == [("user", mentionable.id, "Ada")]


async def test_mentions_refuse_non_members_non_roster_agents_and_unconverted_chats(
    db: AsyncSession,
):
    room, service = await converted_room(db)
    outsider, _, _ = await add_member(db, room, role="builder")
    spare = await add_agent(db, room)

    with pytest.raises(AuthorizationError, match="Mentioned person is not a room member"):
        await service.validate_mentions(room.ctx, room.conversation.id, [user_ref(outsider.id)])
    with pytest.raises(AuthorizationError, match="Mentioned agent is not a room member"):
        await service.validate_mentions(room.ctx, room.conversation.id, [agent_ref(spare.id)])

    legacy = await personal_room(db)
    with pytest.raises(BadRequestError, match="Convert this conversation to a room"):
        await service.validate_mentions(legacy.ctx, legacy.conversation.id, [])


async def test_a_reader_who_has_not_joined_a_public_room_cannot_mention_anyone(
    db: AsyncSession,
):
    room = await seed(db)
    service = RoomParticipantService(db)
    public = await service.create_room(room.ctx, RoomCreate(title="Open", visibility="public"))
    _, _, reader_ctx = await add_member(db, room, role="viewer")

    with pytest.raises(AuthorizationError, match="Join the room before mentioning"):
        await service.validate_mentions(reader_ctx, public.id, [user_ref(room.user.id)])


async def test_a_project_chat_cannot_mention_someone_outside_the_organization(db: AsyncSession):
    room = await seed(db)
    outsider = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(outsider)
    await db.flush()

    with pytest.raises(AuthorizationError, match="no longer has room access"):
        await RoomParticipantService(db).validate_mentions(
            room.ctx, room.conversation.id, [user_ref(outsider.id)]
        )


async def test_the_public_directory_pages_rooms_the_reader_has_not_joined(db: AsyncSession):
    room = await seed(db)
    service = RoomParticipantService(db)
    rooms = [
        await service.create_room(room.ctx, RoomCreate(title=f"Open {n}", visibility="public"))
        for n in range(3)
    ]
    await service.create_room(room.ctx, RoomCreate(title="Closed", visibility="private"))
    _, _, reader_ctx = await add_member(db, room, role="viewer")

    first, total = await service.list_public_rooms(reader_ctx, skip=0, limit=2)
    second, second_total = await service.list_public_rooms(reader_ctx, skip=2, limit=2)
    own, own_total = await service.list_public_rooms(room.ctx, skip=0, limit=10)

    assert total == second_total == 3
    assert len(first) == 2 and len(second) == 1
    assert {item.id for item in [*first, *second]} == {item.id for item in rooms}
    assert (own, own_total) == ([], 0)

    await service.join_public_room(reader_ctx, rooms[0].id)
    remaining, remaining_total = await service.list_public_rooms(reader_ctx, skip=0, limit=10)
    assert remaining_total == 2 and rooms[0].id not in {item.id for item in remaining}


async def test_the_public_directory_leaves_out_archived_other_tenant_and_workflow_rooms(
    db: AsyncSession,
):
    room = await seed(db)
    service = RoomParticipantService(db)
    visible = await service.create_room(room.ctx, RoomCreate(title="Visible", visibility="public"))
    archived = await service.create_room(room.ctx, RoomCreate(title="Old", visibility="public"))
    workflow = await service.create_room(room.ctx, RoomCreate(title="Flow", visibility="public"))
    await db.execute(
        update(Conversation).where(Conversation.id == archived.id).values(is_archived=True)
    )
    await db.execute(
        update(Conversation).where(Conversation.id == workflow.id).values(origin="workflow")
    )
    other = Organization(
        id=uuid4(), name="Elsewhere", slug=f"else-{uuid4().hex}", created_by_user_id=room.user.id
    )
    db.add(other)
    await db.flush()
    db.add(
        Conversation(
            id=uuid4(),
            organization_id=other.id,
            user_id=room.user.id,
            room_visibility="public",
            title="Foreign",
        )
    )
    await db.flush()
    _, _, reader_ctx = await add_member(db, room, role="viewer")

    listed, total = await service.list_public_rooms(reader_ctx, skip=0, limit=10)

    assert [item.id for item in listed] == [visible.id] and total == 1
    foreign, foreign_total = await room_participant_repo.public_directory(
        db, organization_id=other.id, user_id=reader_ctx.user_id, skip=0, limit=10
    )
    assert foreign_total == 1 and [item.title for item in foreign] == ["Foreign"]


async def test_an_inactive_member_cannot_browse_public_rooms(db: AsyncSession):
    room = await seed(db)
    _, _, inactive_ctx = await add_member(db, room, role="viewer", active=False)

    with pytest.raises(AuthorizationError, match="active organization member"):
        await RoomParticipantService(db).list_public_rooms(inactive_ctx, skip=0, limit=10)


async def test_only_a_public_room_can_be_joined_and_joining_twice_adds_one_row(db: AsyncSession):
    room, service = await converted_room(db)
    public = await service.create_room(room.ctx, RoomCreate(title="Open", visibility="public"))
    _, _, reader_ctx = await add_member(db, room, role="viewer")

    with pytest.raises(NotFoundError, match="Public room not found"):
        await service.join_public_room(room.ctx, room.conversation.id)

    await service.join_public_room(reader_ctx, public.id)
    await service.join_public_room(reader_ctx, public.id)

    reader_rows = [
        row for row in await roster(db, room, public.id) if row.user_id == reader_ctx.user_id
    ]
    assert len(reader_rows) == 1


async def test_a_join_loses_to_a_member_removed_after_the_check(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Membership is checked again after the lock; a concurrent removal refuses the join."""
    room = await seed(db)
    service = RoomParticipantService(db)
    public = await service.create_room(room.ctx, RoomCreate(title="Open", visibility="public"))
    reader, reader_member, reader_ctx = await add_member(db, room, role="viewer")
    real = service._conversation
    calls = 0

    async def conversation_then_removed(ctx: AuthContext, conversation_id):
        nonlocal calls
        result = await real(ctx, conversation_id)
        calls += 1
        if calls == 1:
            await db.execute(
                delete(OrganizationMember).where(OrganizationMember.id == reader_member.id)
            )
        return result

    monkeypatch.setattr(service, "_conversation", conversation_then_removed)

    with pytest.raises(AuthorizationError, match="active organization member"):
        await service.join_public_room(reader_ctx, public.id)

    assert not await room_participant_repo.has_member(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=public.id,
        user_id=reader.id,
    )


async def test_a_join_loses_to_a_room_made_private_after_the_lock(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Visibility is read again under the lock; a room closed meanwhile cannot be joined."""
    room = await seed(db)
    service = RoomParticipantService(db)
    public = await service.create_room(room.ctx, RoomCreate(title="Open", visibility="public"))
    reader, _, reader_ctx = await add_member(db, room, role="viewer")
    db.add(
        ConversationShare(
            id=uuid4(),
            conversation_id=public.id,
            shared_by=room.user.id,
            shared_with=reader.id,
            permission="view",
        )
    )
    await db.flush()
    real_hold = room_participant_service.hold_subject

    async def hold_then_close(session: AsyncSession, scope, subject) -> None:
        await real_hold(session, scope, subject)
        await session.execute(
            update(Conversation)
            .where(Conversation.id == public.id)
            .values(room_visibility="private")
            .execution_options(synchronize_session="fetch")
        )

    monkeypatch.setattr(room_participant_service, "hold_subject", hold_then_close)

    with pytest.raises(NotFoundError, match="Public room not found"):
        await service.join_public_room(reader_ctx, public.id)

    assert not await room_participant_repo.has_member(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=public.id,
        user_id=reader.id,
    )


async def test_a_participant_is_described_by_its_conversation_and_principal(db: AsyncSession):
    room, service = await converted_room(db)
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    rows = await roster(db, room)

    texts = {repr(row) for row in rows}
    assert (
        f"<RoomParticipant(conversation={room.conversation.id}, principal={room.user.id})>" in texts
    )
    assert (
        f"<RoomParticipant(conversation={room.conversation.id}, principal={room.agent.id})>"
        in texts
    )


async def test_removing_a_principal_needs_an_id_and_removes_only_that_one(db: AsyncSession):
    room, service = await converted_room(db)
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    with pytest.raises(ValueError, match="user_id or agent_id is required"):
        await room_participant_repo.remove(
            db, organization_id=room.ctx.organization_id, conversation_id=room.conversation.id
        )

    assert len(await roster(db, room)) == 2


async def test_auto_reply_is_set_only_for_an_agent_in_that_room_and_tenant(db: AsyncSession):
    room, service = await converted_room(db)
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))
    kwargs = {
        "conversation_id": room.conversation.id,
        "agent_id": room.agent.id,
        "auto_reply": True,
    }

    assert not await room_participant_repo.set_auto_reply(db, organization_id=uuid4(), **kwargs)
    assert not await room_participant_repo.set_auto_reply(
        db,
        organization_id=room.ctx.organization_id,
        conversation_id=room.conversation.id,
        agent_id=uuid4(),
        auto_reply=True,
    )
    assert set(await stored_auto_replies(db, room)) == {(None, False), (room.agent.id, False)}

    assert await room_participant_repo.set_auto_reply(
        db, organization_id=room.ctx.organization_id, **kwargs
    )
    assert set(await stored_auto_replies(db, room)) == {(None, False), (room.agent.id, True)}


async def test_public_ids_keep_only_current_public_rooms(db: AsyncSession):
    room = await seed(db)
    service = RoomParticipantService(db)
    public = await service.create_room(room.ctx, RoomCreate(title="Open", visibility="public"))
    private = await service.create_room(room.ctx, RoomCreate(title="Closed", visibility="private"))
    workflow = await service.create_room(room.ctx, RoomCreate(title="Flow", visibility="public"))
    await db.execute(
        update(Conversation).where(Conversation.id == workflow.id).values(origin="workflow")
    )
    candidates = {public.id, private.id, workflow.id, room.conversation.id, uuid4()}

    found = await room_participant_repo.public_ids_in_conversations(
        db, organization_id=room.ctx.organization_id, conversation_ids=candidates
    )
    elsewhere = await room_participant_repo.public_ids_in_conversations(
        db, organization_id=uuid4(), conversation_ids=candidates
    )

    assert found == {public.id}
    assert elsewhere == set()
    assert (
        await room_participant_repo.public_ids_in_conversations(
            db, organization_id=room.ctx.organization_id, conversation_ids=[]
        )
        == set()
    )


async def history_message(db: AsyncSession, room: Room) -> None:
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


async def test_mentionables_of_a_legacy_chat_preview_its_owner_and_past_agents_once(
    db: AsyncSession,
):
    room = await personal_room(db)
    await history_message(db, room)

    offered = (await RoomParticipantService(db).mentionables(room.ctx, room.conversation.id)).items

    by_key = {(item.kind, item.id): item for item in offered}
    assert len(offered) == len(by_key) == 2
    assert not by_key[("user", room.user.id)].is_member
    assert not by_key[("agent", room.agent.id)].is_member
    assert await roster(db, room) == []


async def test_a_legacy_chat_preview_leaves_out_an_owner_who_left_the_organization(
    db: AsyncSession,
):
    room = await personal_room(db)
    editor, _, editor_ctx = await add_member(db, room, role="builder")
    await share(db, room, editor, "edit")
    await history_message(db, room)
    await db.execute(delete(OrganizationMember).where(OrganizationMember.id == room.member.id))
    await db.flush()

    listed = await RoomParticipantService(db).participants(editor_ctx, room.conversation.id)

    assert [(item.kind, item.id) for item in listed.items] == [("agent", room.agent.id)]


async def test_a_user_finds_the_rooms_they_joined_outside_projects(db: AsyncSession):
    room = await seed(db)
    service = RoomParticipantService(db)
    joined = await service.create_room(room.ctx, RoomCreate(title="Mine"))
    other = await service.create_room(room.ctx, RoomCreate(title="Not mine"))
    teammate, _, _ = await add_member(db, room, role="builder")
    await service.add(room.ctx, other.id, user_ref(teammate.id))
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))
    organization_id = room.ctx.organization_id

    found = await room_participant_repo.user_conversation_ids(
        db, organization_id=organization_id, user_id=room.user.id
    )
    narrowed = await room_participant_repo.user_ids_in_conversations(
        db,
        organization_id=organization_id,
        user_id=teammate.id,
        conversation_ids=[joined.id, other.id],
    )
    nothing = await room_participant_repo.user_ids_in_conversations(
        db, organization_id=organization_id, user_id=teammate.id, conversation_ids=[]
    )
    elsewhere = await room_participant_repo.user_ids_in_conversations(
        db, organization_id=uuid4(), user_id=teammate.id, conversation_ids=[other.id]
    )

    assert found == {joined.id, other.id}
    assert narrowed == {other.id}
    assert nothing == set() and elsewhere == set()


async def test_the_roster_leaves_out_a_user_deleted_after_the_rows_were_read(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    room, service = await converted_room(db)
    await service.add(room.ctx, room.conversation.id, agent_ref(room.agent.id))

    async def nobody(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(room_participant_service.conversation_repo, "users_by_id", nobody)

    listed = await service.participants(room.ctx, room.conversation.id)

    assert [(item.kind, item.id) for item in listed.items] == [("agent", room.agent.id)]


async def test_a_candidate_agent_deleted_after_the_directory_was_read_is_not_offered(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    room, service = await converted_room(db)
    vanishing = await add_agent(db, room)
    real_get_many = room_participant_service.agent_repo.get_many

    async def without_vanishing(*args, **kwargs):
        found = await real_get_many(*args, **kwargs)
        return {key: value for key, value in found.items() if key != vanishing.id}

    monkeypatch.setattr(room_participant_service.agent_repo, "get_many", without_vanishing)

    offered = (await service.mentionables(room.ctx, room.conversation.id)).items

    assert ("agent", vanishing.id) not in {(item.kind, item.id) for item in offered}
    assert ("agent", room.agent.id) in {(item.kind, item.id) for item in offered}


async def test_an_insert_whose_row_cannot_be_read_back_fails_loudly(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    room, _ = await converted_room(db)
    teammate, _, _ = await add_member(db, room, role="builder")

    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(db, "scalar", nothing)

    with pytest.raises(RuntimeError, match="could not be read back"):
        await room_participant_repo.add(
            db,
            organization_id=room.ctx.organization_id,
            conversation_id=room.conversation.id,
            user_id=teammate.id,
        )
