"""The route that sets how often a connected mailbox is checked."""

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

URL = f"{settings.API_V1_STR}/mcp-connections/portals/{{}}/poll-interval"


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()

    async def set_poll_interval(ctx: AuthContext, *, connection_id: uuid.UUID, minutes: int):
        return MagicMock(id=connection_id, poll_interval_minutes=minutes)

    stub.set_poll_interval = AsyncMock(side_effect=set_poll_interval)
    return stub


@pytest.fixture
def client(service: MagicMock) -> Iterator[AsyncClient]:
    context = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    app.dependency_overrides[deps.get_mcp_connection_service] = lambda: service
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_it_sets_one_of_the_allowed_intervals(
    client: AsyncClient, service: MagicMock
) -> None:
    connection_id = uuid.uuid4()
    async with client as http:
        response = await http.put(URL.format(connection_id), json={"poll_interval_minutes": 15})

    assert response.status_code == 200
    assert response.json() == {"connection_id": str(connection_id), "poll_interval_minutes": 15}
    assert service.set_poll_interval.await_args.kwargs == {
        "connection_id": connection_id,
        "minutes": 15,
    }


@pytest.mark.parametrize("value", [0, 2, 61, 120, -5, "often", None])
async def test_a_value_outside_the_set_is_refused_naming_the_field(
    client: AsyncClient, service: MagicMock, value: object
) -> None:
    async with client as http:
        response = await http.put(URL.format(uuid.uuid4()), json={"poll_interval_minutes": value})

    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert [entry["field"] for entry in fields] == ["poll_interval_minutes"]
    service.set_poll_interval.assert_not_awaited()


async def test_another_organizations_grant_is_a_404(
    client: AsyncClient, service: MagicMock
) -> None:
    service.set_poll_interval.side_effect = NotFoundError(message="Connection not found")
    async with client as http:
        response = await http.put(URL.format(uuid.uuid4()), json={"poll_interval_minutes": 5})

    assert response.status_code == 404
