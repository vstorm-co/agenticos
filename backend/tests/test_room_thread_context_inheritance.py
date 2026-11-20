"""Inherited room reads follow every external thread-context source edge."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.permissions import AuthContext
from app.repositories import room_thread_context_access as context_repo
from app.services.room_thread_context_access import (
    MAX_CONTEXT_SOURCE_DEPTH,
    MAX_CONTEXT_SOURCE_NODES,
    RoomThreadContextAccessService,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def conversation(organization_id, conversation_id=None):
    return SimpleNamespace(
        id=conversation_id or uuid4(),
        organization_id=organization_id,
        room_visibility="private",
        project_id=None,
        origin=None,
    )


def install_graph(monkeypatch, edges, conversations):
    repo = context_repo

    async def find_edges(_db, *, organization_id, destination_ids=None):
        assert all(
            conversations[destination].organization_id == organization_id
            for destination, _ in edges
            if destination in conversations
        )
        return [edge for edge in edges if destination_ids is None or edge[0] in destination_ids]

    async def find_conversations(_db, *, organization_id, conversation_ids):
        return {
            conversation_id: conversations[conversation_id]
            for conversation_id in conversation_ids
            if conversation_id in conversations
            and conversations[conversation_id].organization_id == organization_id
        }

    monkeypatch.setattr(repo, "external_context_edges", AsyncMock(side_effect=find_edges))
    monkeypatch.setattr(repo, "conversations_by_ids", AsyncMock(side_effect=find_conversations))


def setup_service(monkeypatch, edges, conversations):
    service = RoomThreadContextAccessService(AsyncMock())
    install_graph(monkeypatch, edges, conversations)
    service._may_read_direct = AsyncMock(return_value=True)
    return service


async def test_can_read_sources_checks_transitive_sources_and_caches_direct_acl(
    monkeypatch,
):
    organization_id = uuid4()
    destination, first, second = [conversation(organization_id) for _ in range(3)]
    service = setup_service(
        monkeypatch,
        [(destination.id, first.id), (first.id, second.id)],
        {item.id: item for item in (destination, first, second)},
    )

    assert await service.can_read_sources(destination, uuid4())

    checked = [call.args[0].id for call in service._may_read_direct.await_args_list]
    assert set(checked) == {first.id, second.id}
    assert len(checked) == 2


async def test_can_read_sources_checks_cycle_back_to_destination_once(monkeypatch):
    organization_id = uuid4()
    destination, source = [conversation(organization_id) for _ in range(2)]
    service = setup_service(
        monkeypatch,
        [(destination.id, source.id), (source.id, destination.id)],
        {destination.id: destination, source.id: source},
    )

    assert await service.can_read_sources(destination, uuid4())

    checked = [call.args[0].id for call in service._may_read_direct.await_args_list]
    assert set(checked) == {destination.id, source.id}
    assert len(checked) == 2


async def test_can_read_sources_fails_closed_for_missing_or_denied_sources(monkeypatch):
    organization_id = uuid4()
    destination, source, missing_id = [uuid4() for _ in range(3)]
    destination_row = conversation(organization_id, destination)
    source_row = conversation(organization_id, source)
    service = setup_service(
        monkeypatch,
        [(destination, source), (source, missing_id)],
        {destination: destination_row, source: source_row},
    )

    assert not await service.can_read_sources(destination_row, uuid4())

    service = setup_service(
        monkeypatch,
        [(destination, source)],
        {destination: destination_row, source: source_row},
    )
    service._may_read_direct.return_value = False
    assert not await service.can_read_sources(destination_row, uuid4())


async def test_can_read_sources_fails_closed_when_graph_exceeds_bounds(monkeypatch):
    organization_id = uuid4()
    rows = [conversation(organization_id) for _ in range(MAX_CONTEXT_SOURCE_DEPTH + 2)]
    depth_edges = [(rows[index].id, rows[index + 1].id) for index in range(len(rows) - 1)]
    service = setup_service(
        monkeypatch,
        depth_edges,
        {row.id: row for row in rows},
    )

    assert not await service.can_read_sources(rows[0], uuid4())

    root = conversation(organization_id)
    leaves = [conversation(organization_id) for _ in range(MAX_CONTEXT_SOURCE_NODES)]
    node_edges = [(root.id, row.id) for row in leaves]
    service = setup_service(
        monkeypatch,
        node_edges,
        {row.id: row for row in [root, *leaves]},
    )

    assert not await service.can_read_sources(root, uuid4())


async def test_unreadable_destinations_checks_transitive_closure_and_reuses_acl_results(
    monkeypatch,
):
    organization_id = uuid4()
    first, second, private_source, other = [conversation(organization_id) for _ in range(4)]
    service = setup_service(
        monkeypatch,
        [(first.id, second.id), (second.id, private_source.id), (other.id, second.id)],
        {item.id: item for item in (first, second, private_source, other)},
    )
    service._may_read_direct.side_effect = lambda row, _user_id, *, ctx: row.id != private_source.id
    user_id = uuid4()
    actor = AuthContext(user_id=user_id, organization_id=organization_id, role="member")

    unreadable = await service.unreadable_destinations(organization_id, user_id, actor)

    assert unreadable == {first.id, second.id, other.id}
    checked = [call.args[0].id for call in service._may_read_direct.await_args_list]
    assert checked.count(private_source.id) == 1
    assert checked.count(second.id) <= 1
    assert len(checked) == len(set(checked))


async def test_unreadable_destinations_fails_closed_for_cross_tenant_actor(monkeypatch):
    organization_id = uuid4()
    destination, source = [conversation(organization_id) for _ in range(2)]
    service = setup_service(
        monkeypatch,
        [(destination.id, source.id)],
        {destination.id: destination, source.id: source},
    )
    actor = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")

    assert await service.unreadable_destinations(organization_id, actor.user_id, actor) == {
        destination.id
    }
    service._may_read_direct.assert_not_awaited()


async def test_external_context_repository_scopes_edges_and_excludes_same_room_rows():
    organization_id, destination_id, source_id = uuid4(), uuid4(), uuid4()
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [(destination_id, source_id)])

    edges = await context_repo.external_context_edges(
        db,
        organization_id=organization_id,
        destination_ids={destination_id},
    )

    assert edges == [(destination_id, source_id)]
    sql = str(db.execute.await_args.args[0])
    assert "room_threads.organization_id" in sql
    assert "room_threads.context_source_conversation_id != room_threads.conversation_id" in sql
