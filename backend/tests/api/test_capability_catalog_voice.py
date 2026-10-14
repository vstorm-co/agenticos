"""The capability catalog says which capabilities a call cannot use (#54)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
def member() -> Iterator[None]:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.MEMBER.value,
        is_app_admin=False,
    )
    yield
    app.dependency_overrides.clear()


@pytest.mark.usefixtures("member")
async def test_the_catalog_says_which_capabilities_a_call_cannot_use(client: AsyncClient):
    resp = await client.get(f"{settings.API_V1_STR}/agents/capabilities")

    assert resp.status_code == 200
    by_id = {item["id"]: item for item in resp.json()["items"]}
    assert by_id["sandbox"]["voice"] is False
    assert by_id["knowledge"]["voice"] is True
