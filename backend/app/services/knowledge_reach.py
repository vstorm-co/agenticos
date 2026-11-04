"""Which groups an agent's knowledge comes from, and where it reaches further (#2072).

A company's departments keep their own skills, context, knowledge bases and MCP
servers by sharing them with their group. An agent bound to Finance's knowledge base and
shared with the whole organization answers everyone from Finance's documents -
the binding is allowed, and the agent reads them with its publisher's access,
so nothing refuses it. This makes that visible in the Builder instead.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec, OrgMcpServerRef
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import Visibility
from app.repositories import (
    context_repo,
    group_repo,
    knowledge_base_repo,
    mcp_connection_repo,
    resource_grant_repo,
    skill_repo,
)
from app.schemas.agent import AgentKnowledgeReach, KnowledgeSource, KnowledgeSourceKind
from app.services.access import (
    AGENT,
    COLLECTION,
    CONTEXT,
    MCP_CONNECTION,
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
    user_ids: frozenset[UUID]

    def wider_than(self, other: _Reach) -> bool:
        """Whether this reaches somebody `other` does not."""
        if other.everyone:
            return False
        if self.everyone:
            return True
        # Compared by identity: an agent shared with Alice and a source shared with
        # Bob reach different people. A person the other side reaches only through
        # a group still counts as missing - resolving membership is not done here,
        # and erring towards the warning is the honest side.
        return bool(self.group_ids - other.group_ids) or bool(self.user_ids - other.user_ids)


class KnowledgeReachService:
    """Compare who an agent reaches with who each of its knowledge sources reaches."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _reaches(
        self, ctx: AuthContext, resources: list[OwnedResource], kind: ResourceType
    ) -> dict[UUID, _Reach]:
        grants = await resource_grant_repo.list_for_resources(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=kind.key,
            resource_ids=[row.id for row in resources if row.visibility != Visibility.ORG.value],
        )
        groups: dict[UUID, set[UUID]] = {}
        users: dict[UUID, set[UUID]] = {}
        for grant in grants:
            if grant.subject_group_id:
                groups.setdefault(grant.resource_id, set()).add(grant.subject_group_id)
            if grant.subject_user_id:
                users.setdefault(grant.resource_id, set()).add(grant.subject_user_id)
        return {
            row.id: _Reach(
                everyone=row.visibility == Visibility.ORG.value,
                group_ids=frozenset(groups.get(row.id, ())),
                user_ids=frozenset(users.get(row.id, ())),
            )
            for row in resources
        }

    async def for_agent(self, ctx: AuthContext, agent_id: UUID) -> AgentKnowledgeReach:
        """The agent's own reach, and each source it binds that the caller may see."""
        agent = await AgentRegistryService(self.db).get(ctx, agent_id)
        spec = AgentSpec.model_validate(agent.draft_spec)
        agent_reach = (await self._reaches(ctx, [agent], AGENT))[agent.id]

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
            selected = [row for key, row in rows.items() if key in visible]
            reaches = await self._reaches(ctx, list(selected), resource_type)
            sources.extend((kind, row, reaches[row.id]) for row in selected)

        servers = await mcp_connection_repo.get_org_scoped_by_ids(
            self.db,
            connection_ids=[
                ref.connection_id for ref in spec.mcp_servers if isinstance(ref, OrgMcpServerRef)
            ],
            organization_id=org,
        )
        # A server left to the organization is everyone's to see; one narrowed to
        # groups is shown to those it reaches, as the Builder's own list does.
        narrowed = [row for row in servers.values() if row.visibility != Visibility.ORG.value]
        reached = await accessible_ids(
            self.db, ctx, narrowed, Perm.MCP_MANAGE, resource_type=MCP_CONNECTION
        )
        selected_servers = [
            row
            for row in servers.values()
            if row.visibility == Visibility.ORG.value or row.id in reached
        ]
        reaches = await self._reaches(ctx, list(selected_servers), MCP_CONNECTION)
        sources.extend(("mcp", row, reaches[row.id]) for row in selected_servers)

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
