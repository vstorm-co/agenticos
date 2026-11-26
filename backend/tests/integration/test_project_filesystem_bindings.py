"""Real tenant predicates, unique credentials and expiring run leases in PostgreSQL."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import RunAudience
from app.db.models.conversation import Conversation
from app.db.models.project import Project
from app.db.models.project_filesystem import ProjectFilesystemBinding, ProjectFilesystemLease
from app.db.models.sandbox_connection import SandboxConnection
from app.repositories import project_filesystem_bindings as repo
from app.schemas.project import ProjectCreate
from app.schemas.project_filesystem import FsList, FsRead, FsSuccess, FsWrite
from app.schemas.project_filesystem_authority import ProjectFilesystemAuthority
from app.services.project import ProjectService
from app.services.project_filesystem_bindings import ProjectFilesystemBindingService
from app.services.project_filesystem_gateway import ProjectFilesystemGateway
from tests.integration.test_agent_attention import _agent, _run
from tests.integration.test_workflow_exposures import _ctx, _org, _user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_real_binding_predicates_uniqueness_and_lease_expiry(db: AsyncSession) -> None:
    user = await _user(db)
    organization = await _org(db, owner=user)
    other_organization = await _org(db, owner=user)
    ctx = _ctx(user, organization)
    connection = SandboxConnection(
        organization_id=organization.id, name="private mount host", kind="docker", is_active=True
    )
    db.add(connection)
    await db.flush()
    conversation = Conversation(organization_id=organization.id, user_id=user.id)
    db.add(conversation)
    await db.flush()
    project_read = await ProjectService(db).create(
        ctx, ProjectCreate(name="Live namespace", backend="state")
    )
    project = await db.get(Project, project_read.id)
    assert project is not None
    agent = await _agent(db, organization, user, "Filesystem authority")
    run = await _run(db, agent, status="running", user_id=user.id, conversation_id=conversation.id)
    service = ProjectFilesystemBindingService(db)
    kwargs = {
        "organization_id": organization.id,
        "connection_id": connection.id,
        "session_name": "private-session",
        "workspace_id": None,
        "conversation_id": conversation.id,
    }
    credential = await service.credential(**kwargs)
    binding = await repo.binding_by_id(db, credential.binding_id, for_update=True)
    assert binding is not None
    assert (await service.credential(**kwargs)).token == credential.token
    assert (
        await repo.binding_for_session(
            db,
            organization_id=other_organization.id,
            connection_id=connection.id,
            session_name="private-session",
        )
        is None
    )
    assert (
        await repo.binding_for_session(
            db,
            organization_id=organization.id,
            connection_id=uuid4(),
            session_name="private-session",
        )
        is None
    )
    assert (
        await repo.binding_for_session(
            db,
            organization_id=organization.id,
            connection_id=connection.id,
            session_name="another-session",
        )
        is None
    )
    candidate = ProjectFilesystemBinding(
        id=uuid4(),
        organization_id=organization.id,
        connection_id=connection.id,
        session_name="private-session",
        conversation_id=conversation.id,
        workspace_id=None,
        token_digest="different",
        ciphertext="losing-envelope",
        secret_key_version=1,
    )
    await repo.insert_binding(db, row=candidate)
    winner = await repo.binding_for_session(
        db,
        organization_id=organization.id,
        connection_id=connection.id,
        session_name="private-session",
    )
    assert winner is not None and winner.id == binding.id and winner.token_digest != "different"
    authority = ProjectFilesystemAuthority(
        actor=ctx,
        audience=RunAudience(user_id=user.id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        conversation_id=conversation.id,
        conversation_project_id=None,
    )
    view = await service.issue_lease(
        binding_id=binding.id,
        project_id=project.id,
        generation=project.workspace_generation,
        run_id=run.id,
        authority=authority,
    )
    lease = await repo.lease_for_binding(db, binding=binding, lease_id=view.id)
    assert lease is not None
    another_binding = ProjectFilesystemBinding(
        id=uuid4(),
        organization_id=organization.id,
        connection_id=connection.id,
        session_name="other-session",
        conversation_id=conversation.id,
        token_digest="other",
        ciphertext="other-envelope",
        secret_key_version=1,
    )
    await repo.insert_binding(db, row=another_binding)
    assert await repo.lease_for_binding(db, binding=another_binding, lease_id=view.id) is None
    # Even the same opaque binding ID under a forged tenant cannot pass the SQL tenant predicate.
    impostor = ProjectFilesystemBinding(id=binding.id, organization_id=other_organization.id)
    assert await repo.lease_for_binding(db, binding=impostor, lease_id=view.id) is None
    now = datetime.now(UTC)
    assert [item.id for item in await repo.live_leases(db, binding=binding, now=now)] == [lease.id]
    assert not await repo.renew_lease(
        db,
        lease_id=lease.id,
        run_id=uuid4(),
        organization_id=organization.id,
        now=now,
        expires_at=now + timedelta(seconds=90),
    )
    assert not await repo.renew_lease(
        db,
        lease_id=lease.id,
        run_id=run.id,
        organization_id=other_organization.id,
        now=now,
        expires_at=now + timedelta(seconds=90),
    )
    assert await repo.renew_lease(
        db,
        lease_id=lease.id,
        run_id=run.id,
        organization_id=organization.id,
        now=now,
        expires_at=now + timedelta(seconds=120),
    )
    await repo.revoke_lease(
        db, lease_id=lease.id, run_id=uuid4(), organization_id=organization.id, now=now
    )
    await db.refresh(lease)
    assert lease.revoked_at is None
    await repo.revoke_lease(
        db, lease_id=lease.id, run_id=run.id, organization_id=organization.id, now=now
    )
    await db.refresh(lease)
    assert lease.revoked_at == now and await repo.live_leases(db, binding=binding, now=now) == []
    assert not await repo.renew_lease(
        db,
        lease_id=lease.id,
        run_id=run.id,
        organization_id=organization.id,
        now=now,
        expires_at=now + timedelta(seconds=120),
    )
    expired = ProjectFilesystemLease(
        id=uuid4(),
        organization_id=organization.id,
        binding_id=binding.id,
        project_id=project.id,
        run_id=run.id,
        actor_id=user.id,
        authority_json=authority.model_dump_json(),
        expires_at=now - timedelta(seconds=1),
    )
    await repo.create_lease(db, lease=expired)
    assert await repo.live_leases(db, binding=binding, now=now) == []
    assert not await repo.renew_lease(
        db,
        lease_id=expired.id,
        run_id=run.id,
        organization_id=organization.id,
        now=now,
        expires_at=now + timedelta(seconds=120),
    )


async def test_real_gateway_writes_reach_project_and_expired_run_disappears(
    db: AsyncSession,
) -> None:
    user = await _user(db)
    organization = await _org(db, owner=user)
    ctx = _ctx(user, organization)
    connection = SandboxConnection(
        organization_id=organization.id, name="gateway host", kind="docker", is_active=True
    )
    conversation = Conversation(organization_id=organization.id, user_id=user.id)
    db.add_all([connection, conversation])
    await db.flush()
    created = await ProjectService(db).create(ctx, ProjectCreate(name="Mount ACK", backend="state"))
    project = await db.get(Project, created.id)
    assert project is not None
    agent = await _agent(db, organization, user, "Gateway writes")
    run = await _run(db, agent, status="running", user_id=user.id, conversation_id=conversation.id)
    bindings = ProjectFilesystemBindingService(db)
    credential = await bindings.credential(
        organization_id=organization.id,
        connection_id=connection.id,
        session_name="gateway-session",
        workspace_id=None,
        conversation_id=conversation.id,
    )
    authority = ProjectFilesystemAuthority(
        actor=ctx,
        audience=RunAudience(user_id=user.id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        conversation_id=conversation.id,
        conversation_project_id=None,
    )
    lease = await bindings.issue_lease(
        binding_id=credential.binding_id,
        project_id=project.id,
        generation=project.workspace_generation,
        run_id=run.id,
        authority=authority,
    )
    gateway = ProjectFilesystemGateway(db)
    from app.schemas.project_filesystem import FsCreate

    token = SecretStr(credential.token.get_secret_value())
    await gateway.perform(
        credential.binding_id, token, FsCreate(op="create", path=f"{lease.id}/file")
    )
    await gateway.perform(
        credential.binding_id,
        token,
        FsWrite(op="write", path=f"{lease.id}/file", data="YmluYXJ5AGJ5dGVz"),
    )
    await db.commit()
    result = await gateway.perform(
        credential.binding_id, token, FsRead(op="read", path=f"{lease.id}/file", count=12)
    )
    assert isinstance(result, FsSuccess) and result.data == "YmluYXJ5AGJ5dGVz" and result.eof
    run.status = "completed"
    await db.flush()
    listing = await gateway.perform(credential.binding_id, token, FsList(op="list"))
    assert isinstance(listing, FsSuccess) and listing.entries == []
