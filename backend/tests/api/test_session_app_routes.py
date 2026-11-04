"""`PUT /sessions/current/app` and the list's `is_current` (#2305, #2097)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import NotFoundError
from app.main import app
from app.schemas.session import SessionAppUpdate, SessionListResponse

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _client(
    *, service: MagicMock, user_id: UUID, session_id: UUID | None
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_current_user] = lambda: MagicMock(id=user_id)
    app.dependency_overrides[deps.get_current_session_id] = lambda: session_id
    app.dependency_overrides[deps.get_session_service] = lambda: service
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_the_console_in_an_app_labels_its_own_session() -> None:
    user_id, session_id = uuid4(), uuid4()
    service = MagicMock(record_app=AsyncMock())
    async with _client(service=service, user_id=user_id, session_id=session_id) as client:
        response = await client.put(
            "/api/v1/sessions/current/app", json={"platform": "macos", "version": "0.2.0"}
        )
    assert response.status_code == 204
    service.record_app.assert_awaited_once_with(
        session_id, user_id, SessionAppUpdate(platform="macos", version="0.2.0")
    )


async def test_a_request_with_no_session_is_a_404_and_a_bad_body_a_422() -> None:
    service = MagicMock(record_app=AsyncMock(side_effect=NotFoundError(message="none")))
    async with _client(service=service, user_id=uuid4(), session_id=None) as client:
        missing = await client.put(
            "/api/v1/sessions/current/app", json={"platform": "ios", "version": "0.1.0"}
        )
        invalid = await client.put(
            "/api/v1/sessions/current/app", json={"platform": "toaster", "version": "1"}
        )
    assert missing.status_code == 404
    assert invalid.status_code == 422


async def test_the_list_is_told_which_session_is_the_callers() -> None:
    user_id, session_id = uuid4(), uuid4()
    service = MagicMock(
        list_sessions=AsyncMock(return_value=SessionListResponse(items=[], total=0))
    )
    async with _client(service=service, user_id=user_id, session_id=session_id) as client:
        response = await client.get("/api/v1/sessions")
    assert response.status_code == 200
    assert service.list_sessions.await_args.kwargs["current_session_id"] == session_id
