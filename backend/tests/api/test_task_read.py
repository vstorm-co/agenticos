"""A task URL remains a scoped lookup and malformed identifiers never reach storage."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.main import app

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_task_lookup_keeps_the_authenticated_tenant_and_rejects_invalid_ids():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    identifier = uuid4()
    read = AsyncMock(side_effect=NotFoundError(message="Task not found"))
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_durable_task_service] = lambda: MagicMock(get=read)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/tasks/{identifier}")
            malformed = await client.get("/api/v1/tasks/not-an-id")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert malformed.status_code == 422
    read.assert_awaited_once_with(ctx, identifier)


async def test_table_assignment_options_use_authenticated_scope_without_a_collection_gate():
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    identifier = uuid4()
    options = AsyncMock(return_value=[])
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_durable_task_service] = lambda: MagicMock(
        assignee_options=options
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/tables/{identifier}/assignee-options")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == []
    options.assert_awaited_once_with(ctx, identifier)
