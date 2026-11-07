"""Public key scopes must not become new role gates for signed-in chats."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.main import app
from app.schemas.conversation import ConversationRead

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("operation", ["list", "create", "update"])
@pytest.mark.parametrize("caller", ["member", "viewer", "scoped-key", "unscoped-key"])
async def test_conversation_key_scopes_preserve_session_access(operation: str, caller: str) -> None:
    person, organization, conversation = uuid4(), uuid4(), uuid4()
    permission = Perm.RUNS_VIEW if operation == "list" else Perm.AGENTS_RUN
    is_key = caller.endswith("key")
    ctx = AuthContext(
        user_id=person,
        organization_id=organization,
        role=OrgRoleName.VIEWER if caller == "viewer" else OrgRoleName.MEMBER,
        api_key_id=uuid4() if is_key else None,
        key_scopes=frozenset({permission})
        if caller == "scoped-key"
        else frozenset()
        if is_key
        else None,
    )
    saved = ConversationRead(
        id=conversation,
        title="Project",
        user_id=person,
        organization_id=organization,
        created_at=datetime.now(UTC),
    )
    service = MagicMock(
        list_conversations=AsyncMock(return_value=([], 0)),
        create_conversation=AsyncMock(return_value=saved),
        update_conversation=AsyncMock(return_value=saved),
    )
    app.dependency_overrides[deps.get_current_user] = lambda: SimpleNamespace(
        id=person, is_app_admin=False
    )
    app.dependency_overrides[deps.get_active_organization] = lambda: SimpleNamespace(
        id=organization
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_conversation_service] = lambda: service

    def database_session() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[deps.get_db_session] = database_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            path = f"{settings.API_V1_STR}/conversations"
            if operation == "list":
                response = await client.get(path)
                call = service.list_conversations
            elif operation == "create":
                response = await client.post(path, json={"title": "Project"})
                call = service.create_conversation
            else:
                response = await client.patch(f"{path}/{conversation}", json={"title": "Renamed"})
                call = service.update_conversation
        if caller == "unscoped-key":
            assert response.status_code == 403
            call.assert_not_awaited()
        else:
            assert response.status_code == (201 if operation == "create" else 200), response.text
            call.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()
