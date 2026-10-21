"""`GET /providers/realtime-models`: the Voice card's picker, over the wire (#54)."""

import uuid
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app

pytestmark = pytest.mark.anyio

_V1 = settings.API_V1_STR


@pytest.fixture
def member() -> Iterator[None]:
    """A signed-in member, who holds `agents:view`."""
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.MEMBER.value,
        is_app_admin=False,
    )
    yield
    app.dependency_overrides.clear()


@pytest.mark.usefixtures("member")
async def test_the_catalog_lists_providers_and_their_voices(client: AsyncClient):
    resp = await client.get(f"{_V1}/providers/realtime-models")

    assert resp.status_code == 200
    body = resp.json()
    openai = next(item for item in body["items"] if item["provider"] == "openai")
    assert openai["models"][0]["transport"] == "webrtc"
    assert "marin" in openai["models"][0]["voices"]
    assert body["total"] == len(body["items"])
