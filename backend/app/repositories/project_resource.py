"""Project resource links; every read joins the owning project's tenant."""

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.db.models.agent import Agent
from app.db.models.artifact import Artifact
from app.db.models.project import Project
from app.db.models.project_resource import ProjectResource, ProjectResourceKind
from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow

Resource = Agent | Workflow | Artifact | VirtualTable
MODELS: dict[
    ProjectResourceKind, type[Agent] | type[Workflow] | type[Artifact] | type[VirtualTable]
] = {
    ProjectResourceKind.AGENT: Agent,
    ProjectResourceKind.WORKFLOW: Workflow,
    ProjectResourceKind.APP: Artifact,
    ProjectResourceKind.TABLE: VirtualTable,
}
COLUMNS: dict[ProjectResourceKind, InstrumentedAttribute[UUID | None]] = {
    ProjectResourceKind.AGENT: ProjectResource.agent_id,
    ProjectResourceKind.WORKFLOW: ProjectResource.workflow_id,
    ProjectResourceKind.APP: ProjectResource.app_id,
    ProjectResourceKind.TABLE: ProjectResource.table_id,
}


async def get_resource(
    db: AsyncSession, *, kind: ProjectResourceKind, resource_id: UUID, organization_id: UUID
) -> Resource | None:
    model = MODELS[kind]
    result = await db.execute(
        select(model).where(model.id == resource_id, model.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def list_resources(
    db: AsyncSession, *, organization_id: UUID, project_id: UUID, kind: ProjectResourceKind
) -> list[tuple[ProjectResource, Resource]]:
    model = MODELS[kind]
    result = await db.execute(
        select(ProjectResource, model)
        .join(Project, Project.id == ProjectResource.project_id)
        .join(model, model.id == COLUMNS[kind])
        .where(
            Project.organization_id == organization_id,
            Project.id == project_id,
            model.organization_id == organization_id,
        )
        .order_by(model.name, model.id)
    )
    return [(link, resource) for link, resource in result.tuples().all()]


async def member_ids(
    db: AsyncSession, *, organization_id: UUID, project_id: UUID, kind: ProjectResourceKind
) -> list[UUID]:
    column = COLUMNS[kind]
    result = await db.execute(
        select(column)
        .join(Project, Project.id == ProjectResource.project_id)
        .where(
            Project.organization_id == organization_id,
            Project.id == project_id,
            column.is_not(None),
        )
    )
    return [value for value in result.scalars().all() if value is not None]


async def add(
    db: AsyncSession, *, project_id: UUID, kind: ProjectResourceKind, resource_id: UUID
) -> None:
    await db.execute(
        insert(ProjectResource)
        .values(project_id=project_id, **{COLUMNS[kind].key: resource_id})
        .on_conflict_do_nothing(index_elements=[ProjectResource.project_id, COLUMNS[kind]])
    )
    await db.flush()


async def remove(
    db: AsyncSession, *, project_id: UUID, kind: ProjectResourceKind, resource_id: UUID
) -> None:
    await db.execute(
        delete(ProjectResource).where(
            ProjectResource.project_id == project_id, COLUMNS[kind] == resource_id
        )
    )
    await db.flush()


async def set_entrypoint(db: AsyncSession, *, project_id: UUID, workflow_id: UUID | None) -> None:
    await db.execute(
        update(ProjectResource)
        .where(ProjectResource.project_id == project_id, ProjectResource.is_entrypoint.is_(True))
        .values(is_entrypoint=False)
    )
    if workflow_id is not None:
        await db.execute(
            update(ProjectResource)
            .where(
                ProjectResource.project_id == project_id, ProjectResource.workflow_id == workflow_id
            )
            .values(is_entrypoint=True)
        )
    await db.flush()
