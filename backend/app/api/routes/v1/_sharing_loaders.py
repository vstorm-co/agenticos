"""Per-resource row loaders for the sharing routers.

Loading a row is the only thing that differs between sharing an agent, a
collection, a skill, a vault secret and an artifact, so each loader is injected into
`build_sharing_router`. They live here - beside the factory, not in an endpoint
module and not in `SharingService`, which stays agnostic about what it is
sharing.

Each takes the caller's context rather than only its organization, so a loader
can refuse what the resource's own read path refuses: an archived artifact is
found only by a caller who may edit it.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact
from app.db.models.context import ContextFile
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.skill import Skill
from app.db.models.virtual_table import VirtualTable
from app.db.models.workflow import Workflow
from app.services.access import ARTIFACT, resolve_access


async def load_agent(db: AsyncSession, agent_id: UUID, ctx: AuthContext) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.organization_id != ctx.organization_id:
        raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
    return agent


async def load_collection(db: AsyncSession, kb_id: UUID, ctx: AuthContext) -> KnowledgeBase:
    collection = await db.get(KnowledgeBase, kb_id)
    if collection is None or collection.organization_id != ctx.organization_id:
        raise NotFoundError(message="Collection not found", details={"kb_id": str(kb_id)})
    return collection


async def load_skill(db: AsyncSession, skill_id: UUID, ctx: AuthContext) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.organization_id != ctx.organization_id:
        raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
    return skill


async def load_context(db: AsyncSession, context_id: UUID, ctx: AuthContext) -> ContextFile:
    file = await db.get(ContextFile, context_id)
    if file is None or file.organization_id != ctx.organization_id:
        raise NotFoundError(
            message="Context file not found", details={"context_id": str(context_id)}
        )
    return file


async def load_table(db: AsyncSession, table_id: UUID, ctx: AuthContext) -> VirtualTable:
    table = await db.get(VirtualTable, table_id)
    if table is None or table.organization_id != ctx.organization_id:
        raise NotFoundError(message="Table not found", details={"table_id": str(table_id)})
    return table


async def load_secret(db: AsyncSession, secret_id: UUID, ctx: AuthContext) -> OrganizationSecret:
    secret = await db.get(OrganizationSecret, secret_id)
    if secret is None or secret.organization_id != ctx.organization_id:
        raise NotFoundError(message="Secret not found", details={"secret_id": str(secret_id)})
    return secret


async def load_workflow(db: AsyncSession, workflow_id: UUID, ctx: AuthContext) -> Workflow:
    workflow = await db.get(Workflow, workflow_id)
    if workflow is None or workflow.organization_id != ctx.organization_id:
        raise NotFoundError(message="Workflow not found", details={"workflow_id": str(workflow_id)})
    return workflow


async def load_artifact(db: AsyncSession, artifact_id: UUID, ctx: AuthContext) -> Artifact:
    artifact = await db.get(Artifact, artifact_id)
    # An archived page is read only by a caller who may edit it - the one who can
    # restore it, as `ArtifactService.read` answers - so its grants are managed by
    # them alone, and to anybody else it is as missing here as everywhere else.
    if (
        artifact is None
        or artifact.organization_id != ctx.organization_id
        or (
            artifact.archived_at is not None
            and not await resolve_access(
                db, ctx, artifact, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
            )
        )
    ):
        raise NotFoundError(message="Artifact not found", details={"artifact_id": str(artifact_id)})
    return artifact
