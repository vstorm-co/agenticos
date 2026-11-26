"""A conversation's SQL cascade must not erase its remote cleanup obligation."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic_ai.workspaces import WorkspaceUnavailableError
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import deps
from app.core.background import _DEFERRED_KEY
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.pending_sandbox_destroy import PendingSandboxDestroy
from app.db.models.sandbox_connection import SandboxConnection
from app.db.models.user import User
from app.db.session import _managed_session
from app.main import app
from app.repositories import conversation_repo
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.sandbox_workspace import SandboxWorkspaceService

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


async def _case(db: AsyncSession) -> tuple[User, Organization, Conversation, AgentWorkspace]:
    owner = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(owner)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Delete locks", slug=uuid4().hex, created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    connection = SandboxConnection(
        id=uuid4(),
        organization_id=org.id,
        name="Cleanup provider",
        kind="opensandbox",
        base_url="https://sandbox.invalid",
        default_runtime="test-image",
    )
    conversation = Conversation(
        id=uuid4(), user_id=owner.id, organization_id=org.id, title="Delete"
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
        session_id="remote-to-destroy",
    )
    db.add(workspace)
    await db.flush()
    return owner, org, conversation, workspace


def _caller(owner: User, org: Organization) -> AuthContext:
    app.dependency_overrides[deps.get_current_user] = lambda: owner
    app.dependency_overrides[deps.get_active_organization] = lambda: SimpleNamespace(id=org.id)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    return ctx


async def test_delete_holds_the_parent_before_the_workspace_purge_boundary(
    db: AsyncSession, engine: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org, conversation, workspace = await _case(db)
    await db.commit()
    _caller(owner, org)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def request_session() -> AsyncIterator[AsyncSession]:
        async with _managed_session(factory) as session:
            yield session

    app.dependency_overrides[deps.get_db_session] = request_session
    reached, proceed = asyncio.Event(), asyncio.Event()
    original = SandboxWorkspaceService.purge_for_conversation

    async def paused(
        self: SandboxWorkspaceService, ctx: AuthContext, *, conversation_id: UUID
    ) -> int:
        reached.set()
        await proceed.wait()
        return await original(self, ctx, conversation_id=conversation_id)

    monkeypatch.setattr(SandboxWorkspaceService, "purge_for_conversation", paused)
    monkeypatch.setattr(
        SandboxConnectionService,
        "resolve_for_teardown",
        AsyncMock(side_effect=WorkspaceUnavailableError("Offline")),
    )
    deleting = asyncio.create_task(client.delete(f"/api/v1/conversations/{conversation.id}"))
    try:
        await asyncio.wait_for(reached.wait(), 10)
        async with factory() as account:
            await account.execute(select(User.id).where(User.id == owner.id).with_for_update())
            with pytest.raises(DBAPIError) as refusal:
                await conversation_repo.lock_authored_histories(account, user_id=owner.id)
            assert getattr(refusal.value.orig, "sqlstate", None) == "55P03"
            await account.rollback()
    finally:
        proceed.set()
        response = await asyncio.wait_for(deleting, 10)
    assert response.status_code == 204
    async with factory() as verified:
        assert await verified.get(Conversation, conversation.id) is None
        assert await verified.get(AgentWorkspace, workspace.id) is None
        assert (
            await verified.scalars(select(PendingSandboxDestroy))
        ).one().ref_id == "remote-to-destroy"


@pytest.mark.security
async def test_a_final_refusal_rolls_back_workspace_tombstone_and_deferred_destroy(
    db: AsyncSession, engine: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org, conversation, workspace = await _case(db)
    replacement = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(replacement)
    await db.commit()
    ctx = _caller(owner, org)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sessions: list[AsyncSession] = []

    async def request_session() -> AsyncIterator[AsyncSession]:
        async with _managed_session(factory) as session:
            sessions.append(session)
            yield session

    app.dependency_overrides[deps.get_db_session] = request_session
    destroy = AsyncMock()
    monkeypatch.setattr("app.services.sandbox_workspace._destroy_and_forget", destroy)
    connection = await db.get(SandboxConnection, workspace.connection_id)
    assert connection is not None
    monkeypatch.setattr(
        SandboxConnectionService,
        "resolve_for_teardown",
        AsyncMock(return_value=ResolvedConnection(connection, "test-only-token")),
    )
    original = SandboxWorkspaceService.purge_for_conversation

    async def purge_then_revoke(
        self: SandboxWorkspaceService, caller: AuthContext, *, conversation_id: UUID
    ) -> int:
        count = await original(self, caller, conversation_id=conversation_id)
        assert await self.db.scalar(select(PendingSandboxDestroy.id)) is not None
        assert self.db.info.get(_DEFERRED_KEY)
        # Exercise the final authorization refusal after cleanup was staged, before commit.
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(user_id=replacement.id)
        )
        return count

    monkeypatch.setattr(SandboxWorkspaceService, "purge_for_conversation", purge_then_revoke)
    response = await client.delete(f"/api/v1/conversations/{conversation.id}")
    assert response.status_code == 404
    destroy.assert_not_awaited()
    assert len(sessions) == 1 and not sessions[0].info.get(_DEFERRED_KEY)
    async with factory() as verified:
        restored = await verified.get(Conversation, conversation.id)
        assert restored is not None and restored.user_id == ctx.user_id
        assert await verified.get(AgentWorkspace, workspace.id) is not None
        assert await verified.scalar(select(PendingSandboxDestroy.id)) is None


@pytest.mark.security
async def test_a_parent_changed_while_waiting_is_reauthorized_before_purge(
    db: AsyncSession, engine: AsyncEngine, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, org, conversation, workspace = await _case(db)
    replacement = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(replacement)
    await db.commit()
    _caller(owner, org)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def request_session() -> AsyncIterator[AsyncSession]:
        async with _managed_session(factory) as session:
            yield session

    app.dependency_overrides[deps.get_db_session] = request_session
    reached = asyncio.Event()
    original = conversation_repo.lock_for_deletion

    async def acquire(
        session: AsyncSession, *, conversation_id: UUID, organization_id: UUID
    ) -> Conversation | None:
        reached.set()
        return await original(
            session, conversation_id=conversation_id, organization_id=organization_id
        )

    monkeypatch.setattr(conversation_repo, "lock_for_deletion", acquire)
    purge = AsyncMock()
    monkeypatch.setattr(SandboxWorkspaceService, "purge_for_conversation", purge)
    async with factory() as changed:
        await changed.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(user_id=replacement.id)
        )
        deleting = asyncio.create_task(client.delete(f"/api/v1/conversations/{conversation.id}"))
        try:
            await asyncio.wait_for(reached.wait(), 10)
        finally:
            await changed.commit()
            response = await asyncio.wait_for(deleting, 10)
    assert response.status_code == 404
    purge.assert_not_awaited()
    async with factory() as verified:
        remaining = await verified.get(Conversation, conversation.id)
        assert remaining is not None and remaining.user_id == replacement.id
        assert await verified.get(AgentWorkspace, workspace.id) is not None
        assert await verified.scalar(select(PendingSandboxDestroy.id)) is None
