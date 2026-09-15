"""The agent metadata command route, through the app.

`tests/api/test_platform_routes.py` proves this per-resource PATCH carries no
role gate and that `GET /agents` keeps its `agents:view` one;
`tests/test_agent_registry.py` proves the service checks `agents:edit` and
persists. What is left is the handler itself: it parses the body, answers an
`AgentRead`, refuses an invalid body at the edge with a 422, and reports a
cross-tenant target as a 404 - and a Viewer holding an explicit edit grant
reaches it, since the route delegates to the grant-aware service.

The real service runs with the repository stubbed at the database edge.
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
from app.db.models.agent import Agent, AgentStatus
from app.db.models.resource_grant import GrantLevel, Visibility
from app.main import app
from app.services.agent_registry import AgentRegistryService

pytestmark = pytest.mark.anyio

_ORGANIZATION_ID = uuid.uuid4()

OpenClient = Callable[[], AbstractAsyncContextManager[AsyncClient]]

REGISTRY_PATH = "app.services.agent_registry"


def _agent(*, categories: list[str] | None = None, tags: list[str] | None = None) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        organization_id=_ORGANIZATION_ID,
        owner_user_id=uuid.uuid4(),
        visibility=Visibility.PRIVATE.value,
        slug="support",
        name="Support",
        description=None,
        status=AgentStatus.DRAFT.value,
        draft_spec={},
        categories=categories or [],
        tags=tags or [],
    )


def _client_for(role: str) -> Iterator[OpenClient]:
    context = AuthContext(user_id=uuid.uuid4(), organization_id=_ORGANIZATION_ID, role=role)
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_agent_registry_service] = lambda: AgentRegistryService(
        MagicMock()
    )

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


@pytest.fixture
def owner_client() -> Iterator[OpenClient]:
    yield from _client_for(OrgRoleName.OWNER)


@pytest.fixture
def viewer_client() -> Iterator[OpenClient]:
    yield from _client_for(OrgRoleName.VIEWER)


def _url(agent_id: uuid.UUID) -> str:
    return f"{settings.API_V1_STR}/agents/{agent_id}/metadata"


async def test_setting_metadata_answers_the_normalized_agent_read(owner_client: OpenClient):
    agent = _agent()
    saved = _agent(categories=["sales"], tags=["eu"])
    saved.id = agent.id
    with (
        patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=saved)) as update,
    ):
        async with owner_client() as http:
            response = await http.patch(
                _url(agent.id),
                json={"categories": ["Sales", "sales"], "tags": ["  EU  "]},
            )
    assert response.status_code == 200
    body = response.json()
    assert body["categories"] == ["sales"]
    assert body["tags"] == ["eu"]
    # The body reached the service already folded, so duplicates never hit the row.
    assert update.call_args.kwargs["update_data"] == {"categories": ["sales"], "tags": ["eu"]}


async def test_an_over_length_label_is_refused_at_the_edge(owner_client: OpenClient):
    async with owner_client() as http:
        response = await http.patch(_url(uuid.uuid4()), json={"tags": ["x" * 33]})
    assert response.status_code == 422


async def test_too_many_categories_are_refused_at_the_edge(owner_client: OpenClient):
    async with owner_client() as http:
        response = await http.patch(
            _url(uuid.uuid4()), json={"categories": [f"c{i}" for i in range(11)]}
        )
    assert response.status_code == 422


async def test_a_cross_tenant_target_is_a_not_found(owner_client: OpenClient):
    """The org filter in the repo read means another tenant's agent is missing."""
    with patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=None)):
        async with owner_client() as http:
            response = await http.patch(_url(uuid.uuid4()), json={"tags": ["x"]})
    assert response.status_code == 404


async def test_a_viewer_with_an_edit_grant_reaches_the_route(viewer_client: OpenClient):
    """No role gate on the route, so the grant-aware service is what decides."""
    agent = _agent()
    with (
        patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
        patch(
            "app.services.access.resource_grant_repo.get_level",
            new=AsyncMock(return_value=GrantLevel.EDIT),
        ),
        patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)),
    ):
        async with viewer_client() as http:
            response = await http.patch(_url(agent.id), json={"tags": ["ops"]})
    assert response.status_code == 200
