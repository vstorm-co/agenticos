"""Sharing endpoints for every shareable resource.

Agents, collections, skills and vault secrets each get the same four routes,
generated from one definition. The resource loaders live here because loading a row is the only
thing that differs between them - and they are deliberately *not* in the sharing
service, which stays agnostic about what it is sharing.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.v1._sharing_routes import build_sharing_router
from app.core.exceptions import NotFoundError
from app.db.models.agent import Agent
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.skill import Skill
from app.services.access import AGENT, COLLECTION, SECRET, SKILL


# routes-helper: per-resource loader injected into build_sharing_router; kept out
# of the agnostic sharing service by design (see the module docstring).
async def _load_agent(db: AsyncSession, agent_id: UUID, organization_id: UUID) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.organization_id != organization_id:
        raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
    return agent


# routes-helper: per-resource loader injected into build_sharing_router.
async def _load_collection(db: AsyncSession, kb_id: UUID, organization_id: UUID) -> KnowledgeBase:
    collection = await db.get(KnowledgeBase, kb_id)
    if collection is None or collection.organization_id != organization_id:
        raise NotFoundError(message="Collection not found", details={"kb_id": str(kb_id)})
    return collection


# routes-helper: per-resource loader injected into build_sharing_router.
async def _load_skill(db: AsyncSession, skill_id: UUID, organization_id: UUID) -> Skill:
    skill = await db.get(Skill, skill_id)
    if skill is None or skill.organization_id != organization_id:
        raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
    return skill


# routes-helper: per-resource loader injected into build_sharing_router.
async def _load_secret(
    db: AsyncSession, secret_id: UUID, organization_id: UUID
) -> OrganizationSecret:
    secret = await db.get(OrganizationSecret, secret_id)
    if secret is None or secret.organization_id != organization_id:
        raise NotFoundError(message="Secret not found", details={"secret_id": str(secret_id)})
    return secret


agent_sharing_router = build_sharing_router(resource_type=AGENT, load=_load_agent)
collection_sharing_router = build_sharing_router(resource_type=COLLECTION, load=_load_collection)
skill_sharing_router = build_sharing_router(resource_type=SKILL, load=_load_skill)
secret_sharing_router = build_sharing_router(resource_type=SECRET, load=_load_secret)
