"""Saving a visual as an app and reading its pictures, through the app.

The service's own rules are pinned in `tests/test_visual_service.py`. What is left
is the wiring: saving is gated on `artifacts:edit`, the caller's context reaches
the service, and a picture is answered with a type and a policy that runs nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.visual import VisualPublished

pytestmark = pytest.mark.anyio

CONVERSATION_ID = uuid4()
BASE = f"{settings.API_V1_STR}/conversations/{CONVERSATION_ID}/visuals/toolu_1"


@pytest.fixture
def service(mock_redis: MagicMock) -> Iterator[MagicMock]:
    service = MagicMock()
    app.dependency_overrides[deps.get_visual_service] = lambda: service
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_db_session] = lambda: AsyncMock()
    yield service
    app.dependency_overrides.clear()


def _as(role: OrgRoleName) -> AuthContext:
    context = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=str(role))
    app.dependency_overrides[deps.get_auth_context] = lambda: context
    return context


async def _call(method: str, url: str, **kwargs: object):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await http.request(method, url, **kwargs)


async def test_saving_a_visual_reaches_the_service_with_the_caller(service: MagicMock) -> None:
    context = _as(OrgRoleName.MEMBER)
    published = VisualPublished(
        artifact_id=uuid4(),
        version=1,
        name="flow",
        title="Flow",
        created=True,
        unchanged=False,
        url="/apps/x",
    )
    service.publish = AsyncMock(return_value=published)

    response = await _call("POST", f"{BASE}/publish", json={"name": "flow"})

    assert response.status_code == 201
    assert response.json()["version"] == 1
    ctx, conversation_id, visual_id, data = service.publish.await_args.args
    assert ctx == context
    assert (conversation_id, visual_id, data.name) == (CONVERSATION_ID, "toolu_1", "flow")


@pytest.mark.security
async def test_saving_takes_artifacts_edit(service: MagicMock) -> None:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid4(), organization_id=uuid4(), role="no-such-role"
    )
    service.publish = AsyncMock()
    response = await _call("POST", f"{BASE}/publish", json={"name": "flow"})
    assert response.status_code == 403
    service.publish.assert_not_called()


@pytest.mark.security
async def test_a_picture_is_served_typed_and_inert(service: MagicMock) -> None:
    _as(OrgRoleName.MEMBER)
    service.image = AsyncMock(return_value=(b"<svg/>", "image/svg+xml"))

    response = await _call("GET", f"{BASE}/images/logo")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert service.image.await_args.args[1:] == (CONVERSATION_ID, "toolu_1", "logo")
