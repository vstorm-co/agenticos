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


def _db() -> AsyncMock:
    """A session for routes whose service is mocked: no query reaches it.

    A function rather than `AsyncMock` itself, which FastAPI would read the
    constructor of as the dependency's parameters.
    """
    return AsyncMock()


@pytest.fixture
def service(mock_redis: MagicMock) -> Iterator[MagicMock]:
    service = MagicMock()
    app.dependency_overrides[deps.get_visual_service] = lambda: service
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_db_session] = _db
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


async def test_a_thread_opened_by_its_link_carries_its_drawings(mock_redis: MagicMock) -> None:
    """The link answered 500 for every thread: the route promised a member's
    conversation and returned the link's narrower shape. It now says what it
    returns, and a drawing arrives finished rather than as the call that made it."""
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import patch

    message = SimpleNamespace(
        id=uuid4(),
        role="assistant",
        content="Here it is.",
        created_at=datetime(2026, 10, 16, tzinfo=UTC),
        tool_calls=[
            SimpleNamespace(
                tool_call_id="d",
                tool_name="draw",
                args={"title": "Flow", "kind": "svg", "content": "<svg/>", "secret": "x"},
                status="completed",
                result="Drew 'Flow' as visual `d`.",
            )
        ],
    )
    conversation = SimpleNamespace(
        id=uuid4(), organization_id=uuid4(), project_id=None, title="Shared", messages=[message]
    )
    share = SimpleNamespace(
        id=uuid4(), conversation_id=conversation.id, permission="view", share_token="tok"
    )
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_db_session] = _db
    try:
        with (
            patch(
                "app.services.conversation_share.conversation_share_repo.get_by_token",
                new=AsyncMock(return_value=share),
            ),
            patch(
                "app.services.conversation_share.conversation_repo.get_conversation_by_id",
                new=AsyncMock(return_value=conversation),
            ),
        ):
            response = await _call("GET", f"{settings.API_V1_STR}/conversations/shared/tok")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["share"]["permission"] == "view"
    shared = body["conversation"]["messages"][0]
    assert shared["visuals"] == [{"id": "d", "title": "Flow", "kind": "svg", "content": "<svg/>"}]
    assert "tool_calls" not in shared


async def test_the_caller_s_recent_drawings_are_listed(service: MagicMock) -> None:
    from app.schemas.visual import VisualList

    context = _as(OrgRoleName.MEMBER)
    service.recent = AsyncMock(return_value=VisualList(items=[]))

    response = await _call("GET", f"{settings.API_V1_STR}/visuals?limit=6")

    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert service.recent.await_args.args == (context,)
    assert service.recent.await_args.kwargs == {"limit": 6}


async def test_a_thumbnail_is_a_png_that_runs_nothing(service: MagicMock) -> None:
    _as(OrgRoleName.MEMBER)
    service.thumbnail = AsyncMock(return_value=b"\x89PNG")
    visual_id = uuid4()

    response = await _call("GET", f"{settings.API_V1_STR}/visuals/{visual_id}/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert service.thumbnail.await_args.args[1] == visual_id


async def test_the_console_s_thumbnail_reaches_the_service(service: MagicMock) -> None:
    context = _as(OrgRoleName.MEMBER)
    service.save_thumbnail = AsyncMock()

    response = await _call(
        "POST",
        f"{BASE}/thumbnail",
        files={"file": ("thumbnail.png", b"\x89PNG", "image/png")},
    )

    assert response.status_code == 204
    assert service.save_thumbnail.await_args.args == (
        context,
        CONVERSATION_ID,
        "toolu_1",
        b"\x89PNG",
    )
