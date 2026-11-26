"""Run-local project files persist and lose access on real membership changes."""

from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import RunAudience
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.project import Project
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.services.run_project_workspace import RunProjectWorkspace
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_selected_files_persist_and_revoked_membership_blocks_the_next_operation(
    db: AsyncSession,
) -> None:
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Workspace test", slug=str(uuid4()), created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(id=uuid4(), organization_id=org.id, user_id=user.id, role="owner"))
    project = Project(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        name="Research",
        instructions="",
        backend="state",
        visibility="private",
    )
    db.add(project)
    await db.commit()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    original = document_workspace()
    await original.write_text("private.txt", "keep in conversation")
    selector = RunProjectWorkspace(
        original,
        ctx,
        audience=RunAudience(user_id=ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
    await selector.select(project.id)
    await selector.write_file("report.md", "saved in project")
    assert not await original.exists("report.md")
    # A different run opens the persisted document, rather than a cached handle.
    next_run = RunProjectWorkspace(
        document_workspace(),
        ctx,
        audience=RunAudience(user_id=ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
    assert next_run.project_id is None
    await next_run.select(project.id)
    assert "saved in project" in await next_run.read_file("report.md")
    assert "private.txt" not in await next_run.files()
    await db.execute(delete(OrganizationMember).where(OrganizationMember.organization_id == org.id))
    await db.commit()
    with pytest.raises(PermissionError, match="membership"):
        await selector.write_file("report.md", "must not save")
    await selector.select(None)
    assert await selector.workspace.read_text("private.txt") == "keep in conversation"


async def test_selection_cannot_cross_tenants_or_private_project_grants(db: AsyncSession) -> None:
    person = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    owner = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add_all([person, owner])
    await db.flush()
    orgs = [
        Organization(id=uuid4(), name="Test", slug=str(uuid4()), created_by_user_id=owner.id)
        for _ in range(2)
    ]
    db.add_all(orgs)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid4(), organization_id=orgs[0].id, user_id=person.id, role="member")
    )
    projects = [
        Project(
            id=uuid4(),
            organization_id=org.id,
            owner_user_id=owner.id,
            name="Private",
            instructions="",
            backend="state",
            visibility="private",
        )
        for org in orgs
    ]
    db.add_all(projects)
    await db.commit()
    selector = RunProjectWorkspace(
        document_workspace(),
        AuthContext(user_id=person.id, organization_id=orgs[0].id, role="member"),
        audience=RunAudience(user_id=person.id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
    for project in projects:
        with pytest.raises(NotFoundError):
            await selector.select(project.id)
        assert selector.project_id is None

    grant = ResourceGrant(
        id=uuid4(),
        organization_id=orgs[0].id,
        resource_type="project",
        resource_id=projects[0].id,
        subject_user_id=person.id,
        level="use",
    )
    db.add(grant)
    await db.commit()
    await selector.select(projects[0].id)
    await selector.write_file("notes.md", "shared by grant")
    await db.execute(delete(ResourceGrant).where(ResourceGrant.id == grant.id))
    await db.commit()
    with pytest.raises(PermissionError, match="Project not found"):
        await selector.read_file("notes.md")


async def test_project_staged_uploads_are_visible_and_final_close_preserves_later_tool_edits(
    db: AsyncSession,
) -> None:
    from functools import partial

    from app.services.agent_runner import _initialize_project_staging
    from app.services.sandbox_workspace import SandboxWorkspaceService

    user = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Staging test", slug=str(uuid4()), created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(id=uuid4(), organization_id=org.id, user_id=user.id, role="owner"))
    project = Project(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=user.id,
        name="Staged work",
        instructions="",
        backend="state",
        visibility="private",
    )
    db.add(project)
    await db.commit()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    service = SandboxWorkspaceService(db)
    staged = await service.open_project(ctx, project)
    await staged.workspace.write_text("uploads/input.txt", "staged upload")
    await staged.workspace.write_text("existing.md", "before tools")
    await db.commit()
    selector = RunProjectWorkspace(
        document_workspace(),
        ctx,
        audience=RunAudience(user_id=ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        conversation_project_id=project.id,
    )
    selector.initialize(project, execution_target="agent")
    selector.initialize_project = partial(_initialize_project_staging, staged)
    with pytest.raises(FileNotFoundError):
        await selector.read_file("missing.txt")
    assert "staged upload" in await selector.read_file("uploads/input.txt")
    assert "before tools" in await selector.read_file("existing.md")
    await selector.write_file("existing.md", "edited by project tool")
    await selector.write_file("later.md", "added by project tool")
    assert await service.close(staged) is None
    await db.commit()
    assert "edited by project tool" in await selector.read_file("existing.md")
    assert "added by project tool" in await selector.read_file("later.md")
    assert "staged upload" in await selector.read_file("uploads/input.txt")
