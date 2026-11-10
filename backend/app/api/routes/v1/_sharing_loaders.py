"""Per-resource row loaders for the sharing routers.

Loading a row is the only thing that differs between sharing an agent, a
collection, a skill, a vault secret, an artifact, a dataset and an MCP server, so each loader is injected into
`build_sharing_router`. They live here - beside the factory, not in an endpoint
module and not in `SharingService`, which stays agnostic about what it is
sharing.

Each takes the caller's context rather than only its organization, so a loader
can refuse what the resource's own read path refuses: an archived artifact is
found only by a caller who may edit it.

A row the caller may neither view nor edit is reported exactly as a missing id - same
message, same `details` - so the sharing routes cannot be used to tell a
private resource apart from one that does not exist (#2619). A caller who can
view but not edit gets past the loader and is refused with a 403 by the
service.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact
from app.db.models.context import ContextFile
from app.db.models.dataset import Dataset
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.project import Project
from app.db.models.skill import Skill
from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow
from app.services.access import (
    AGENT,
    ARTIFACT,
    COLLECTION,
    CONTEXT,
    DATASET,
    MCP_CONNECTION,
    PROJECT,
    SECRET,
    SKILL,
    TABLE,
    WORKFLOW,
    OwnedResource,
    ResourceType,
    resolve_access,
)
from app.services.artifact import ArtifactService


async def _visible[R: OwnedResource](
    db: AsyncSession,
    ctx: AuthContext,
    row: R | None,
    resource_type: ResourceType,
    missing: NotFoundError,
) -> R:
    """`row`, when it is the caller's organization's and they may view or edit it; `missing`
    otherwise.

    Edit admits on its own because an API key can be issued for `edit` without `view`,
    and such a key may still change the resource everywhere else - refusing it its
    sharing would make sharing the one edit it cannot make. Every role's view reaches
    at least as far as its edit, so for a session this is the view check.
    """
    if row is None or row.organization_id != ctx.organization_id:
        raise missing
    for perm in dict.fromkeys((resource_type.view, resource_type.edit)):
        if await resolve_access(db, ctx, row, perm, resource_type=resource_type):
            return row
    raise missing


async def load_agent(db: AsyncSession, agent_id: UUID, ctx: AuthContext) -> Agent:
    missing = NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
    return await _visible(db, ctx, await db.get(Agent, agent_id), AGENT, missing)


async def load_collection(db: AsyncSession, kb_id: UUID, ctx: AuthContext) -> KnowledgeBase:
    missing = NotFoundError(message="Collection not found", details={"kb_id": str(kb_id)})
    return await _visible(db, ctx, await db.get(KnowledgeBase, kb_id), COLLECTION, missing)


async def load_skill(db: AsyncSession, skill_id: UUID, ctx: AuthContext) -> Skill:
    missing = NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
    return await _visible(db, ctx, await db.get(Skill, skill_id), SKILL, missing)


async def load_context(db: AsyncSession, context_id: UUID, ctx: AuthContext) -> ContextFile:
    missing = NotFoundError(
        message="Context file not found", details={"context_id": str(context_id)}
    )
    return await _visible(db, ctx, await db.get(ContextFile, context_id), CONTEXT, missing)


async def load_table(db: AsyncSession, table_id: UUID, ctx: AuthContext) -> VirtualTable:
    missing = NotFoundError(message="Table not found", details={"table_id": str(table_id)})
    return await _visible(db, ctx, await db.get(VirtualTable, table_id), TABLE, missing)


async def load_project(db: AsyncSession, project_id: UUID, ctx: AuthContext) -> Project:
    missing = NotFoundError(message="Project not found", details={"project_id": str(project_id)})
    return await _visible(db, ctx, await db.get(Project, project_id), PROJECT, missing)


async def load_secret(db: AsyncSession, secret_id: UUID, ctx: AuthContext) -> OrganizationSecret:
    missing = NotFoundError(message="Secret not found", details={"secret_id": str(secret_id)})
    return await _visible(db, ctx, await db.get(OrganizationSecret, secret_id), SECRET, missing)


async def load_workflow(db: AsyncSession, workflow_id: UUID, ctx: AuthContext) -> Workflow:
    missing = NotFoundError(message="Workflow not found", details={"workflow_id": str(workflow_id)})
    return await _visible(db, ctx, await db.get(Workflow, workflow_id), WORKFLOW, missing)


async def load_artifact(db: AsyncSession, artifact_id: UUID, ctx: AuthContext) -> Artifact:
    """Found by `ArtifactService.load`, which hides an archived page; then the view check."""
    artifact = await ArtifactService(db).load(ctx, artifact_id)
    missing = NotFoundError(message="App not found", details={"artifact_id": str(artifact_id)})
    return await _visible(db, ctx, artifact, ARTIFACT, missing)


async def load_dataset(db: AsyncSession, dataset_id: UUID, ctx: AuthContext) -> Dataset:
    missing = NotFoundError(message="Dataset not found", details={"dataset_id": str(dataset_id)})
    return await _visible(db, ctx, await db.get(Dataset, dataset_id), DATASET, missing)


async def load_mcp_connection(
    db: AsyncSession, connection_id: UUID, ctx: AuthContext
) -> McpConnection:
    """An organization's MCP server; a member's own is nobody else's to share."""
    connection = await db.get(McpConnection, connection_id)
    missing = NotFoundError(
        message="MCP connection not found", details={"connection_id": str(connection_id)}
    )
    if connection is not None and connection.scope != "org":
        raise missing
    return await _visible(db, ctx, connection, MCP_CONNECTION, missing)
