"""Workflow registry repository (PostgreSQL async).

Mirrors `app.repositories.agent`: `Workflow` rows are read and written plainly,
`WorkflowVersion` rows are only ever created and read - there is no
`update_version`, which is what makes a published graph immutable a structural
fact rather than a convention every caller has to remember.
"""

from uuid import UUID

from sqlalchemy import ColumnElement, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowVersion


async def get(db: AsyncSession, workflow_id: UUID, *, organization_id: UUID) -> Workflow | None:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_for_update(
    db: AsyncSession, workflow_id: UUID, *, organization_id: UUID
) -> Workflow | None:
    """The workflow, row-locked - taken before comparing `draft_revision`."""
    result = await db.execute(
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.organization_id == organization_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_by_slug(db: AsyncSession, slug: str, *, organization_id: UUID) -> Workflow | None:
    result = await db.execute(
        select(Workflow).where(Workflow.slug == slug, Workflow.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


def visible_to(*, user_id: UUID, shared_ids: list[UUID]) -> ColumnElement[bool]:
    """The workflows a caller whose role does not reach them all may see.

    Their own, the organization-visible ones, and those shared with them - the
    one definition `list_visible` and the run listing both filter by, so the
    two cannot disagree about which workflows a caller can see.
    """
    return or_(
        Workflow.owner_user_id == user_id,
        Workflow.visibility == Visibility.ORG.value,
        Workflow.id.in_(shared_ids) if shared_ids else false(),
    )


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    skip: int,
    limit: int,
) -> tuple[list[Workflow], int]:
    """The workflows this caller may see: their own, org-visible ones and those shared.

    `see_all=True` when the role scope already reaches every workflow, in
    which case `shared_ids` is not consulted - the same contract
    `app.services.access.visible_resource_ids` documents for every other
    resource type.
    """
    where = [Workflow.organization_id == organization_id]
    if not see_all:
        where.append(visible_to(user_id=user_id, shared_ids=shared_ids))
    total = await db.scalar(select(func.count()).select_from(Workflow).where(*where)) or 0
    result = await db.execute(
        select(Workflow)
        .where(*where)
        .order_by(Workflow.created_at.desc(), Workflow.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    slug: str,
    name: str,
    description: str | None,
    owner_user_id: UUID | None,
    created_by_user_id: UUID | None,
    visibility: str,
) -> Workflow:
    workflow = Workflow(
        organization_id=organization_id,
        slug=slug,
        name=name,
        description=description,
        owner_user_id=owner_user_id,
        created_by_user_id=created_by_user_id,
        visibility=visibility,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return workflow


async def update(db: AsyncSession, *, workflow: Workflow, update_data: dict) -> Workflow:
    for field, value in update_data.items():
        setattr(workflow, field, value)
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return workflow


async def next_version_number(db: AsyncSession, *, workflow_id: UUID) -> int:
    """The next version number for a workflow, starting at 1."""
    current = await db.scalar(
        select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow_id)
    )
    return (current or 0) + 1


async def create_version(
    db: AsyncSession,
    *,
    workflow_id: UUID,
    organization_id: UUID,
    version: int,
    graph: dict,
    note: str | None,
    published_by_user_id: UUID | None,
    budget_limit: object | None,
) -> WorkflowVersion:
    row = WorkflowVersion(
        workflow_id=workflow_id,
        organization_id=organization_id,
        version=version,
        graph=graph,
        note=note,
        published_by_user_id=published_by_user_id,
        budget_limit=budget_limit,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_version(
    db: AsyncSession, version_id: UUID, *, organization_id: UUID
) -> WorkflowVersion | None:
    result = await db.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.id == version_id,
            WorkflowVersion.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession, *, workflow_id: UUID, organization_id: UUID
) -> list[WorkflowVersion]:
    result = await db.execute(
        select(WorkflowVersion)
        .where(
            WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.organization_id == organization_id,
        )
        .order_by(WorkflowVersion.version.desc())
    )
    return list(result.scalars().all())
