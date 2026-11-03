"""The Discord role mapping routes: wired to `channels:manage`, answering with names (#2569).

The service is a stand-in here; what it refuses beyond the route gate is pinned
against a real database in `tests/integration/test_discord_role_groups.py`.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.discord_role_mapping import DiscordRoleMapping
from app.main import app
from app.services.channels.discord_protocol import Server, ServerRole

pytestmark = pytest.mark.anyio

BOT = uuid.uuid4()
BASE = f"{settings.API_V1_STR}/channels/bots/{BOT}"


def _mapping() -> DiscordRoleMapping:
    return DiscordRoleMapping(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        channel_bot_id=BOT,
        guild_id="1100",
        discord_role_id="7",
        guild_name="Acme HQ",
        discord_role_name="Finance",
        group_id=uuid.uuid4(),
        role="member",
        created_at=datetime.now(UTC),
    )


def _service() -> AsyncMock:
    service = AsyncMock()
    service.servers.return_value = [
        Server(id="1100", name="Acme HQ", roles=(ServerRole(id="7", name="Finance"),))
    ]
    service.list_mappings.return_value = [(_mapping(), "Finance team")]
    service.create.return_value = (_mapping(), "Finance team")
    service.delete.return_value = None
    return service


async def _call(role: str, method: str, path: str, **kwargs: object) -> tuple[Response, AsyncMock]:
    service = _service()
    app.dependency_overrides[deps.get_discord_role_mapping_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.request(method, f"{BASE}{path}", **kwargs)
    finally:
        app.dependency_overrides.clear()
    return answer, service


MAPPING_ID = uuid.UUID("5f0c1d2e-0000-4000-8000-000000000001")
CREATE = {"guild_id": "1100", "discord_role_id": "7", "group_id": str(uuid.uuid4())}


async def test_the_servers_are_listed_with_the_roles_a_mapping_may_name() -> None:
    answer, _ = await _call(OrgRoleName.ADMIN, "GET", "/discord-servers")

    assert answer.status_code == 200
    assert answer.json() == {
        "items": [{"id": "1100", "name": "Acme HQ", "roles": [{"id": "7", "name": "Finance"}]}],
        "total": 1,
    }


async def test_a_mapping_is_listed_with_its_groups_name() -> None:
    answer, _ = await _call(OrgRoleName.ADMIN, "GET", "/role-mappings")

    assert answer.status_code == 200
    [item] = answer.json()["items"]
    assert (item["group_name"], item["discord_role_name"], item["role"]) == (
        "Finance team",
        "Finance",
        "member",
    )


async def test_creating_a_mapping_answers_201_with_the_row() -> None:
    answer, service = await _call(OrgRoleName.ADMIN, "POST", "/role-mappings", json=CREATE)

    assert answer.status_code == 201
    assert answer.json()["group_name"] == "Finance team"
    service.create.assert_awaited_once()


async def test_deleting_a_mapping_answers_204() -> None:
    answer, service = await _call(OrgRoleName.ADMIN, "DELETE", f"/role-mappings/{uuid.uuid4()}")

    assert answer.status_code == 204
    service.delete.assert_awaited_once()


@pytest.mark.parametrize(
    "body",
    [
        {**CREATE, "guild_id": "not-a-snowflake"},
        {**CREATE, "discord_role_id": "0"},
        {**CREATE, "role": "owner"},
    ],
)
async def test_an_id_that_is_not_discords_or_an_owner_role_is_refused(body: dict[str, str]) -> None:
    answer, service = await _call(OrgRoleName.OWNER, "POST", "/role-mappings", json=body)

    assert answer.status_code == 422
    service.create.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/discord-servers", {}),
        ("GET", "/role-mappings", {}),
        ("POST", "/role-mappings", {"json": CREATE}),
        ("DELETE", f"/role-mappings/{MAPPING_ID}", {}),
    ],
)
async def test_a_viewer_is_refused_every_route(
    method: str, path: str, kwargs: dict[str, object]
) -> None:
    answer, service = await _call(OrgRoleName.VIEWER, method, path, **kwargs)

    assert answer.status_code == 403
    assert not service.method_calls
