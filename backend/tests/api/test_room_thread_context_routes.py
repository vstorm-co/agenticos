"""The range and placement routes expose the revision-checked context contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.room_submission import RoomThreadContextCandidatesRead
from app.schemas.room_thread import (
    RoomThreadContextActionRead,
    RoomThreadContextRead,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_ORG = UUID("00000000-0000-4000-8000-000000000001")
_USER = UUID("00000000-0000-4000-8000-000000000002")
_CONVERSATION = UUID("00000000-0000-4000-8000-000000000003")
_ROOT = UUID("00000000-0000-4000-8000-000000000004")
_FIRST = UUID("00000000-0000-4000-8000-000000000005")
_LAST = UUID("00000000-0000-4000-8000-000000000006")


def action() -> RoomThreadContextActionRead:
    return RoomThreadContextActionRead(
        conversation_id=_CONVERSATION,
        root_message_id=_ROOT,
        state="open",
        following=False,
        unread=0,
        can_manage=True,
        context=RoomThreadContextRead(
            source_conversation_id=_CONVERSATION,
            start_message_id=_FIRST,
            end_message_id=_LAST,
            first_ordinal=1,
            last_ordinal=2,
            excluded_message_ids=[],
            message_ids=[_FIRST, _LAST],
            message_count=2,
            moved=False,
            revision=1,
        ),
    )


def route_calls() -> list[tuple[str, str, dict[str, object], str, int]]:
    return [
        (
            "POST",
            f"/api/v1/conversations/{_CONVERSATION}/room-threads",
            {
                "source_conversation_id": str(_CONVERSATION),
                "start_message_id": str(_FIRST),
                "end_message_id": str(_LAST),
                "excluded_message_ids": [],
                "title": None,
            },
            "create_context",
            201,
        ),
        (
            "PATCH",
            f"/api/v1/conversations/{_CONVERSATION}/room-threads/{_ROOT}/context",
            {
                "source_conversation_id": str(_CONVERSATION),
                "start_message_id": str(_FIRST),
                "end_message_id": str(_LAST),
                "excluded_message_ids": [],
                "expected_context_revision": 1,
                "move": True,
            },
            "update_context",
            200,
        ),
        (
            "POST",
            f"/api/v1/conversations/{_CONVERSATION}/room-threads/{_ROOT}/context/move",
            {"expected_context_revision": 1},
            "move_context",
            200,
        ),
        (
            "POST",
            f"/api/v1/conversations/{_CONVERSATION}/room-threads/{_ROOT}/context/return",
            {"expected_context_revision": 1},
            "return_context",
            200,
        ),
    ]


@pytest.mark.parametrize("method,path,body,service_method,status_code", route_calls())
async def test_context_actions_return_metadata_and_delegate_the_revision_contract(
    method: str,
    path: str,
    body: dict[str, object],
    service_method: str,
    status_code: int,
) -> None:
    ctx = AuthContext(user_id=_USER, organization_id=_ORG, role="member")
    call = AsyncMock(return_value=action())
    service = SimpleNamespace(
        create_context=call,
        update_context=call,
        move_context=call,
        return_context=call,
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_room_thread_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(method, path, json=body)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == status_code, response.text
    assert response.json()["context"]["message_ids"] == [str(_FIRST), str(_LAST)]
    call.assert_awaited_once()
    assert call.await_args is not None
    assert call.await_args.args[0] == ctx
    assert call.await_args.args[1] == _CONVERSATION
    if service_method == "create_context":
        assert call.await_args.args[2].start_message_id == _FIRST
    elif service_method == "update_context":
        assert call.await_args.args[2] == _ROOT
        assert call.await_args.args[3].expected_context_revision == 1
    else:
        assert call.await_args.args[2] == _ROOT
        assert call.await_args.args[3] == 1


async def test_context_candidates_route_uses_the_authorized_read_service() -> None:
    ctx = AuthContext(user_id=_USER, organization_id=_ORG, role="member")
    call = AsyncMock(
        return_value=RoomThreadContextCandidatesRead(
            source_conversation_id=_CONVERSATION,
            items=[],
            total=0,
        )
    )
    service = SimpleNamespace(candidates=call)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_room_thread_context_read_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/conversations/{_CONVERSATION}/room-threads/{_ROOT}/context/candidates"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json() == {
        "source_conversation_id": str(_CONVERSATION),
        "items": [],
        "total": 0,
    }
    call.assert_awaited_once_with(ctx, _CONVERSATION, _ROOT)
