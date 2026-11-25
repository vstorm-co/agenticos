"""Concrete project/agent file identities survive a run without widening access."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.sandbox._identity import WorkspaceIdentity
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.organization import OrganizationMember
from app.db.models.project import Project
from app.db.models.resource_grant import ResourceGrant
from app.repositories import agent_run_repo, agent_workspace_repo
from app.services.project import ProjectService
from app.services.sandbox_workspace import OpenWorkspace, SandboxWorkspaceService
from tests.integration.test_run_history_filters import _agent, _ctx, _org, _run, _user
from tests.integration.test_workspace_visibility import _conversation

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _agent_files(
    db: AsyncSession, ctx: AuthContext, agent_id: UUID, conversation_id: UUID, run_id: UUID
) -> OpenWorkspace:
    spec = AgentSpec(
        name="Files",
        capabilities=[CapabilityBindingSpec(id="sandbox", config={"backend": "state"})],
    )
    service = SandboxWorkspaceService(db)
    opened = await service.open(
        spec,
        ctx=ctx,
        identity=WorkspaceIdentity(
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            run_id=run_id,
            conversation_id=conversation_id,
            user_id=str(ctx.user_id),
        ),
    )
    assert opened is not None and opened.row_id is not None
    await opened.workspace.write_text("same.txt", "agent bytes")
    await opened.workspace.write_text("agent-only.txt", "only in agent workspace")
    assert await service.close(opened) is None
    return opened


async def _project(db: AsyncSession, ctx: AuthContext) -> Project:
    project = Project(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name="XYZ",
        instructions="Use the project reference.",
        backend="state",
        visibility="private",
    )
    db.add(project)
    await db.flush()
    await ProjectService(db).add_file(ctx, project.id, path="same.txt", data=b"project bytes")
    await ProjectService(db).add_file(
        ctx, project.id, path="project-only.txt", data=b"only in project"
    )
    return project


async def test_distinct_origins_read_their_own_bytes_and_do_not_fall_back_by_path(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db)
    ctx = _ctx(org, owner)
    agent = await _agent(db, org)
    conversation = await _conversation(db, org, owner, agent)
    run = await _run(db, org, agent, user_id=owner.id, conversation_id=conversation.id)
    project = await _project(db, ctx)
    original = await _agent_files(db, ctx, agent.id, conversation.id, run.id)
    project_row = await agent_workspace_repo.get_for_project(
        db, organization_id=org.id, project_id=project.id
    )
    assert project_row is not None and original.row_id is not None
    await agent_run_repo.record_workspace_origins(
        db,
        run=run,
        origins=[
            {"kind": "agent", "workspace_id": str(original.row_id)},
            {"kind": "project", "workspace_id": str(project_row.id), "project_id": str(project.id)},
        ],
    )
    origins = await SandboxWorkspaceService(db).origins(ctx, conversation_id=conversation.id)
    assert {(item.kind, item.workspace_id) for item in origins.items} == {
        ("agent", original.row_id),
        ("project", project_row.id),
    }
    assert origins.default_origin == "agent"
    assert await ProjectService(db).file_bytes(ctx, project.id, path="same.txt") == b"project bytes"
    assert (
        await SandboxWorkspaceService(db).read_bytes_of(ctx, original.row_id, path="same.txt")
        == b"agent bytes"
    )
    with pytest.raises(NotFoundError):
        await ProjectService(db).file_bytes(ctx, project.id, path="agent-only.txt")
    with pytest.raises(NotFoundError):
        await SandboxWorkspaceService(db).read_bytes_of(
            ctx, original.row_id, path="project-only.txt"
        )


async def test_project_chat_keeps_project_default_after_agent_executor_materializes(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db)
    ctx = _ctx(org, owner)
    agent = await _agent(db, org)
    conversation = await _conversation(db, org, owner, agent)
    project = await _project(db, ctx)
    conversation.project_id = project.id
    run = await _run(db, org, agent, user_id=owner.id, conversation_id=conversation.id)
    await _agent_files(db, ctx, agent.id, conversation.id, run.id)
    kept = await agent_workspace_repo.kept_for_conversation(
        db, organization_id=org.id, conversation_id=conversation.id
    )
    assert kept is not None and kept.project_id == project.id
    origins = await SandboxWorkspaceService(db).origins(ctx, conversation_id=conversation.id)
    assert origins.default_origin == "project"
    assert {item.kind for item in origins.items} == {"agent", "project"}


async def test_dynamic_project_origin_disappears_after_its_grant_is_revoked(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db)
    creator = _ctx(org, owner)
    person = await _user(db)
    db.add(OrganizationMember(id=uuid4(), organization_id=org.id, user_id=person.id, role="member"))
    await db.flush()
    ctx = AuthContext(user_id=person.id, organization_id=org.id, role="member")
    project = await _project(db, creator)
    grant = ResourceGrant(
        id=uuid4(),
        organization_id=org.id,
        resource_type="project",
        resource_id=project.id,
        subject_user_id=person.id,
        level="use",
    )
    db.add(grant)
    await db.flush()
    agent = await _agent(db, org)
    conversation = await _conversation(db, org, person, agent)
    run = await _run(db, org, agent, user_id=person.id, conversation_id=conversation.id)
    row = await agent_workspace_repo.get_for_project(
        db, organization_id=org.id, project_id=project.id
    )
    assert row is not None
    await agent_run_repo.record_workspace_origins(
        db,
        run=run,
        origins=[{"kind": "project", "workspace_id": str(row.id), "project_id": str(project.id)}],
    )
    before = await SandboxWorkspaceService(db).origins(ctx, conversation_id=conversation.id)
    assert [item.project_id for item in before.items] == [project.id]
    await db.delete(grant)
    await db.flush()
    after = await SandboxWorkspaceService(db).origins(ctx, conversation_id=conversation.id)
    assert after.items == []
    with pytest.raises((AuthorizationError, NotFoundError)):
        await ProjectService(db).file_bytes(ctx, project.id, path="same.txt")


async def test_origin_refs_never_lend_a_workspace_from_another_tenant(db: AsyncSession) -> None:
    org, owner = await _org(db)
    ctx = _ctx(org, owner)
    agent = await _agent(db, org)
    conversation = await _conversation(db, org, owner, agent)
    run = await _run(db, org, agent, user_id=owner.id, conversation_id=conversation.id)
    elsewhere, other_owner = await _org(db)
    other_agent = await _agent(db, elsewhere)
    other_chat = await _conversation(db, elsewhere, other_owner, other_agent)
    foreign = await _agent_files(
        db, _ctx(elsewhere, other_owner), other_agent.id, other_chat.id, uuid4()
    )
    assert foreign.row_id is not None
    await agent_run_repo.record_workspace_origins(
        db, run=run, origins=[{"kind": "agent", "workspace_id": str(foreign.row_id)}]
    )
    assert (
        await SandboxWorkspaceService(db).origins(ctx, conversation_id=conversation.id)
    ).items == []
    with pytest.raises(NotFoundError):
        await SandboxWorkspaceService(db).read_bytes_of(ctx, foreign.row_id, path="same.txt")


async def test_origins_remain_recorded_for_failed_or_cancelled_runs(db: AsyncSession) -> None:
    org, owner = await _org(db)
    agent = await _agent(db, org)
    conversation = await _conversation(db, org, owner, agent)
    failed = await _run(
        db, org, agent, user_id=owner.id, conversation_id=conversation.id, status="failed"
    )
    cancelled = await _run(
        db, org, agent, user_id=owner.id, conversation_id=conversation.id, status="cancelled"
    )
    opened = await _agent_files(db, _ctx(org, owner), agent.id, conversation.id, failed.id)
    assert opened.row_id is not None
    ref = {"kind": "agent", "workspace_id": str(opened.row_id)}
    await agent_run_repo.record_workspace_origins(db, run=failed, origins=[ref])
    await agent_run_repo.record_workspace_origins(db, run=cancelled, origins=[ref])
    refs = await agent_workspace_repo.recorded_origins(
        db, organization_id=org.id, conversation_id=conversation.id
    )
    assert len(refs) == 1 and refs[0].workspace_id == opened.row_id


async def test_shared_project_conversation_files_recheck_membership_and_grants(
    db: AsyncSession,
) -> None:
    org, owner = await _org(db)
    ctx = _ctx(org, owner)
    agent = await _agent(db, org)
    project = await _project(db, ctx)
    conversation = await _conversation(db, org, owner, agent)
    conversation.project_id = project.id
    run = await _run(db, org, agent, user_id=owner.id, conversation_id=conversation.id)
    opened = await _agent_files(db, ctx, agent.id, conversation.id, run.id)
    assert opened.row_id is not None
    reader = await _user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=reader.id, role="member"))
    grant = ResourceGrant(
        organization_id=org.id,
        resource_type="project",
        resource_id=project.id,
        subject_user_id=reader.id,
        level="use",
    )
    db.add(grant)
    await db.flush()
    reader_ctx = AuthContext(user_id=reader.id, organization_id=org.id, role="member")
    await agent_run_repo.record_workspace_origins(
        db, run=run, origins=[{"kind": "agent", "workspace_id": str(opened.row_id)}]
    )
    service = SandboxWorkspaceService(db)
    assert await service.read_bytes_of(reader_ctx, opened.row_id, path="same.txt") == b"agent bytes"
    assert (await service.origins(reader_ctx, conversation_id=conversation.id)).items
    await db.delete(grant)
    await db.flush()
    with pytest.raises((NotFoundError, AuthorizationError)):
        await service.read_bytes_of(reader_ctx, opened.row_id, path="same.txt")
    with pytest.raises((NotFoundError, AuthorizationError)):
        await service.origins(reader_ctx, conversation_id=conversation.id)
