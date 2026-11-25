"""Destination names come from authorized listings, never from uploaded labels."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, Perm
from app.schemas.resource_bundle import (
    BundleDestinationList,
    BundleDestinationOption,
    BundleDestinationQuery,
    BundleResourceKind,
)
from app.services.agent_registry import AgentRegistryService
from app.services.context import ContextService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.local_service import LocalServiceService
from app.services.mcp_connection import McpConnectionService
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService
from app.services.sandbox_connection import SandboxConnectionService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
from app.services.virtual_tables import VirtualTableService
from app.services.workflow_registry import WorkflowRegistryService


def _page(
    items: list[BundleDestinationOption], query: BundleDestinationQuery
) -> BundleDestinationList:
    selected = [item for item in items if query.search.casefold() in item.name.casefold()]
    selected.sort(key=lambda item: (item.name.casefold(), str(item.id)))
    return BundleDestinationList(
        items=selected[query.skip : query.skip + query.limit], total=len(selected)
    )


class BundleDestinations:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, ctx: AuthContext, query: BundleDestinationQuery) -> BundleDestinationList:
        kind = query.kind
        if (
            kind
            in (
                BundleResourceKind.AGENT,
                BundleResourceKind.AGENT_VERSION,
                BundleResourceKind.SKILL_VERSION,
            )
            and query.search
        ):
            raise BadRequestError(
                message="Browse this resource's paginated history without a name filter"
            )
        if kind == BundleResourceKind.TABLE:
            tables = await VirtualTableService(self.db).list_tables(
                ctx, search=query.search, skip=query.skip, limit=query.limit
            )
            return BundleDestinationList(
                items=[BundleDestinationOption(id=row.id, name=row.name) for row in tables.items],
                total=tables.total,
            )
        if kind == BundleResourceKind.WORKFLOW:
            if query.search:
                raise BadRequestError(message="Browse workflows without a name filter")
            workflows = await WorkflowRegistryService(self.db).list(
                ctx, skip=query.skip, limit=query.limit
            )
            return BundleDestinationList(
                items=[
                    BundleDestinationOption(id=row.id, name=row.name) for row in workflows.items
                ],
                total=workflows.total,
                searchable=False,
            )
        if kind == BundleResourceKind.CONTEXT:
            rows, total = await ContextService(self.db).list_context(
                ctx, search=query.search, skip=query.skip, limit=query.limit
            )
            return BundleDestinationList(
                items=[BundleDestinationOption(id=row.id, name=row.name) for row in rows],
                total=total,
            )
        if kind == BundleResourceKind.SKILL:
            rows, total = await SkillService(self.db).list_skills(
                ctx, search=query.search, skip=query.skip, limit=query.limit
            )
            return BundleDestinationList(
                items=[BundleDestinationOption(id=row.id, name=row.name) for row in rows],
                total=total,
            )
        if kind == BundleResourceKind.AGENT:
            agents, total = await AgentRegistryService(self.db).list_agents(
                ctx, skip=query.skip, limit=query.limit
            )
            return BundleDestinationList(
                items=[BundleDestinationOption(id=row.id, name=row.name) for row in agents],
                total=total,
                searchable=False,
            )
        if kind in (
            BundleResourceKind.AGENT_VERSION,
            BundleResourceKind.SKILL_VERSION,
            BundleResourceKind.SKILL_FORK,
        ):
            if query.parent_id is None:
                raise BadRequestError(
                    message="Choose an existing destination owner before choosing its version or fork"
                )
            if kind == BundleResourceKind.AGENT_VERSION:
                versions, total = await AgentRegistryService(self.db).list_versions(
                    ctx, query.parent_id, skip=query.skip, limit=query.limit
                )
                return BundleDestinationList(
                    items=[
                        BundleDestinationOption(id=row.id, name=f"v{row.version}")
                        for row in versions
                    ],
                    total=total,
                    searchable=False,
                )
            service = SkillVersionService(self.db)
            if kind == BundleResourceKind.SKILL_VERSION:
                versions = await service.list_versions(
                    ctx, query.parent_id, fork_id=None, skip=query.skip, limit=query.limit
                )
                return BundleDestinationList(
                    items=[
                        BundleDestinationOption(id=row.id, name=f"v{row.number}")
                        for row in versions.items
                    ],
                    total=versions.total,
                    searchable=False,
                )
            forks = await service.list_forks(ctx, query.parent_id)
            return _page(
                [BundleDestinationOption(id=row.id, name=row.name) for row in forks.items], query
            )
        if kind == BundleResourceKind.MODEL_PROFILE:
            self._require(ctx, Perm.AGENTS_VIEW)
            models = await ModelProfileService(self.db).list_profiles(ctx)
            return _page(
                [BundleDestinationOption(id=row.id, name=row.label) for row in models], query
            )
        if kind == BundleResourceKind.MCP_CONNECTION:
            self._require(ctx, Perm.MCP_MANAGE)
            connections, _ = await McpConnectionService(self.db).list_for_org(ctx)
            return _page(
                [
                    BundleDestinationOption(id=row.id, name=row.label or row.name)
                    for row in connections
                ],
                query,
            )
        if kind == BundleResourceKind.SECRET:
            secrets = await OrganizationSecretService(self.db).list_secrets(ctx)
            return _page(
                [BundleDestinationOption(id=row.id, name=row.name) for row in secrets], query
            )
        if kind == BundleResourceKind.KNOWLEDGE_BASE:
            bases = await KnowledgeBaseService(self.db).list_accessible(ctx)
            return _page(
                [BundleDestinationOption(id=row.id, name=row.name) for row in bases], query
            )
        if kind == BundleResourceKind.LOCAL_SERVICE:
            rows = await LocalServiceService(self.db).list_visible(ctx)
            return _page([BundleDestinationOption(id=row.id, name=row.name) for row in rows], query)
        if kind == BundleResourceKind.SANDBOX_CONNECTION:
            self._require(ctx, Perm.CONNECTIONS_VIEW)
            connections = await SandboxConnectionService(self.db).list_connections(ctx)
            return _page(
                [BundleDestinationOption(id=row.id, name=row.name) for row in connections], query
            )
        raise BadRequestError(message="This resource must be configured in its owning editor")

    @staticmethod
    def _require(ctx: AuthContext, permission: Perm) -> None:
        if not ctx.has(permission):
            raise AuthorizationError(message="You may not list these destination resources")
