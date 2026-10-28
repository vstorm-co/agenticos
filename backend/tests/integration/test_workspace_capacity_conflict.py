"""The atomic merge cap and its durable recovery copy, on real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.sandbox._capped import CappedStateBackend, document_size
from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import agent_workspace as repository
from app.services import sandbox_workspace as service
from tests.integration.test_agent_publish_concurrency import _setup
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize("delete_source", [False, True])
async def test_concurrent_files_and_directories_keep_the_cap_and_a_recoverable_snapshot(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, delete_source: bool
) -> None:
    async with asyncio.timeout(15):
        ctx, agent = await _setup(db)
        row = await repository.create(
            db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            scope="agent",
            scope_key=f"test-{uuid4().hex}",
            backend="state",
        )
        await db.commit()
        monkeypatch.setattr(service.settings, "SANDBOX_STATE_MAX_BYTES", 1200)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        copying, release = asyncio.Event(), asyncio.Event()

        @asynccontextmanager
        async def context() -> AsyncIterator[AsyncSession]:
            async with factory() as session, session.begin():
                yield session
                if delete_source:
                    copying.set()
                    await release.wait()

        monkeypatch.setattr(service, "get_worker_db_context", context)

        def opened(path: str) -> service.OpenWorkspace:
            document = CappedStateBackend(max_bytes=1200)
            document.write_bytes(f"/{path}/result.txt", b"x" * 600)
            document.make_dir(f"/{path}/empty")
            return service.OpenWorkspace(
                workspace=document_workspace(document),
                kind="state",
                scope="agent",
                scope_key=row.scope_key,
                row_id=row.id,
                opened_version=0,
                document=document,
            )

        first, second = opened("first"), opened("second")
        async with factory() as one, factory() as two:
            # Both runs loaded version zero before either stored its accepted writes.
            assert (
                await one.scalar(select(AgentWorkspace.version).where(AgentWorkspace.id == row.id))
                == 0
            )
            assert (
                await two.scalar(select(AgentWorkspace.version).where(AgentWorkspace.id == row.id))
                == 0
            )
            first_result = await service.SandboxWorkspaceService(one).close(first)
            assert first_result is None
            await one.commit()
            if delete_source:

                async def remove_source() -> None:
                    async with factory() as deleting:
                        await deleting.execute(
                            delete(AgentWorkspace).where(AgentWorkspace.id == row.id)
                        )
                        await deleting.commit()

                async with asyncio.TaskGroup() as group:
                    closing = group.create_task(service.SandboxWorkspaceService(two).close(second))
                    await copying.wait()
                    deleting = group.create_task(remove_source())
                    done, _ = await asyncio.wait({deleting}, timeout=0.05)
                    assert not done
                    release.set()
                    result = await closing
                    await two.rollback()
            else:
                result = await service.SandboxWorkspaceService(two).close(second)
            assert isinstance(result, service.WorkspaceFlushFailure)
            assert result.error.details is not None
            recovery_id = UUID(result.error.details["recovery_workspace_id"])
            # A request returning 409 rolls back; the recovery snapshot must survive.
            await two.rollback()

        if delete_source:
            assert (
                await db.scalar(
                    select(AgentWorkspace.id).where(AgentWorkspace.id.in_([row.id, recovery_id]))
                )
                is None
            )
            return
        await db.refresh(row)
        assert set(row.files or {}) == {"/first/result.txt"}
        assert row.bytes_total == document_size(row.files or {}, row.directories or ()) <= 1200
        recovery = await repository.get(db, recovery_id, organization_id=ctx.organization_id)
        assert recovery is not None
        assert set(recovery.files or {}) == {"/second/result.txt"}
        assert "/second/empty" in (recovery.directories or ())
        assert (
            recovery.bytes_total
            == document_size(recovery.files or {}, recovery.directories or ())
            <= 1200
        )
        assert recovery.agent_id == row.agent_id and recovery.scope == row.scope
        assert recovery.recovery_of_id == row.id
        assert await repository.get(db, recovery_id, organization_id=uuid4()) is None
        await db.execute(delete(AgentWorkspace).where(AgentWorkspace.id == row.id))
        await db.commit()
        assert (
            await db.scalar(
                select(AgentWorkspace.id).where(AgentWorkspace.id.in_([row.id, recovery_id]))
            )
            is None
        )


@pytest.mark.parametrize("level", [None, "read", "use"])
async def test_project_recovery_discovery_and_downloads_follow_real_grants(
    db: AsyncSession, level: str | None
) -> None:
    from app.core.permissions import AuthContext
    from app.db.models.organization import OrganizationMember
    from app.db.models.project import Project
    from app.db.models.resource_grant import ResourceGrant
    from app.db.models.user import User

    owner, _ = await _setup(db)
    subject = User(email=f"reader-{uuid4()}@example.com", hashed_password="x")
    db.add(subject)
    await db.flush()
    db.add(
        OrganizationMember(organization_id=owner.organization_id, user_id=subject.id, role="viewer")
    )
    project = Project(
        organization_id=owner.organization_id,
        owner_user_id=owner.user_id,
        name="Private",
        visibility="private",
        backend="state",
    )
    db.add(project)
    await db.flush()
    source = await repository.create(
        db,
        organization_id=owner.organization_id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"dp-{project.id.hex}",
        backend="state",
    )
    recovery = await repository.create(
        db,
        organization_id=owner.organization_id,
        agent_id=None,
        project_id=project.id,
        scope="project",
        scope_key=f"recovery-{uuid4().hex}",
        backend="state",
        recovery_of_id=source.id,
    )
    if level is not None:
        db.add(
            ResourceGrant(
                organization_id=owner.organization_id,
                resource_type="project",
                resource_id=project.id,
                subject_user_id=subject.id,
                level=level,
                created_by_user_id=owner.user_id,
            )
        )
    await db.flush()
    ctx = AuthContext(user_id=subject.id, organization_id=owner.organization_id, role="viewer")
    workspaces = service.SandboxWorkspaceService(db)
    listed = await workspaces.visible_to(ctx)
    assert [item.row.id for item in listed] == ([recovery.id] if level == "use" else [])
    assert await workspaces._may_read(ctx, recovery) is (level == "use")
    assert await workspaces._may_read(ctx, source) is False
    assert (
        await repository.get_for_project(
            db, organization_id=ctx.organization_id, project_id=project.id
        )
    ).id == source.id
