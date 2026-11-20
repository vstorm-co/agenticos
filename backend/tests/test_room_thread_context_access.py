"""Cross-room thread context is limited to the current destination audience."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.repositories import room_thread_context_access as room_thread_context_access_repo
from app.repositories.room_thread_context_access import ActiveMemberContext
from app.services import room_thread_context_access as room_thread_context_access_module
from app.services.room_thread_context_access import (
    MAX_CONTEXT_SOURCE_DEPTH,
    MAX_CONTEXT_SOURCE_NODES,
    RoomThreadContextAccessService,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def conversation(
    organization_id,
    *,
    conversation_id=None,
    room_visibility=None,
    project_id=None,
    origin=None,
):
    return SimpleNamespace(
        id=conversation_id or uuid4(),
        organization_id=organization_id,
        room_visibility=room_visibility,
        project_id=project_id,
        origin=origin,
        user_id=None,
    )


@pytest.fixture
def service(monkeypatch):
    db = AsyncMock()
    instance = RoomThreadContextAccessService(db)
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(repo, "active_member_contexts", AsyncMock(return_value=[]))
    monkeypatch.setattr(repo, "has_bearer_share", AsyncMock(return_value=False))
    monkeypatch.setattr(repo, "agent_ids", AsyncMock(return_value=set()))
    instance._may_read = AsyncMock(return_value=True)
    instance._may_read_direct = AsyncMock(return_value=True)
    return instance


async def test_same_conversation_returns_after_tenant_proof(service):
    organization_id = uuid4()
    conversation_id = uuid4()
    same = conversation(organization_id, conversation_id=conversation_id)

    await service.assert_visible(destination=same, source=same)

    service._may_read.assert_not_awaited()
    service._may_read_direct.assert_not_awaited()
    room_thread_context_access_module.room_thread_context_access_repo.has_bearer_share.assert_not_awaited()


async def test_same_conversation_still_requires_matching_tenant(service):
    destination = conversation(uuid4())
    source = conversation(uuid4(), conversation_id=destination.id)

    with pytest.raises(AuthorizationError) as raised:
        await service.assert_visible(destination=destination, source=source)

    assert raised.value.details == {
        "source_conversation_id": str(source.id),
        "destination_conversation_id": str(destination.id),
    }


@pytest.mark.parametrize(
    "source_factory",
    [
        lambda org: conversation(org, origin="workflow", project_id=uuid4()),
        lambda org: conversation(org),
    ],
    ids=["workflow", "personal-chat"],
)
async def test_cross_room_context_rejects_unsupported_source(service, source_factory):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = source_factory(organization_id)

    with pytest.raises(AuthorizationError):
        await service.assert_visible(destination=destination, source=source)

    room_thread_context_access_module.room_thread_context_access_repo.has_bearer_share.assert_not_awaited()


async def test_cross_room_context_rejects_bearer_shared_destination(service, monkeypatch):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, room_visibility="private")
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(repo, "has_bearer_share", AsyncMock(return_value=True))

    with pytest.raises(AuthorizationError):
        await service.assert_visible(destination=destination, source=source)

    repo.active_member_contexts.assert_not_awaited()
    service._may_read.assert_not_awaited()
    service._may_read_direct.assert_not_awaited()


async def test_actor_needs_active_org_membership_and_current_read_access(service, monkeypatch):
    organization_id = uuid4()
    actor_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, project_id=uuid4())
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(repo, "active_member_contexts", AsyncMock(return_value=[]))
    actor = AuthContext(user_id=actor_id, organization_id=organization_id, role="stale")

    with pytest.raises(AuthorizationError):
        await service.assert_visible(destination=destination, source=source, actor=actor)

    service._may_read.assert_not_awaited()
    service._may_read_direct.assert_not_awaited()


async def test_actor_and_current_audience_use_active_role_and_admin_flag(service, monkeypatch):
    organization_id = uuid4()
    actor_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, project_id=uuid4())
    current = ActiveMemberContext(user_id=actor_id, role="owner", is_app_admin=True)
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(repo, "active_member_contexts", AsyncMock(return_value=[current]))
    actor = AuthContext(
        user_id=actor_id,
        organization_id=organization_id,
        role="stale",
        is_app_admin=False,
        api_key_id=uuid4(),
        key_scopes=frozenset({Perm.PROJECTS_VIEW}),
    )

    await service.assert_visible(destination=destination, source=source, actor=actor)

    refreshed = AuthContext(
        user_id=actor_id,
        organization_id=organization_id,
        role="owner",
        is_app_admin=True,
        api_key_id=actor.api_key_id,
        key_scopes=actor.key_scopes,
    )
    service._may_read_direct.assert_any_await(destination, actor_id, ctx=refreshed)
    service._may_read.assert_any_await(source, actor_id, ctx=refreshed)


@pytest.mark.parametrize("blocked_conversation", ["destination", "source"])
async def test_actor_must_currently_read_both_conversations(
    service, monkeypatch, blocked_conversation
):
    organization_id = uuid4()
    actor_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, project_id=uuid4())
    member = ActiveMemberContext(user_id=actor_id, role="member", is_app_admin=False)
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(repo, "active_member_contexts", AsyncMock(return_value=[member]))
    blocked = destination if blocked_conversation == "destination" else source

    async def current_read(conversation_arg, user_id, *, ctx):
        return conversation_arg.id != blocked.id

    service._may_read.side_effect = current_read
    service._may_read_direct.side_effect = current_read
    actor = AuthContext(user_id=actor_id, organization_id=organization_id, role="member")

    with pytest.raises(AuthorizationError):
        await service.assert_visible(destination=destination, source=source, actor=actor)


async def test_every_destination_reader_must_read_source(service, monkeypatch):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, room_visibility="private")
    first_id, second_id = uuid4(), uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(
        repo,
        "active_member_contexts",
        AsyncMock(
            return_value=[
                ActiveMemberContext(user_id=first_id, role="member", is_app_admin=False),
                ActiveMemberContext(user_id=second_id, role="admin", is_app_admin=False),
            ]
        ),
    )

    async def current_read(conversation_arg, user_id, *, ctx):
        return conversation_arg.id != source.id or user_id != second_id

    service._may_read.side_effect = current_read
    service._may_read_direct.side_effect = AsyncMock(return_value=True)

    with pytest.raises(AuthorizationError):
        await service.assert_visible(destination=destination, source=source)

    assert service._may_read.await_count == 2
    assert service._may_read_direct.await_count == 2


async def test_private_source_requires_destination_agents_to_be_source_agents(service, monkeypatch):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, room_visibility="private")
    shared_agent, extra_agent = uuid4(), uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(
        repo,
        "agent_ids",
        AsyncMock(side_effect=[{shared_agent}, {shared_agent, extra_agent}]),
    )

    with pytest.raises(AuthorizationError):
        await service.assert_visible(destination=destination, source=source)

    assert repo.agent_ids.await_count == 2


async def test_project_source_requires_actual_responder_to_be_source_agent(service, monkeypatch):
    organization_id = uuid4()
    destination = conversation(organization_id, project_id=uuid4())
    source = conversation(organization_id, project_id=uuid4())
    responder_agent = uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(
        repo,
        "agent_ids",
        AsyncMock(side_effect=[set(), set()]),
    )

    with pytest.raises(AuthorizationError):
        await service.assert_visible(
            destination=destination,
            source=source,
            responder_agent_id=responder_agent,
        )

    assert repo.agent_ids.await_count == 2


async def test_private_source_allows_actual_responder_and_destination_roster_subset(
    service, monkeypatch
):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, room_visibility="private")
    responder_agent, destination_agent = uuid4(), uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(
        repo,
        "agent_ids",
        AsyncMock(side_effect=[{responder_agent, destination_agent}, {destination_agent}]),
    )

    await service.assert_visible(
        destination=destination,
        source=source,
        responder_agent_id=responder_agent,
    )

    assert repo.agent_ids.await_count == 2


async def test_public_room_source_skips_agent_subset_but_requires_active_actor(
    service, monkeypatch
):
    organization_id = uuid4()
    actor_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, room_visibility="public")
    repo = room_thread_context_access_module.room_thread_context_access_repo
    member = ActiveMemberContext(user_id=actor_id, role="member", is_app_admin=False)
    monkeypatch.setattr(repo, "active_member_contexts", AsyncMock(return_value=[member]))
    actor = AuthContext(user_id=actor_id, organization_id=organization_id, role="member")

    await service.assert_visible(
        destination=destination,
        source=source,
        actor=actor,
        responder_agent_id=uuid4(),
    )

    repo.agent_ids.assert_not_awaited()
    service._may_read.assert_any_await(source, actor_id, ctx=actor)


async def test_actual_responder_must_be_on_every_private_source_in_nested_closure(
    service, monkeypatch
):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    intermediate = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, project_id=uuid4())
    responder_agent = uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(
        repo,
        "external_context_edges",
        AsyncMock(
            side_effect=[
                [(destination.id, intermediate.id)],
                [(intermediate.id, source.id)],
                [],
            ]
        ),
    )
    monkeypatch.setattr(
        repo,
        "conversations_by_ids",
        AsyncMock(
            side_effect=[
                {intermediate.id: intermediate},
                {source.id: source},
            ]
        ),
    )
    monkeypatch.setattr(
        repo,
        "agent_ids",
        AsyncMock(return_value={responder_agent}),
    )

    await service.assert_responder_visible(
        destination=destination,
        responder_agent_id=responder_agent,
    )

    assert repo.agent_ids.await_count == 2
    assert repo.external_context_edges.await_count == 3


async def test_actual_responder_missing_from_nested_private_source_is_refused(service, monkeypatch):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    intermediate = conversation(organization_id, room_visibility="private")
    source = conversation(organization_id, room_visibility="private")
    responder_agent = uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(
        repo,
        "external_context_edges",
        AsyncMock(
            side_effect=[
                [(destination.id, intermediate.id)],
                [(intermediate.id, source.id)],
            ]
        ),
    )
    monkeypatch.setattr(
        repo,
        "conversations_by_ids",
        AsyncMock(
            side_effect=[
                {intermediate.id: intermediate},
                {source.id: source},
            ]
        ),
    )
    monkeypatch.setattr(
        repo,
        "agent_ids",
        AsyncMock(side_effect=[{responder_agent}, {uuid4()}]),
    )

    with pytest.raises(AuthorizationError):
        await service.assert_responder_visible(
            destination=destination,
            responder_agent_id=responder_agent,
        )

    assert repo.agent_ids.await_count == 2


async def test_public_standalone_source_keeps_responder_roster_exception_in_closure(
    service, monkeypatch
):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    public_source = conversation(organization_id, room_visibility="public")
    private_source = conversation(organization_id, room_visibility="private")
    responder_agent = uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    monkeypatch.setattr(
        repo,
        "external_context_edges",
        AsyncMock(
            side_effect=[
                [(destination.id, public_source.id)],
                [(public_source.id, private_source.id)],
                [],
            ]
        ),
    )
    monkeypatch.setattr(
        repo,
        "conversations_by_ids",
        AsyncMock(
            side_effect=[
                {public_source.id: public_source},
                {private_source.id: private_source},
            ]
        ),
    )
    monkeypatch.setattr(repo, "agent_ids", AsyncMock(return_value={responder_agent}))

    await service.assert_responder_visible(
        destination=destination,
        responder_agent_id=responder_agent,
    )

    repo.agent_ids.assert_awaited_once_with(
        service.db,
        organization_id=organization_id,
        conversation_id=private_source.id,
    )


async def test_actual_responder_closure_fails_closed_for_missing_rows_and_node_overflow(
    service, monkeypatch
):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    responder_agent = uuid4()
    repo = room_thread_context_access_module.room_thread_context_access_repo
    missing_source_id = uuid4()
    missing_edges = AsyncMock(return_value=[(destination.id, missing_source_id)])
    missing_rows = AsyncMock(return_value={})
    monkeypatch.setattr(
        repo,
        "external_context_edges",
        missing_edges,
    )
    monkeypatch.setattr(repo, "conversations_by_ids", missing_rows)

    with pytest.raises(AuthorizationError):
        await service.assert_responder_visible(
            destination=destination,
            responder_agent_id=responder_agent,
        )
    missing_rows.assert_awaited_once()
    repo.agent_ids.assert_not_awaited()

    oversized_ids = {uuid4() for _ in range(MAX_CONTEXT_SOURCE_NODES)}
    overflow_edges = AsyncMock(
        return_value=[(destination.id, source_id) for source_id in oversized_ids]
    )
    overflow_rows = AsyncMock(return_value={})
    overflow_rosters = AsyncMock(return_value=set())
    monkeypatch.setattr(repo, "external_context_edges", overflow_edges)
    monkeypatch.setattr(repo, "conversations_by_ids", overflow_rows)
    monkeypatch.setattr(repo, "agent_ids", overflow_rosters)

    with pytest.raises(AuthorizationError):
        await service.assert_responder_visible(
            destination=destination,
            responder_agent_id=responder_agent,
        )

    overflow_rows.assert_not_awaited()
    overflow_rosters.assert_not_awaited()


async def test_actual_responder_closure_fails_closed_when_depth_limit_is_exceeded(
    service, monkeypatch
):
    organization_id = uuid4()
    destination = conversation(organization_id, room_visibility="private")
    responder_agent = uuid4()
    sources = [
        conversation(organization_id, room_visibility="private")
        for _ in range(MAX_CONTEXT_SOURCE_DEPTH + 1)
    ]
    edges = [
        (destination.id, sources[0].id),
        *[(sources[index].id, sources[index + 1].id) for index in range(len(sources) - 1)],
    ]
    rows = {row.id: row for row in sources}
    repo = room_thread_context_access_module.room_thread_context_access_repo

    async def find_edges(_db, *, organization_id, destination_ids):
        return [edge for edge in edges if edge[0] in destination_ids]

    async def find_conversations(_db, *, organization_id, conversation_ids):
        return {conversation_id: rows[conversation_id] for conversation_id in conversation_ids}

    monkeypatch.setattr(repo, "external_context_edges", AsyncMock(side_effect=find_edges))
    monkeypatch.setattr(repo, "conversations_by_ids", AsyncMock(side_effect=find_conversations))
    monkeypatch.setattr(repo, "agent_ids", AsyncMock(return_value={responder_agent}))

    with pytest.raises(AuthorizationError):
        await service.assert_responder_visible(
            destination=destination,
            responder_agent_id=responder_agent,
        )

    assert repo.agent_ids.await_count == MAX_CONTEXT_SOURCE_DEPTH


async def test_active_member_query_excludes_inactive_users_and_returns_current_authority():
    organization_id = uuid4()
    member_id = uuid4()
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [(member_id, "admin", True)])

    members = await room_thread_context_access_repo.active_member_contexts(
        db, organization_id=organization_id
    )

    assert members == [ActiveMemberContext(user_id=member_id, role="admin", is_app_admin=True)]
    statement = db.execute.await_args.args[0]
    sql = str(statement)
    assert "organization_members.organization_id" in sql
    assert "users.is_active IS true" in sql
