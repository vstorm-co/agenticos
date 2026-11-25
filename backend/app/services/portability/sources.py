"""Read portable definitions through each resource's existing access service."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, Perm
from app.schemas.resource_bundle import BundleResource, BundleResourceKind
from app.services.agent_registry import AgentRegistryService
from app.services.context import ContextService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.mcp_connection import McpConnectionService
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService
from app.services.portability.content import (
    ContextContent,
    McpContent,
    ModelContent,
    SkillContent,
    SkillFileContent,
    SkillSnapshotContent,
    portable_connection_settings,
)
from app.services.sandbox_connection import SandboxConnectionService
from app.services.skill_versions import SkillVersionService

_OBJECT = TypeAdapter(dict[str, JsonValue], config=ConfigDict(allow_inf_nan=False))


def agent_spec_from_source(value: object) -> AgentSpec:
    """Reject non-JSON source values before JSON-mode serialization can lose them."""
    try:
        return AgentSpec.model_validate(_OBJECT.validate_python(value))
    except ValidationError as exc:
        raise BadRequestError(
            message="The source agent configuration cannot be represented in a portable bundle"
        ) from exc


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    id: UUID
    name: str
    content: BaseModel | None = None
    parent_id: UUID | None = None
    version_number: int | None = None
    copyable: bool = True

    @property
    def definition(self) -> dict[str, JsonValue] | None:
        return (
            None
            if self.content is None
            else _OBJECT.validate_python(self.content.model_dump(mode="json"))
        )


class BundleSources:
    """A source ID is a lookup candidate, never authority to read a dependency."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def read(
        self, ctx: AuthContext, resource: BundleResource, *, with_content: bool = True
    ) -> SourceDefinition:
        kind, identity = resource.kind, resource.source_id
        if kind == BundleResourceKind.SKILL_VERSION:
            if resource.source_parent_id is None or resource.source_version is None:
                raise BadRequestError(
                    message="A skill version must identify its owning skill and number"
                )
            try:
                number = int(resource.source_version)
            except ValueError as exc:
                raise BadRequestError(message="A skill version number must be an integer") from exc
            return await self._skill(
                ctx, resource.source_parent_id, number=number, with_content=with_content
            )
        if identity is None:
            raise BadRequestError(message="This dependency does not identify a source resource")
        if kind == BundleResourceKind.AGENT:
            row = await AgentRegistryService(self.db).get(ctx, identity)
            return SourceDefinition(
                row.id, row.name, agent_spec_from_source(row.draft_spec) if with_content else None
            )
        if kind == BundleResourceKind.AGENT_VERSION:
            if resource.source_parent_id is None:
                raise BadRequestError(message="An agent version must identify its owning agent")
            row = await AgentRegistryService(self.db).get_version(
                ctx, resource.source_parent_id, identity
            )
            return SourceDefinition(
                row.id,
                "agent_version",
                agent_spec_from_source(row.spec) if with_content else None,
                parent_id=resource.source_parent_id,
            )
        if kind == BundleResourceKind.CONTEXT:
            row = await ContextService(self.db).get(ctx, identity)
            if not with_content:
                return SourceDefinition(row.id, row.name)
            return SourceDefinition(
                row.id,
                row.name,
                ContextContent.model_validate(
                    {
                        "name": row.name,
                        "description": row.description,
                        "content": row.content,
                        "format": row.format,
                        "mode": row.mode,
                    }
                ),
            )
        if kind == BundleResourceKind.SKILL:
            return await self._skill(ctx, identity, with_content=with_content)
        if kind == BundleResourceKind.SKILL_FORK:
            if resource.source_parent_id is None:
                raise BadRequestError(message="A skill fork must identify its owning skill")
            return await self._skill(
                ctx, resource.source_parent_id, fork_id=identity, with_content=with_content
            )
        if kind == BundleResourceKind.MODEL_PROFILE:
            self._require(ctx, Perm.AGENTS_VIEW)
            row = await ModelProfileService(self.db).profile_for_organization(
                ctx.organization_id, profile_id=identity
            )
            copyable = portable_connection_settings(row.base_url, row.params)
            if not with_content or not copyable:
                return SourceDefinition(row.id, row.label, copyable=copyable)
            try:
                payload = ModelContent.model_validate(
                    {
                        "label": row.label,
                        "provider": row.provider,
                        "model": row.model,
                        "secret_id": row.secret_id,
                        "base_url": row.base_url,
                        "api": row.api,
                        "region": row.region,
                        "params": row.params,
                        "fallback_profile_ids": row.fallback_profile_ids,
                    }
                )
            except ValidationError as exc:
                raise BadRequestError(
                    message="The source model configuration cannot be represented in a portable bundle"
                ) from exc
            return SourceDefinition(row.id, row.label, payload)
        if kind == BundleResourceKind.MCP_CONNECTION:
            self._require(ctx, Perm.MCP_MANAGE)
            row = await McpConnectionService(self.db).get_org_connection(ctx, identity)
            copyable = portable_connection_settings(row.url)
            if not with_content or not copyable:
                return SourceDefinition(row.id, row.label or row.name, copyable=copyable)
            payload = McpContent(
                name=row.name,
                label=row.label,
                url=row.url,
                allowed_tools=row.allowed_tools,
                include_instructions=row.include_instructions,
                trust_read_only_hints=row.trust_read_only_hints,
                catalog_key=row.catalog_key,
            )
            return SourceDefinition(row.id, row.label or row.name, payload)
        if kind == BundleResourceKind.SECRET:
            row = await OrganizationSecretService(self.db).get_metadata(ctx, identity)
            return SourceDefinition(row.id, row.name)
        if kind == BundleResourceKind.KNOWLEDGE_BASE:
            row = await KnowledgeBaseService(self.db).get(identity, ctx=ctx)
            return SourceDefinition(row.id, row.name)
        if kind == BundleResourceKind.SANDBOX_CONNECTION:
            self._require(ctx, Perm.CONNECTIONS_VIEW)
            row = await SandboxConnectionService(self.db).get(ctx, identity)
            return SourceDefinition(row.id, row.name)
        raise BadRequestError(
            message="This dependency needs an explicit destination selected in its owning editor",
            details={"kind": kind.value},
        )

    @staticmethod
    def _require(ctx: AuthContext, permission: Perm) -> None:
        if not ctx.has(permission):
            raise AuthorizationError(
                message="You may not read this resource configuration",
                details={"permission": permission.value},
            )

    async def _skill(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        *,
        number: int | None = None,
        fork_id: UUID | None = None,
        with_content: bool = True,
    ) -> SourceDefinition:
        versions = SkillVersionService(self.db)
        skill = await versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW, include_resources=False)
        version = await versions.export_snapshot(ctx, skill_id, number=number, fork_id=fork_id)
        if not with_content:
            name = (
                skill.name
                if fork_id is None
                else (await versions.get_fork(ctx, skill_id, fork_id)).name
            )
            return SourceDefinition(
                fork_id or (version.id if number is not None else skill.id),
                name,
                parent_id=skill.id if number is not None or fork_id is not None else None,
                version_number=version.number if number is not None else None,
            )
        if (
            len(version.resources) > 1000
            or sum(item["size_bytes"] for item in version.resources.values()) > 16 * 1024 * 1024
        ):
            raise BadRequestError(
                message="This skill needs a file bundle rather than an inline configuration export"
            )
        bodies = await versions.files_of(version)
        files = tuple(
            SkillFileContent(
                name=name, description=version.resources[name]["description"], content=body
            )
            for name, body in bodies.items()
        )
        fields = {
            "name": skill.name,
            "description": version.description,
            "content": version.content,
            "category": skill.category,
            "files": files,
        }
        if number is not None or fork_id is not None:
            if fork_id is not None:
                fields["name"] = (await versions.get_fork(ctx, skill_id, fork_id)).name
            payload = SkillSnapshotContent.model_validate(
                {**fields, "skill_id": skill.id, "number": version.number}
            )
            return SourceDefinition(
                fork_id or version.id,
                payload.name,
                payload,
                parent_id=skill.id,
                version_number=version.number,
            )
        return SourceDefinition(skill.id, skill.name, SkillContent.model_validate(fields))
