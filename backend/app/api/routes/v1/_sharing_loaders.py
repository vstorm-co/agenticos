"""Per-resource row loaders for the sharing routers.

Loading a row is the only thing that differs between sharing an agent, a
collection, a skill and a vault secret, so each loader is injected into
`build_sharing_router`. They live here - beside the factory, not in an endpoint
module and not in `SharingService`, which stays agnostic about what it is
sharing.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.agent import Agent
from app.db.models.context import ContextFile
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.skill import Skill


async def load_agent(db: AsyncSession, agent_id: UUID, organization_id: UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.organization_id != organization_id:
        raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
    return agent


async def load_collection(db: AsyncSession, kb_id: UUID, organization_id: UUID) -> KnowledgeBase:
    collection = await db.get(KnowledgeBase, kb_id)
    if collection is None or collection.organization_id != organization_id:
        raise NotFoundError(message="Collection not found", details={"kb_id": str(kb_id)})
    return collection


async def load_skill(db: AsyncSession, skill_id: UUID, organization_id: UUID) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.organization_id != organization_id:
        raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
    return skill


async def load_context(db: AsyncSession, context_id: UUID, organization_id: UUID) -> ContextFile:
    file = await db.get(ContextFile, context_id)
    if file is None or file.organization_id != organization_id:
        raise NotFoundError(
            message="Context file not found", details={"context_id": str(context_id)}
        )
    return file


async def load_secret(
    db: AsyncSession, secret_id: UUID, organization_id: UUID
) -> OrganizationSecret:
    secret = await db.get(OrganizationSecret, secret_id)
    if secret is None or secret.organization_id != organization_id:
        raise NotFoundError(message="Secret not found", details={"secret_id": str(secret_id)})
    return secret
