"""A conversation's SQL cascade must not erase its remote cleanup obligation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic_ai.workspaces import WorkspaceUnavailableError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.pending_sandbox_destroy import PendingSandboxDestroy
from app.db.models.sandbox_connection import SandboxConnection
from app.db.models.user import User
from app.main import app
from app.services.sandbox_connection import SandboxConnectionService

pytestmark = pytest.mark.anyio


async def test_delete_retains_the_remote_ref_before_cascading_its_workspace(
    db: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(owner)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Sandbox cleanup", slug=uuid4().hex, created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    connection = SandboxConnection(
        id=uuid4(), organization_id=org.id, name="Offline provider", kind="opensandbox"
    )
    conversation = Conversation(
        id=uuid4(), user_id=owner.id, organization_id=org.id, title="Delete me"
    )
    db.add_all([connection, conversation])
    await db.flush()
    workspace = AgentWorkspace(
        id=uuid4(),
        organization_id=org.id,
        conversation_id=conversation.id,
        scope="conversation",
        scope_key=uuid4().hex,
        backend="service",
        connection_id=connection.id,
        session_id="remote-workspace-to-destroy",
    )
    db.add(workspace)
    await db.flush()
    conversation_id, workspace_id = conversation.id, workspace.id
    monkeypatch.setattr(
        SandboxConnectionService,
        "resolve_for_teardown",
        AsyncMock(
            side_effect=WorkspaceUnavailableError("Provider temporarily unavailable"),
        ),
    )

    async def session() -> AsyncSession:
        return db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_current_user] = lambda: owner
    app.dependency_overrides[deps.get_active_organization] = lambda: SimpleNamespace(id=org.id)
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=owner.id,
        organization_id=org.id,
        role=OrgRoleName.OWNER,
    )
    response = await client.delete(f"/api/v1/conversations/{conversation_id}")
    assert response.status_code == 204
    assert (
        await db.scalar(select(Conversation.id).where(Conversation.id == conversation_id)) is None
    )
    assert (
        await db.scalar(select(AgentWorkspace.id).where(AgentWorkspace.id == workspace_id)) is None
    )
    pending = (await db.scalars(select(PendingSandboxDestroy))).one()
    assert pending.ref_id == "remote-workspace-to-destroy"
    assert pending.connection_id == connection.id
    assert pending.organization_id == org.id
