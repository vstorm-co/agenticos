"""Share things with a department from the department's own page (#2072).

Sharing used to happen from each resource's own Share panel: open the agent,
add Finance; open the skill, add Finance. A department head setting up their
group wants the other direction - the group's page, a list of what they could
share with it, and a few ticks. This is that list and that one action. Each share
is the same grant the Share panel writes, held to the same rule: only something
the caller may edit can be shared.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.group import Group
from app.db.models.resource_grant import GrantLevel
from app.repositories import (
    agent_repo,
    artifact_repo,
    context_repo,
    group_repo,
    knowledge_base_repo,
    mcp_connection_repo,
    resource_grant_repo,
    skill_repo,
)
from app.schemas.group import GroupResource, GroupShareItem
from app.services.access import (
    AGENT,
    ARTIFACT,
    COLLECTION,
    CONTEXT,
    MCP_CONNECTION,
    SKILL,
    OwnedResource,
    ResourceType,
    accessible_ids,
    visible_resource_ids,
)
from app.services.sharing import SharingService

_KINDS: dict[str, ResourceType] = {
    kind.key: kind for kind in (AGENT, COLLECTION, SKILL, CONTEXT, ARTIFACT, MCP_CONNECTION)
}

_OFFERED = 200
"""How many of each kind the list offers; a department shares a handful at a time."""


def _name(row: OwnedResource) -> str:
    """An app by its title, an MCP server by its label, the rest by name."""
    for field in ("title", "label", "name"):
        value = getattr(row, field, None)
        if isinstance(value, str) and value:
            return value
    return str(row.id)


class GroupSharingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def shareable(self, ctx: AuthContext, group_id: UUID) -> list[GroupResource]:
        """What the caller could share with this group that it does not have yet.

        Everything they may edit, of every kind - editing is what sharing takes -
        minus what was already shared with the group.
        """
        group = await self._group(ctx, group_id)
        granted = {
            (grant.resource_type, grant.resource_id)
            for grant in await resource_grant_repo.list_for_group(
                self.db, organization_id=ctx.organization_id, group_id=group.id
            )
        }
        offered: list[GroupResource] = []
        for key, rows in (await self._candidates(ctx)).items():
            kind = _KINDS[key]
            editable = await accessible_ids(self.db, ctx, rows, kind.edit, resource_type=kind)
            offered.extend(
                GroupResource.model_validate(
                    {"kind": key, "id": row.id, "name": _name(row), "level": "use"}
                )
                for row in rows
                if row.id in editable and (key, row.id) not in granted
            )
        return sorted(offered, key=lambda item: (item.kind, item.name.lower()))

    async def share(
        self,
        ctx: AuthContext,
        group_id: UUID,
        items: Sequence[GroupShareItem],
        *,
        level: GrantLevel,
    ) -> None:
        """Share each item with the group, as the Share panel would.

        Raises:
            NotFoundError: An item is not one of this organization's.
            AuthorizationError: The caller may not edit an item, which sharing takes.
        """
        group = await self._group(ctx, group_id)
        sharing = SharingService(self.db)
        for item in items:
            rows = await self._load(ctx, item.kind, [item.id])
            row = rows.get(item.id)
            if row is None:
                raise NotFoundError(
                    message="Resource not found", details={"kind": item.kind, "id": item.id}
                )
            await sharing.share_with_group(
                ctx, row, resource_type=_KINDS[item.kind], group_id=group.id, level=level
            )

    async def _group(self, ctx: AuthContext, group_id: UUID) -> Group:
        group = await group_repo.get(
            self.db, organization_id=ctx.organization_id, group_id=group_id
        )
        if group is None:
            raise NotFoundError(message="Group not found", details={"group_id": group_id})
        return group

    async def _candidates(self, ctx: AuthContext) -> dict[str, Sequence[OwnedResource]]:
        """The caller's visible rows of every kind, before narrowing to what they may edit."""
        org, user_id = ctx.organization_id, ctx.user_id
        if user_id is None:
            return {}

        async def reach(kind: ResourceType) -> tuple[bool, list[UUID]]:
            shared = await visible_resource_ids(self.db, ctx, resource_type=kind, perm=kind.view)
            return shared is None, shared or []

        see_all, shared = await reach(AGENT)
        agents, _ = await agent_repo.list_visible(
            self.db,
            organization_id=org,
            user_id=user_id,
            see_all=see_all,
            shared_ids=shared,
            limit=_OFFERED,
        )
        see_all, shared = await reach(SKILL)
        skills, _ = await skill_repo.list_visible(
            self.db,
            organization_id=org,
            user_id=user_id,
            see_all=see_all,
            shared_ids=shared,
            limit=_OFFERED,
        )
        see_all, shared = await reach(CONTEXT)
        files, _ = await context_repo.list_visible(
            self.db,
            organization_id=org,
            user_id=user_id,
            see_all=see_all,
            shared_ids=shared,
            limit=_OFFERED,
        )
        see_all, shared = await reach(ARTIFACT)
        apps, _ = await artifact_repo.list_visible(
            self.db,
            organization_id=org,
            user_id=user_id,
            see_all=see_all,
            shared_ids=shared,
            limit=_OFFERED,
        )
        servers, _ = await mcp_connection_repo.list_org_scoped(self.db, organization_id=org)
        return {
            AGENT.key: agents,
            SKILL.key: skills,
            CONTEXT.key: files,
            ARTIFACT.key: apps,
            COLLECTION.key: await knowledge_base_repo.list_org_scoped(self.db, org),
            MCP_CONNECTION.key: servers,
        }

    async def _load(
        self, ctx: AuthContext, kind: str, ids: list[UUID]
    ) -> dict[UUID, OwnedResource]:
        """Rows of one kind, by id, inside the caller's organization."""
        org = ctx.organization_id
        if kind == AGENT.key:
            return dict(await agent_repo.get_many(self.db, ids, organization_id=org))
        if kind == SKILL.key:
            return dict(await skill_repo.get_many(self.db, ids, organization_id=org))
        if kind == CONTEXT.key:
            return dict(await context_repo.get_many(self.db, ids, organization_id=org))
        if kind == ARTIFACT.key:
            return dict(await artifact_repo.get_many(self.db, ids, organization_id=org))
        if kind == MCP_CONNECTION.key:
            return dict(
                await mcp_connection_repo.get_org_scoped_by_ids(
                    self.db, connection_ids=ids, organization_id=org
                )
            )
        found = await knowledge_base_repo.get_by_ids(self.db, ids)
        return {key: row for key, row in found.items() if row.organization_id == org}
