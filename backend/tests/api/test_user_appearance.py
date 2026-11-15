"""The account route exposes only appearance and retains the key scope gate."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.api.deps import get_auth_context
from app.api.public_api import is_assistant_route, is_public_route
from app.api.routes.v1.users import router as users_router
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
def person():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    app.dependency_overrides[get_auth_context] = lambda: ctx
    yield ctx
    app.dependency_overrides.pop(get_auth_context, None)


async def test_appearance_round_trip_uses_authenticated_account(client, person):
    row = SimpleNamespace(id=person.user_id, appearance={"look": "paper"})
    with (
        patch("app.services.user_appearance.user_repo.get_by_id", AsyncMock(return_value=row)),
        patch(
            "app.services.user_appearance.user_repo.get_by_id_for_update",
            AsyncMock(return_value=row),
        ),
        patch("app.services.user_appearance.user_repo.update", new_callable=AsyncMock) as write,
        patch("app.services.user_appearance.record_audit", new_callable=AsyncMock),
    ):
        path = f"{settings.API_V1_STR}/users/me/appearance"
        response = await client.get(path)
        assert response.status_code == 200
        assert response.json()["look"] == "paper"
        response = await client.patch(path, json={"theme": "dark"})
        assert response.status_code == 200
        assert response.json()["look"] == "paper"
        assert response.json()["theme"] == "dark"
        assert write.await_args.kwargs["db_user"].id == person.user_id
        response = await client.delete(path)
        assert response.status_code == 200
        assert response.json()["theme"] == "system"


@pytest.mark.security
async def test_route_rejects_target_account_and_arbitrary_css(client, person):
    path = f"{settings.API_V1_STR}/users/me/appearance"
    for payload in ({"user_id": str(uuid4())}, {"css": "display:none"}, {"accent": "#ff0000"}):
        response = await client.patch(path, json=payload)
        assert response.status_code == 422


@pytest.mark.security
async def test_key_needs_agent_scope_even_for_appearance(client, person):
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        user_id=person.user_id,
        organization_id=person.organization_id,
        role="owner",
        api_key_id=uuid4(),
        key_scopes=frozenset({Perm.RUNS_VIEW}),
    )
    response = await client.patch(
        f"{settings.API_V1_STR}/users/me/appearance", json={"theme": "dark"}
    )
    assert response.status_code == 403


@pytest.mark.security
async def test_appearance_is_a_platform_tool_surface_not_an_organization_key_contract():
    routes = [
        route for route in users_router.routes if getattr(route, "path", "") == "/me/appearance"
    ]
    assert len(routes) == 3
    assert all(is_assistant_route(route) and not is_public_route(route) for route in routes)
