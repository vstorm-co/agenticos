"""Every room routing route uses the member's live resource authority."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.main import app
from app.services.conversation import ConversationService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def routes():
    proposal = uuid4()
    return [
        ("GET", "lead-policy", None),
        ("PUT", "lead-policy", {"expected_revision": 0, "enabled": False}),
        ("GET", "routing-proposals", None),
        ("GET", f"routing-proposals/{proposal}", None),
        (
            "POST",
            f"routing-proposals/{proposal}/accept",
            {
                "expected_revision": 1,
                "idempotency_key": "decision",
                "selected_item_ids": [str(uuid4())],
            },
        ),
        (
            "POST",
            f"routing-proposals/{proposal}/discard",
            {"expected_revision": 1, "idempotency_key": "decision"},
        ),
        ("GET", "task-links", None),
    ]


@pytest.mark.parametrize("method,path,body", routes())
@pytest.mark.parametrize("identity", ["member", "api_key", "anonymous"])
async def test_routing_never_widens_authentication_or_reveals_an_unreadable_room(
    monkeypatch, method, path, body, identity
):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    if identity == "api_key":
        ctx = replace(ctx, api_key_id=uuid4())
    elif identity == "anonymous":
        ctx = replace(ctx, user_id=None)
    conversation_id = uuid4()
    read = AsyncMock(side_effect=NotFoundError(message="Room not found"))
    monkeypatch.setattr(ConversationService, "get_conversation", read)
    db = MagicMock(info={})
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_db_session] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(
                method, f"/api/v1/conversations/{conversation_id}/{path}", json=body
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == (404 if identity == "member" else 403), response.text
    if identity == "member":
        read.assert_awaited_once()
        assert read.await_args.args == (conversation_id,)
        assert read.await_args.kwargs["organization_id"] == ctx.organization_id
        assert read.await_args.kwargs["ctx"] == ctx
    else:
        read.assert_not_awaited()
