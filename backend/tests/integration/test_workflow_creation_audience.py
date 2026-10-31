"""The creation dialog's audience is applied atomically to its resources."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import ResourceGrant
from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreate
from app.services.workflow_registry import WorkflowRegistryService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("template_id", [None, "markdownNotes"])
async def test_creation_shares_only_with_the_chosen_member(db: AsyncSession, template_id):
    owner, member = await make_user(db), await make_user(db)
    org = await make_org(db, owner=owner)
    db.add(OrganizationMember(id=uuid4(), organization_id=org.id, user_id=member.id, role="member"))
    await db.flush()
    result = await WorkflowRegistryService(db).create(
        ctx_for(owner, org),
        WorkflowCreate(
            name="Customer onboarding",
            description="Collect customer details",
            tags=["Onboarding"],
            template_id=template_id,
            user_ids=[member.id],
            visibility="org",
        ),
    )
    assert result.visibility == "private"
    assert result.tags == ["onboarding"]
    grants = (
        await db.scalars(
            select(ResourceGrant).where(
                ResourceGrant.organization_id == org.id,
            )
        )
    ).all()
    assert {grant.subject_user_id for grant in grants} == {member.id}
    assert {grant.resource_type for grant in grants} == (
        {"workflow", "table"} if template_id else {"workflow"}
    )
    if template_id:
        table = await db.scalar(select(VirtualTable).where(VirtualTable.organization_id == org.id))
        assert table is not None and table.visibility == "private"
        assert table.owner_user_id == owner.id


async def test_template_table_follows_an_explicit_organization_audience(db: AsyncSession):
    owner = await make_user(db)
    org = await make_org(db, owner=owner)
    result = await WorkflowRegistryService(db).create(
        ctx_for(owner, org),
        WorkflowCreate(
            name="Team example",
            template_id="markdownNotes",
            visibility="org",
        ),
    )
    table = await db.scalar(select(VirtualTable).where(VirtualTable.organization_id == org.id))
    assert result.visibility == "org"
    assert table is not None and table.visibility == "org"


async def test_cross_tenant_audience_rolls_back_the_new_workflow(db: AsyncSession):
    owner, outsider = await make_user(db), await make_user(db)
    org = await make_org(db, owner=owner)
    await make_org(db, owner=outsider)
    with pytest.raises(BadRequestError):
        async with db.begin_nested():
            await WorkflowRegistryService(db).create(
                ctx_for(owner, org),
                WorkflowCreate(
                    name="Never stored",
                    user_ids=[outsider.id],
                ),
            )
    assert await db.scalar(select(Workflow.id).where(Workflow.organization_id == org.id)) is None
