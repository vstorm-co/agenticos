"""The memory-file routes, through the app.

`tests/api/test_platform_routes.py` proves these routes carry no role gate and
delegate to a service that resolves access per agent; `tests/test_memory_service.py`
proves the service refuses where the database is. What is left is the handlers
and the shapes they return - the index carries origin/kind/size without the body,
the partition filter translates to the service's arguments, a create answers 201,
a promote 200 and a delete 204.

The real service runs with the repository stubbed at the database edge and access
resolved to yes, so the assertions are about what the route returns.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.memory import AgentMemoryFact, AgentMemoryFile, MemoryOrigin
from app.main import app
from app.services.memory.facade import MemoryService

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()
_AGENT_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

FACADE = "app.services.memory.facade"


def _row(name: str = "prefs", *, origin: str = MemoryOrigin.AGENT.value) -> AgentMemoryFile:
    return AgentMemoryFile(
        id=uuid.uuid4(),
        organization_id=_ORGANIZATION_ID,
        agent_id=_AGENT_ID,
        end_user_scope_key=None,
        name=name,
        description=f"about {name}",
        content="# body\n\nremembered",
        format="md",
        kind="note",
        origin=origin,
    )


@pytest.fixture
def client(mock_redis: MagicMock) -> Iterator[OpenClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_memory_service] = lambda: MemoryService(MagicMock())

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


def _url(suffix: str = "") -> str:
    return f"{settings.API_V1_STR}/memory{suffix}"


def _agent() -> MagicMock:
    """An agent row with nothing published, so the mem0 guard reads the draft alone."""
    return MagicMock(
        id=_AGENT_ID, organization_id=_ORGANIZATION_ID, draft_spec={}, current_version_id=None
    )


def _reachable():
    """The parent agent exists and access resolves to yes."""
    return (
        patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=_agent())),
        patch(f"{FACADE}.resolve_access", new=AsyncMock(return_value=True)),
    )


class TestListing:
    async def test_the_index_carries_origin_and_size_without_the_body(self, client: OpenClient):
        rows = [
            _row("prefs", origin=MemoryOrigin.AGENT.value),
            _row("policy", origin=MemoryOrigin.OPERATOR.value),
        ]
        get_agent, allow = _reachable()
        with (
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.list_for_agent", new=AsyncMock(return_value=(rows, 2))),
        ):
            async with client() as http:
                response = await http.get(_url(f"/files?agent_id={_AGENT_ID}"))
        assert response.status_code == 200
        body = response.json()
        by_name = {item["name"]: item for item in body["items"]}
        assert by_name["policy"]["origin"] == "operator"
        assert by_name["prefs"]["size_bytes"] > 0
        assert "content" not in by_name["prefs"]

    @pytest.mark.parametrize(
        ("partition", "all_partitions", "scope_key", "scoped_only"),
        [
            ("all", True, None, False),
            ("shared", False, None, False),
            ("per_user", False, None, True),
            ("user:42", False, "user:42", False),
        ],
    )
    async def test_the_partition_filter_translates_to_service_arguments(
        self,
        client: OpenClient,
        partition: str,
        all_partitions: bool,
        scope_key: str | None,
        scoped_only: bool,
    ):
        get_agent, allow = _reachable()
        with (
            get_agent,
            allow,
            patch(
                f"{FACADE}.memory_repo.list_for_agent", new=AsyncMock(return_value=([], 0))
            ) as listed,
        ):
            async with client() as http:
                await http.get(_url(f"/files?agent_id={_AGENT_ID}&partition={partition}"))
        assert listed.call_args.kwargs["all_partitions"] is all_partitions
        assert listed.call_args.kwargs["scope_key"] == scope_key
        assert listed.call_args.kwargs["scoped_only"] is scoped_only

    async def test_a_listing_without_an_agent_is_refused(self, client: OpenClient):
        async with client() as http:
            response = await http.get(_url("/files"))
        assert response.status_code == 422

    async def test_a_sort_the_repository_does_not_know_is_refused(self, client: OpenClient):
        async with client() as http:
            response = await http.get(_url(f"/files?agent_id={_AGENT_ID}&sort=oldest"))
        assert response.status_code == 422


class TestCreate:
    async def test_creating_a_file_answers_201_with_an_operator_row(self, client: OpenClient):
        created = _row("policy", origin=MemoryOrigin.OPERATOR.value)
        get_agent, allow = _reachable()
        with (
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{FACADE}.memory_repo.create", new=AsyncMock(return_value=created)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.post(
                    _url("/files"),
                    json={"agent_id": str(_AGENT_ID), "name": "policy", "content": "body"},
                )
        assert response.status_code == 201
        assert response.json()["origin"] == "operator"
        assert response.json()["content"] == created.content

    async def test_creating_a_fact_answers_201_with_the_embedded_row(self, client: OpenClient):
        fact_id = uuid.uuid4()
        get_agent, allow = _reachable()
        with (
            get_agent,
            allow,
            patch(f"{FACADE}.assert_organization_within_budget", new=AsyncMock()),
            patch(f"{FACADE}.embed_operator_fact", new=AsyncMock(return_value=[0.1])),
            patch(f"{FACADE}.memory_repo.create_fact", new=AsyncMock(return_value=(fact_id, None))),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.post(
                    _url("/facts"),
                    json={"agent_id": str(_AGENT_ID), "content": "Acme FY starts in April"},
                )
        assert response.status_code == 201
        assert response.json()["content"] == "Acme FY starts in April"
        assert response.json()["id"] == str(fact_id)
        assert response.json()["origin"] == "operator"


class TestGetPatchPromoteDelete:
    async def test_reading_one_file_returns_its_body(self, client: OpenClient):
        row = _row()
        get_agent, allow = _reachable()
        with patch(f"{FACADE}.memory_repo.get", new=AsyncMock(return_value=row)), get_agent, allow:
            async with client() as http:
                response = await http.get(_url(f"/files/{row.id}"))
        assert response.status_code == 200
        assert response.json()["content"] == row.content

    async def test_editing_a_file_returns_the_updated_row(self, client: OpenClient):
        row = _row()
        get_agent, allow = _reachable()
        with (
            patch(f"{FACADE}.memory_repo.get", new=AsyncMock(return_value=row)),
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.update", new=AsyncMock(return_value=row)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.patch(_url(f"/files/{row.id}"), json={"content": "new"})
        assert response.status_code == 200

    async def test_promoting_a_file_returns_200(self, client: OpenClient):
        row = _row(origin=MemoryOrigin.AGENT.value)
        get_agent, allow = _reachable()
        with (
            patch(f"{FACADE}.memory_repo.get", new=AsyncMock(return_value=row)),
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.update", new=AsyncMock(return_value=row)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.post(_url(f"/files/{row.id}/promote"))
        assert response.status_code == 200

    async def test_deleting_a_file_answers_204(self, client: OpenClient):
        row = _row()
        get_agent, allow = _reachable()
        with (
            patch(f"{FACADE}.memory_repo.get", new=AsyncMock(return_value=row)),
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.delete", new=AsyncMock()),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/files/{row.id}"))
        assert response.status_code == 204


def _fact_row(content: str = "likes tea") -> AgentMemoryFact:
    return AgentMemoryFact(
        id=uuid.uuid4(),
        organization_id=_ORGANIZATION_ID,
        agent_id=_AGENT_ID,
        end_user_scope_key=None,
        content=content,
        origin=MemoryOrigin.AGENT.value,
    )


class TestFacts:
    async def test_listing_carries_the_fact_content(self, client: OpenClient):
        get_agent, allow = _reachable()
        with (
            get_agent,
            allow,
            patch(
                f"{FACADE}.memory_repo.list_facts",
                new=AsyncMock(return_value=([_fact_row("likes tea")], 1)),
            ),
        ):
            async with client() as http:
                response = await http.get(_url(f"/facts?agent_id={_AGENT_ID}"))
        assert response.status_code == 200
        assert response.json()["items"][0]["content"] == "likes tea"

    async def test_reading_one_fact(self, client: OpenClient):
        fact = _fact_row()
        get_agent, allow = _reachable()
        with (
            patch(f"{FACADE}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
            get_agent,
            allow,
        ):
            async with client() as http:
                response = await http.get(_url(f"/facts/{fact.id}"))
        assert response.status_code == 200
        assert response.json()["content"] == fact.content

    async def test_deleting_a_fact_answers_204(self, client: OpenClient):
        fact = _fact_row()
        get_agent, allow = _reachable()
        with (
            patch(f"{FACADE}.memory_repo.get_fact", new=AsyncMock(return_value=fact)),
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.delete_fact", new=AsyncMock()),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/facts/{fact.id}"))
        assert response.status_code == 204


class TestClear:
    async def test_clearing_all_memory_answers_204(self, client: OpenClient):
        get_agent, allow = _reachable()
        with (
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.delete_all_files", new=AsyncMock(return_value=2)) as files,
            patch(f"{FACADE}.memory_repo.delete_all_facts", new=AsyncMock(return_value=1)) as facts,
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.delete(_url(f"?agent_id={_AGENT_ID}"))
        assert response.status_code == 204
        files.assert_awaited_once()
        facts.assert_awaited_once()

    async def test_clearing_all_facts_answers_204(self, client: OpenClient):
        get_agent, allow = _reachable()
        with (
            get_agent,
            allow,
            patch(f"{FACADE}.memory_repo.delete_all_facts", new=AsyncMock(return_value=3)) as facts,
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            async with client() as http:
                response = await http.delete(_url(f"/facts?agent_id={_AGENT_ID}"))
        assert response.status_code == 204
        facts.assert_awaited_once()

    async def test_clearing_without_an_agent_is_refused(self, client: OpenClient):
        async with client() as http:
            response = await http.delete(_url())
        assert response.status_code == 422
