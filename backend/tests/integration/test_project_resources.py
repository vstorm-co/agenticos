"""Real foreign keys, tenant filtering and pagination of project resource links."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact
from app.db.models.project_resource import ProjectResource
from app.db.models.project_resource import ProjectResourceKind as Kind
from app.db.models.resource_grant import Visibility
from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow
from app.repositories import agent_repo
from app.repositories import project_resource as repo
from app.repositories import workflow as workflow_repo
from app.schemas.project_resource import ProjectResourceRef
from app.services.project_resources import ProjectResourceService
from tests.integration.test_project_repo import _org, _project, _user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_links_are_idempotent_multihome_and_cascade_only_the_link(db: AsyncSession):
    owner = await _user(db)
    org = await _org(db, owner=owner)
    first = await _project(db, org, owner, name="Launch", visibility="org")
    second = await _project(db, org, owner, name="Research", visibility="org")
    agent = Agent(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Helper",
        slug="helper",
        visibility="private",
        draft_spec={},
    )
    workflow = Workflow(
        id=uuid4(), organization_id=org.id, owner_user_id=owner.id, name="Main", slug="main"
    )
    app = Artifact(
        id=uuid4(), organization_id=org.id, owner_user_id=owner.id, name="report", title="Report"
    )
    table = VirtualTable(id=uuid4(), organization_id=org.id, owner_user_id=owner.id, name="Tasks")
    db.add_all([agent, workflow, app, table])
    await db.flush()
    resources = [
        (Kind.AGENT, agent),
        (Kind.WORKFLOW, workflow),
        (Kind.APP, app),
        (Kind.TABLE, table),
    ]
    for kind, row in resources:
        assert (
            await repo.get_resource(db, kind=kind, resource_id=row.id, organization_id=org.id)
            is row
        )
        assert (
            await repo.get_resource(db, kind=kind, resource_id=row.id, organization_id=uuid4())
            is None
        )
        await repo.add(db, project_id=first.id, kind=kind, resource_id=row.id)
        await repo.add(db, project_id=first.id, kind=kind, resource_id=row.id)
        listed = await repo.list_resources(
            db, organization_id=org.id, project_id=first.id, kind=kind
        )
        assert len(listed) == 1
        assert (
            await repo.list_resources(db, organization_id=uuid4(), project_id=first.id, kind=kind)
            == []
        )
    await repo.add(db, project_id=second.id, kind=Kind.AGENT, resource_id=agent.id)
    await repo.set_entrypoint(db, project_id=first.id, workflow_id=workflow.id)
    await repo.set_entrypoint(db, project_id=first.id, workflow_id=None)
    await repo.remove(db, project_id=first.id, kind=Kind.AGENT, resource_id=agent.id)
    assert await db.get(Agent, agent.id) is agent
    assert (
        await repo.member_ids(db, organization_id=org.id, project_id=first.id, kind=Kind.AGENT)
        == []
    )
    assert await repo.member_ids(
        db, organization_id=org.id, project_id=second.id, kind=Kind.AGENT
    ) == [agent.id]
    await db.delete(first)
    await db.flush()
    assert await db.get(Workflow, workflow.id) is workflow
    await db.delete(agent)
    await db.flush()
    assert (await db.execute(select(ProjectResource))).scalars().all() == []


async def test_project_membership_does_not_grant_private_resources_or_cross_tenant_access(
    db: AsyncSession,
):
    owner, reader = await _user(db), await _user(db)
    org = await _org(db, owner=owner)
    foreign_org = await _org(db, owner=reader)
    project = await _project(db, org, owner, name="Shared", visibility="org")
    hidden = Agent(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Hidden",
        slug="hidden",
        visibility="private",
        draft_spec={},
    )
    foreign = Agent(
        id=uuid4(),
        organization_id=foreign_org.id,
        owner_user_id=reader.id,
        name="Foreign",
        slug="foreign",
        draft_spec={},
    )
    db.add_all([hidden, foreign])
    await db.flush()
    await repo.add(db, project_id=project.id, kind=Kind.AGENT, resource_id=hidden.id)
    ctx = AuthContext(user_id=reader.id, organization_id=org.id, role=OrgRoleName.MEMBER)
    service = ProjectResourceService(db)
    assert (await service.list_resources(ctx, project.id)).items == []
    owner_ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
    with pytest.raises(NotFoundError):
        await service.add(
            owner_ctx, project.id, [ProjectResourceRef(kind=Kind.AGENT, resource_id=foreign.id)]
        )
    with pytest.raises(NotFoundError):
        await service.member_ids(
            AuthContext(user_id=reader.id, organization_id=foreign_org.id, role=OrgRoleName.OWNER),
            project.id,
            Kind.AGENT,
        )


async def test_registry_filters_count_before_paging_and_preserve_visibility(db: AsyncSession):
    owner, reader = await _user(db), await _user(db)
    org = await _org(db, owner=owner)
    agent = Agent(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Hidden",
        slug="hidden",
        visibility="private",
        draft_spec={},
    )
    workflow = Workflow(
        id=uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Main",
        slug="main",
        visibility="org",
    )
    db.add_all([agent, workflow])
    await db.flush()
    args = {
        "organization_id": org.id,
        "user_id": reader.id,
        "see_all": False,
        "shared_ids": [],
        "skip": 0,
        "limit": 1,
    }
    assert await agent_repo.list_visible(db, **args, only_ids=[agent.id]) == ([], 0)
    assert await workflow_repo.list_visible(db, **args, only_ids=[]) == ([], 0)
    rows, total = await workflow_repo.list_visible(db, **args, only_ids=[workflow.id])
    assert rows == [workflow] and total == 1


@pytest.mark.parametrize("invalid", ["empty", "multiple", "agent-entrypoint"])
async def test_invalid_links_are_rejected_by_database(db: AsyncSession, invalid: str):
    owner = await _user(db)
    org = await _org(db, owner=owner)
    project = await _project(db, org, owner, name="Test", visibility=Visibility.PRIVATE.value)
    agent = Agent(id=uuid4(), organization_id=org.id, name="Agent", slug="agent", draft_spec={})
    table = VirtualTable(id=uuid4(), organization_id=org.id, name="Table")
    db.add_all([agent, table])
    await db.flush()
    async with db.begin_nested():
        row = ProjectResource(project_id=project.id)
        if invalid != "empty":
            row.agent_id = agent.id
        if invalid == "multiple":
            row.table_id = table.id
        if invalid == "agent-entrypoint":
            row.is_entrypoint = True
        db.add(row)
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_project_filter_flows_through_both_registry_services(db: AsyncSession):
    from app.services.agent_registry import AgentRegistryService
    from app.services.workflow_registry import WorkflowRegistryService

    owner = await _user(db)
    org = await _org(db, owner=owner)
    project = await _project(db, org, owner, name="Empty", visibility="org")
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role=OrgRoleName.OWNER)
    agents, total = await AgentRegistryService(db).list_agents(ctx, project_id=project.id)
    assert agents == [] and total == 0
    assert (await WorkflowRegistryService(db).list(ctx, project_id=project.id)).items == []
