"""Which groups an agent's knowledge comes from, and where it reaches further (#2072).

A company's departments keep their own skills, context and knowledge bases by
sharing them with their group. An agent bound to Finance's knowledge base and
shared with the whole organization answers everyone from Finance's documents -
the binding is allowed, and the agent reads them with its publisher's access,
so nothing refuses it. This makes that visible in the Builder instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.db.models.resource_grant import Visibility
from app.repositories import (
    context_repo,
    group_repo,
    knowledge_base_repo,
    resource_grant_repo,
    skill_repo,
)
from app.schemas.agent import AgentKnowledgeReach, KnowledgeSource, KnowledgeSourceKind
from app.services.access import (
    AGENT,
    COLLECTION,
    CONTEXT,
    SKILL,
    OwnedResource,
    ResourceType,
    accessible_ids,
)
from app.services.agent_registry import AgentRegistryService


class _NamedResource(OwnedResource, Protocol):
    name: str


@dataclass(frozen=True)
class _Reach:
    """Who a resource reaches beyond its owner: everyone, or these groups and people."""

    everyone: bool
    group_ids: frozenset[UUID]
    has_people: bool

    def wider_than(self, other: _Reach) -> bool:
        """Whether this reaches somebody `other` does not."""
        if other.everyone:
            return False
        if self.everyone:
            return True
        # A person shared on one side is somebody the other side may not reach;
        # without resolving group membership that is the honest answer.
        return bool(self.group_ids - other.group_ids) or (self.has_people and not other.has_people)


class KnowledgeReachService:
    """Compare who an agent reaches with who each of its knowledge sources reaches."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _reach(self, ctx: AuthContext, resource: OwnedResource, kind: ResourceType) -> _Reach:
        if resource.visibility == Visibility.ORG.value:
            return _Reach(everyone=True, group_ids=frozenset(), has_people=False)
        grants = await resource_grant_repo.list_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=kind.key,
            resource_id=resource.id,
        )
        return _Reach(
            everyone=False,
            group_ids=frozenset(g.subject_group_id for g in grants if g.subject_group_id),
            has_people=any(g.subject_user_id is not None for g in grants),
        )

    async def for_agent(self, ctx: AuthContext, agent_id: UUID) -> AgentKnowledgeReach:
        """The agent's own reach, and each source it binds that the caller may see."""
        agent = await AgentRegistryService(self.db).get(ctx, agent_id)
        spec = AgentSpec.model_validate(agent.draft_spec)
        agent_reach = await self._reach(ctx, agent, AGENT)

        org = ctx.organization_id
        bound: list[tuple[KnowledgeSourceKind, ResourceType, dict[UUID, _NamedResource]]] = [
            (
                "collection",
                COLLECTION,
                dict(await knowledge_base_repo.get_by_ids(self.db, spec.collection_ids)),
            ),
            (
                "skill",
                SKILL,
                dict(await skill_repo.get_many(self.db, spec.skill_ids, organization_id=org)),
            ),
            (
                "context",
                CONTEXT,
                dict(await context_repo.get_many(self.db, spec.context_ids, organization_id=org)),
            ),
        ]
        sources: list[tuple[KnowledgeSourceKind, _NamedResource, _Reach]] = []
        for kind, resource_type, rows in bound:
            visible = await accessible_ids(
                self.db, ctx, rows.values(), resource_type.view, resource_type=resource_type
            )
            for key, row in rows.items():
                if key in visible:
                    reach = await self._reach(ctx, row, resource_type)
                    sources.append((kind, row, reach))

        every_group = set(agent_reach.group_ids)
        for *_, reach in sources:
            every_group |= reach.group_ids
        names = await group_repo.get_names(
            self.db, organization_id=org, group_ids=sorted(every_group)
        )
        return AgentKnowledgeReach(
            whole_organization=agent_reach.everyone,
            groups=sorted(names[g] for g in agent_reach.group_ids if g in names),
            sources=[
                KnowledgeSource(
                    kind=kind,
                    id=row.id,
                    name=row.name,
                    whole_organization=reach.everyone,
                    groups=sorted(names[g] for g in reach.group_ids if g in names),
                    reaches_fewer_than_agent=agent_reach.wider_than(reach),
                )
                for kind, row, reach in sources
            ],
        )
