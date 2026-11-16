"""Run-local project files persist and lose access on real membership changes."""

from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

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
    selector = RunProjectWorkspace(original, ctx)
    await selector.select(project.id)
    await selector.workspace.write_text("report.md", "saved in project")
    assert not await original.exists("report.md")
    # A different run opens the persisted document, rather than a cached handle.
    next_run = RunProjectWorkspace(document_workspace(), ctx)
    assert next_run.project_id is None
    await next_run.select(project.id)
    assert await next_run.workspace.read_text("report.md") == "saved in project"
    assert not await next_run.workspace.exists("private.txt")
    await db.execute(delete(OrganizationMember).where(OrganizationMember.organization_id == org.id))
    await db.commit()
    with pytest.raises(PermissionError, match="membership"):
        await selector.workspace.write_text("report.md", "must not save")
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
    await selector.workspace.write_text("notes.md", "shared by grant")
    await db.execute(delete(ResourceGrant).where(ResourceGrant.id == grant.id))
    await db.commit()
    with pytest.raises(PermissionError, match="Project not found"):
        await selector.workspace.read_text("notes.md")
