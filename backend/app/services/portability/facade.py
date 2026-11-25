"""Selectable exports and atomic, reviewed imports through domain services."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import Visibility
from app.db.models.skill_version import SkillVersionSource
from app.repositories import solution_installation as receipts
from app.schemas.mcp_connection import OrgMcpConnectionCreate, OrgMcpConnectionUpdate
from app.schemas.resource_bundle import (
    BundleContentLayer,
    BundleDestination,
    BundleDestinationList,
    BundleDestinationQuery,
    BundleDownloadCreate,
    BundleImportCreate,
    BundleImportRead,
    BundlePreview,
    BundleReference,
    BundleResource,
    BundleResourceKind,
    BundleResourceOption,
    ResourceBundle,
)
from app.schemas.skill_version import SkillForkCreate
from app.services.agent_registry import AgentRegistryService
from app.services.context import ContextService
from app.services.file_storage import BaseFileStorage
from app.services.knowledge_base import KnowledgeBaseService
from app.services.mcp_connection import McpConnectionService
from app.services.model_profile import ModelProfileService
from app.services.portability.archive import BundleLimits
from app.services.portability.content import (
    ContextContent,
    ImportedSkillResourceUpdate,
    ImportedSkillUpdate,
    KnowledgeBaseContent,
    McpContent,
    ModelContent,
    SkillContent,
    SkillSnapshotContent,
)
from app.services.portability.contracts import (
    CREATE_PERMISSIONS,
    DEFINITION_MODELS,
    agent_omissions,
    definition_model,
    owner_key,
    references_for,
    require_agent_root,
    verify_references,
)
from app.services.portability.destinations import BundleDestinations
from app.services.portability.documents import (
    MAX_DOCUMENT_BYTES,
    document_bytes,
    parse_document,
    select_content,
)
from app.services.portability.file_bundle import externalize_text
from app.services.portability.knowledge import KnowledgeTransfer
from app.services.portability.mapping import rebind_definition
from app.services.portability.snapshots import agent_snapshot
from app.services.portability.sources import BundleSources, agent_spec_from_source
from app.services.rag.parsed_snapshot import MAX_SNAPSHOT_CHUNKS
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService

_READABLE = frozenset(
    {
        BundleResourceKind.AGENT,
        BundleResourceKind.AGENT_VERSION,
        BundleResourceKind.CONTEXT,
        BundleResourceKind.SKILL,
        BundleResourceKind.SKILL_VERSION,
        BundleResourceKind.SKILL_FORK,
        BundleResourceKind.MODEL_PROFILE,
        BundleResourceKind.MCP_CONNECTION,
        BundleResourceKind.SECRET,
        BundleResourceKind.KNOWLEDGE_BASE,
        BundleResourceKind.SANDBOX_CONNECTION,
        BundleResourceKind.LOCAL_SERVICE,
    }
)

MAX_EXPORT_RESOURCES = 500
MAX_EXPORT_ASSET_BYTES = BundleLimits().expanded_bytes


class PortabilityService:
    def __init__(self, db: AsyncSession, *, storage: BaseFileStorage | None = None) -> None:
        self.db = db
        self.storage = storage
        self.sources = BundleSources(db)

    async def destinations(
        self, ctx: AuthContext, query: BundleDestinationQuery
    ) -> BundleDestinationList:
        return await BundleDestinations(self.db).list(ctx, query)

    async def preview_document(self, ctx: AuthContext, text: str) -> BundlePreview:
        bundle = parse_document(text)
        require_agent_root(bundle)
        return await self.preview_import(ctx, bundle)

    async def download_agent(
        self, ctx: AuthContext, agent_id: UUID, selection: BundleDownloadCreate
    ) -> bytes:
        bundle, _ = await self.selected_agent(ctx, agent_id, selection)
        return document_bytes(bundle, selection.file_format)

    async def selected_agent(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        selection: BundleDownloadCreate,
        *,
        asset_directory: Path | None = None,
    ) -> tuple[ResourceBundle, dict[str, Path]]:
        """Load selected bodies one resource at a time; ZIP content is staged immediately."""
        preview = await self.export_agent(ctx, agent_id, metadata_only=True)
        available = {option.key: option.layers for option in preview.options}
        if not set(selection.resources).issubset(available):
            raise BadRequestError(message="The selection names a resource outside this export")
        if any(not layers.issubset(available[key]) for key, layers in selection.resources.items()):
            raise BadRequestError(message="The selected content is not available in this export")
        resources = []
        assets = []
        files: dict[str, Path] = {}
        inline_bytes = 0
        parsed_chunks = 0
        for item in preview.bundle.resources:
            if selection.resources.get(item.key):
                _, loaded = await self._source(ctx, item)
                if loaded.definition is None:
                    raise ConflictError(
                        message="An export resource changed; review the selection again"
                    )
                references = tuple(ref for ref, _ in references_for(definition_model(loaded)))
                if any(reference.target not in available for reference in references):
                    raise ConflictError(
                        message="Export dependencies changed; review the selection again"
                    )
                item = loaded.model_copy(update={"references": references})
                if asset_directory is not None:
                    from app.core.blocking import run_blocking_settled

                    single = ResourceBundle.model_construct(
                        roots=(item.key,), resources=(item,), assets=()
                    )
                    staged, paths = await run_blocking_settled(
                        externalize_text, single, asset_directory
                    )
                    item = staged.resources[0]
                    assets.extend(staged.assets)
                    files.update(paths)
                    if item.kind == BundleResourceKind.KNOWLEDGE_BASE:
                        item, kb_assets, kb_files, count = await KnowledgeTransfer(
                            self.db, storage=self.storage
                        ).export(
                            ctx,
                            item,
                            selection.resources[item.key],
                            asset_directory,
                            asset_budget=MAX_EXPORT_ASSET_BYTES
                            - sum({asset.sha256: asset.size_bytes for asset in assets}.values()),
                        )
                        parsed_chunks += count
                        if parsed_chunks > MAX_SNAPSHOT_CHUNKS:
                            raise BadRequestError(
                                message="Export at most 10,000 parsed chunks per transfer"
                            )
                        assets.extend(kb_assets)
                        files.update(kb_files)
                    if (
                        sum({asset.sha256: asset.size_bytes for asset in assets}.values())
                        > MAX_EXPORT_ASSET_BYTES
                    ):
                        raise BadRequestError(
                            message="This export exceeds the 2 GiB expanded bundle limit"
                        )
                inline_bytes += len(json.dumps(item.definition, ensure_ascii=False).encode("utf-8"))
                if inline_bytes > MAX_DOCUMENT_BYTES:
                    raise BadRequestError(
                        message="This configuration exceeds 4 MiB; use a ZIP bundle"
                    )
                if (
                    asset_directory is None
                    and item.kind == BundleResourceKind.KNOWLEDGE_BASE
                    and selection.resources[item.key] - {BundleContentLayer.DEFINITION}
                ):
                    raise BadRequestError(
                        message="Knowledge files and parsed text require a ZIP bundle"
                    )
            resources.append(item)
        bundle = preview.bundle.model_copy(
            update={"resources": tuple(resources), "assets": tuple(assets)}
        )
        verify_references(bundle)
        # Text layers are represented by assets in ZIPs, and belong to the selected
        # resource definition. YAML/JSON preserve the existing inline contract.
        choices = selection.model_copy(
            update={
                "resources": {
                    item.key: (
                        selection.resources.get(item.key, frozenset())
                        if item.kind == BundleResourceKind.KNOWLEDGE_BASE
                        else item.included
                        if selection.resources.get(item.key)
                        else frozenset()
                    )
                    for item in bundle.resources
                }
            }
        )
        return select_content(bundle, choices), files

    async def export_agent(
        self, ctx: AuthContext, agent_id: UUID, *, metadata_only: bool = False
    ) -> BundlePreview:
        agent = await AgentRegistryService(self.db).get(ctx, agent_id)
        bundle = agent_snapshot(agent_spec_from_source(agent.draft_spec), source_id=agent.id)
        resources = {item.key: item for item in bundle.resources}
        options: dict[str, BundleResourceOption] = {}
        pending = list(resources)
        for key in pending:
            if len(resources) > MAX_EXPORT_RESOURCES:
                raise BadRequestError(message="Export at most 500 linked resources at once")
            resource = resources[key]
            include = not metadata_only or resource.kind not in (
                BundleResourceKind.CONTEXT,
                BundleResourceKind.SKILL,
                BundleResourceKind.SKILL_VERSION,
                BundleResourceKind.SKILL_FORK,
            )
            option, loaded = await self._source(ctx, resource, include=include)
            options[key] = option
            resources[key] = loaded
            if loaded.definition is not None:
                model = definition_model(loaded)
                references: list[BundleReference] = []
                for reference, pin in references_for(model):
                    references.append(reference)
                    if pin.bundle_key not in resources:
                        resources[pin.bundle_key] = BundleResource(
                            key=pin.bundle_key,
                            kind=pin.kind,
                            name=pin.kind.value,
                            source_id=pin.source_id,
                            source_parent_id=pin.parent_id,
                            source_version=None
                            if pin.source_number is None
                            else str(pin.source_number),
                        )
                        pending.append(pin.bundle_key)
                resources[key] = loaded.model_copy(update={"references": tuple(references)})
            if metadata_only:
                resources[key] = loaded.model_copy(
                    update={"definition": None, "references": (), "included": frozenset()}
                )
        result = ResourceBundle(roots=bundle.roots, resources=tuple(resources.values()))
        verify_references(result)
        return BundlePreview(bundle=result, options=tuple(options.values()))

    async def preview_import(self, ctx: AuthContext, bundle: ResourceBundle) -> BundlePreview:
        verify_references(bundle)
        options = []
        for item in bundle.resources:
            option, _ = await self._source(ctx, item, include=False)
            options.append(
                option.model_copy(
                    update={
                        "can_create": item.definition is not None
                        and item.kind in CREATE_PERMISSIONS
                        and ctx.has(Perm(CREATE_PERMISSIONS[item.kind]))
                    }
                )
            )
        return BundlePreview(bundle=bundle, options=tuple(options))

    async def _source(
        self, ctx: AuthContext, item: BundleResource, *, include: bool = True
    ) -> tuple[BundleResourceOption, BundleResource]:
        option = BundleResourceOption(key=item.key, available=False)
        if item.kind not in _READABLE or (
            item.source_id is None and item.kind != BundleResourceKind.SKILL_VERSION
        ):
            return option, item
        try:
            source = await self.sources.read(ctx, item, with_content=include)
        except NotFoundError, AuthorizationError:
            return option, item
        definition = source.definition if include else item.definition
        loaded = item.model_copy(
            update={
                "name": source.name,
                "definition": definition,
                "included": frozenset({BundleContentLayer.DEFINITION})
                if definition is not None
                else frozenset(),
            }
        )
        return BundleResourceOption(
            key=item.key,
            available=True,
            layers=frozenset(
                {
                    BundleContentLayer.DEFINITION,
                    BundleContentLayer.KB_DOCUMENTS,
                    BundleContentLayer.KB_PARSED_TEXT,
                }
            )
            if item.kind == BundleResourceKind.KNOWLEDGE_BASE
            else frozenset({BundleContentLayer.DEFINITION})
            if source.copyable and item.kind in DEFINITION_MODELS
            else frozenset(),
            reusable_id=source.id,
            reusable_name=source.name,
            can_create=definition is not None
            and item.kind in CREATE_PERMISSIONS
            and ctx.has(Perm(CREATE_PERMISSIONS[item.kind])),
        ), loaded

    async def import_agent(
        self,
        ctx: AuthContext,
        request: BundleImportCreate,
        *,
        hydrate: Callable[[BundleResource], Awaitable[BundleResource]] | None = None,
        attach: Callable[[BundleResource, UUID], Awaitable[None]] | None = None,
    ) -> BundleImportRead:
        require_agent_root(request.bundle)
        return await self.import_bundle(ctx, request, hydrate=hydrate, attach=attach)

    async def import_bundle(
        self,
        ctx: AuthContext,
        request: BundleImportCreate,
        *,
        hydrate: Callable[[BundleResource], Awaitable[BundleResource]] | None = None,
        attach: Callable[[BundleResource, UUID], Awaitable[None]] | None = None,
    ) -> BundleImportRead:
        """Create private resources in one transaction; retry replays the receipt.

        Reused rows are never edited. A source ID is resolved again under current
        destination authority. Nothing is published, run, scheduled or indexed.
        """
        if ctx.subject_id is None or not ctx.has(Perm.AGENTS_EDIT):
            raise AuthorizationError(message="Importing an agent requires agents:edit")
        if request.bundle.assets and hydrate is None:
            raise BadRequestError(
                message="This endpoint accepts inline configurations; binary assets require a complete bundle upload"
            )
        verify_references(request.bundle)
        resources = {item.key: item for item in request.bundle.resources}
        if request.choices.keys() != resources.keys():
            raise BadRequestError(message="Choose create, reuse or skip for every resource")
        if any(request.choices[key].action == "skip" for key in request.bundle.roots):
            raise BadRequestError(message="An import cannot skip its root resource")
        reviewed = request.model_dump(mode="json")
        fingerprint = hashlib.sha256(
            json.dumps(reviewed, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        key = f"bundle-{request.operation_id.hex}"
        await receipts.lock(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id, key=key
        )
        existing = await receipts.get(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id, key=key
        )
        if existing is not None:
            if existing.manifest_hash != fingerprint:
                raise ConflictError(
                    message="This import operation already names a different reviewed document"
                )
            return self._receipt(request.bundle, existing.resources)
        resolved: dict[str, BundleDestination | None] = {}
        result: dict[str, dict[str, str]] = {}
        for resource_key, choice in request.choices.items():
            if choice.action == "skip":
                resolved[resource_key] = None
                result[resource_key] = {"action": "skip"}
        pending = {key for key, choice in request.choices.items() if choice.action != "skip"}
        while pending:
            ready: list[str] = []
            for candidate in sorted(pending):
                resource = resources[candidate]
                needed = (
                    {ref.target for ref in resource.references}
                    if request.choices[candidate].action == "create"
                    else set()
                )
                if resource.source_parent_id is not None:
                    needed.add(owner_key(request.bundle, resource))
                if needed.issubset(resolved):
                    ready.append(candidate)
            if not ready:
                raise BadRequestError(
                    message="These dependencies form a creation cycle; reuse an existing resource or skip a binding"
                )
            for resource_key in ready:
                resource = resources[resource_key]
                choice = request.choices[resource_key]
                if choice.action == "reuse":
                    assert choice.destination_id is not None
                    destination = await self._reuse(
                        ctx, request.bundle, resource, choice.destination_id, resolved
                    )
                else:
                    permission = CREATE_PERMISSIONS.get(resource.kind)
                    if permission is None or not ctx.has(Perm(permission)):
                        raise AuthorizationError(
                            message="You may not create this resource type",
                            details={"kind": resource.kind.value},
                        )
                    content = await hydrate(resource) if hydrate is not None else resource
                    rebound = rebind_definition(content, resolved, omit=agent_omissions(resource))
                    definition = rebound.definition
                    if choice.name is not None:
                        definition = {
                            **definition,
                            "label"
                            if resource.kind == BundleResourceKind.MODEL_PROFILE
                            else "name": choice.name,
                        }
                    definition_model(resource.model_copy(update={"definition": definition}))
                    if resource.kind in (
                        BundleResourceKind.SKILL_VERSION,
                        BundleResourceKind.SKILL_FORK,
                    ):
                        owner = owner_key(request.bundle, resource)
                        if result[owner]["action"] != "create":
                            raise BadRequestError(
                                message="Import skill snapshots into a new skill; existing skills are never changed"
                            )
                        destination = await self._create_skill_snapshot(
                            ctx, resource.kind, definition
                        )
                    else:
                        destination = BundleDestination(
                            id=await self._create(ctx, resource.kind, definition)
                        )
                    if resource.kind == BundleResourceKind.KNOWLEDGE_BASE:
                        if (
                            attach is None
                            and KnowledgeBaseContent.model_validate(definition).documents
                        ):
                            raise BadRequestError(
                                message="Knowledge files require a complete bundle upload"
                            )
                        if attach is not None:
                            await attach(
                                content.model_copy(update={"definition": definition}),
                                destination.id,
                            )
                resolved[resource_key] = destination
                result[resource_key] = {"action": choice.action, "id": str(destination.id)}
                pending.remove(resource_key)
        await receipts.create(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            key=key,
            manifest_hash=fingerprint,
            resources=result,
        )
        return self._receipt(request.bundle, result)

    async def _reuse(
        self,
        ctx: AuthContext,
        bundle: ResourceBundle,
        resource: BundleResource,
        identity: UUID,
        resolved: dict[str, BundleDestination | None],
    ) -> BundleDestination:
        parent: BundleDestination | None = None
        if resource.source_parent_id is not None:
            parent = resolved[owner_key(bundle, resource)]
            if parent is None:
                raise BadRequestError(
                    message="A reused version needs an accessible destination owner"
                )
        if resource.kind == BundleResourceKind.SKILL_VERSION:
            assert parent is not None
            version = await SkillVersionService(self.db).export_version_by_id(
                ctx, parent.id, identity
            )
            if version.fork_id is not None:
                raise BadRequestError(message="A main skill pin must select a main version")
            return BundleDestination(
                id=version.id, parent_id=parent.id, version_number=version.number
            )
        source = await self.sources.read(
            ctx,
            resource.model_copy(
                update={
                    "source_id": identity,
                    "source_parent_id": parent.id if parent is not None else None,
                }
            ),
            with_content=False,
        )
        return BundleDestination(
            id=source.id, parent_id=source.parent_id, version_number=source.version_number
        )

    async def _write_skill_content(
        self, ctx: AuthContext, skill_id: UUID, content: SkillContent
    ) -> BundleDestination:
        service = SkillService(self.db)
        await service.update(
            ctx,
            skill_id,
            ImportedSkillUpdate(description=content.description, content=content.content),
            source=None,
        )
        await service.drop_resources(ctx, skill_id, keep=[file.name for file in content.files])
        written = await service.put_resources(
            ctx, skill_id, [(file.name, file.content.encode()) for file in content.files]
        )
        descriptions = {file.name: file.description for file in content.files}
        for file in written:
            if descriptions[file.name] is not None:
                await service.update_resource(
                    ctx,
                    skill_id,
                    file.id,
                    ImportedSkillResourceUpdate(description=descriptions[file.name]),
                )
        version = await service.versions.export_snapshot(ctx, skill_id)
        return BundleDestination(id=version.id, parent_id=skill_id, version_number=version.number)

    async def _create_skill_snapshot(
        self, ctx: AuthContext, kind: BundleResourceKind, definition: dict[str, JsonValue]
    ) -> BundleDestination:
        content = SkillSnapshotContent.model_validate(definition)
        current = await self.sources.read(
            ctx,
            BundleResource(
                key=f"skill/{content.skill_id}",
                kind=BundleResourceKind.SKILL,
                source_id=content.skill_id,
                name="skill",
            ),
        )
        assert isinstance(current.content, SkillContent)
        snapshot = SkillContent.model_validate(content.model_dump(exclude={"skill_id", "number"}))
        version = await self._write_skill_content(ctx, content.skill_id, snapshot)
        destination = version
        if kind == BundleResourceKind.SKILL_FORK:
            fork = await SkillVersionService(self.db).create_fork(
                ctx,
                content.skill_id,
                SkillForkCreate(name=content.name, from_version_id=version.id),
            )
            destination = BundleDestination(id=fork.id, parent_id=content.skill_id)
        # Floating bindings keep the original main body. All writes target a
        # new, private skill before any imported agent can refer to it.
        await self._write_skill_content(ctx, content.skill_id, current.content)
        return destination

    @staticmethod
    def _receipt(bundle: ResourceBundle, rows: dict[str, dict[str, str]]) -> BundleImportRead:
        created = {
            key: UUID(value["id"]) for key, value in rows.items() if value["action"] == "create"
        }
        reused = {
            key: UUID(value["id"]) for key, value in rows.items() if value["action"] == "reuse"
        }
        return BundleImportRead(
            roots={key: created[key] if key in created else reused[key] for key in bundle.roots},
            created=created,
            reused=reused,
            skipped=tuple(key for key, value in rows.items() if value["action"] == "skip"),
        )

    async def _create(
        self, ctx: AuthContext, kind: BundleResourceKind, definition: dict[str, JsonValue]
    ) -> UUID:
        try:
            if kind == BundleResourceKind.AGENT:
                row = await AgentRegistryService(self.db).create(
                    ctx, AgentSpec.model_validate(definition), choose_model=False
                )
                return row.id
            if kind == BundleResourceKind.KNOWLEDGE_BASE:
                content = KnowledgeBaseContent.model_validate(definition)
                row = await KnowledgeBaseService(self.db).create_portable_snapshot(
                    ctx=ctx,
                    name=content.name,
                    description=content.description,
                    ingestion_config=content.ingestion_config,
                    embedding_model=content.embedding_model,
                    embedding_provider=content.embedding_provider,
                    embedding_dim=content.embedding_dim,
                    embedding_secret_id=content.embedding_secret_id,
                    embedding_endpoint_id=content.embedding_endpoint_id,
                )
                return row.id
            if kind == BundleResourceKind.CONTEXT:
                content = ContextContent.model_validate(definition)
                row = await ContextService(self.db).create(
                    ctx,
                    name=content.name,
                    description=content.description,
                    content=content.content,
                    content_format=content.format,
                    mode=content.mode,
                )
                return row.id
            if kind == BundleResourceKind.SKILL:
                content = SkillContent.model_validate(definition)
                service = SkillService(self.db)
                row = await service.create(
                    ctx,
                    name=content.name,
                    description=content.description,
                    content=content.content,
                    category=content.category,
                    source=None,
                )
                if content.files:
                    await self._write_skill_content(ctx, row.id, content)
                else:
                    await service.versions.record_main(ctx, row, source=SkillVersionSource.CREATED)
                return row.id
            if kind == BundleResourceKind.MODEL_PROFILE:
                content = ModelContent.model_validate(definition)
                row = await ModelProfileService(self.db).create_profile(
                    ctx,
                    label=content.label,
                    provider=content.provider,
                    model=content.model,
                    secret_id=content.secret_id,
                    base_url=content.base_url,
                    api=content.api,
                    region=content.region,
                    params=content.params,
                    fallback_profile_ids=content.fallback_profile_ids,
                )
                return row.id
            if kind == BundleResourceKind.MCP_CONNECTION:
                content = McpContent.model_validate(definition)
                service = McpConnectionService(self.db)
                row = await service.create_for_org(
                    ctx,
                    OrgMcpConnectionCreate(
                        visibility=Visibility.PRIVATE,
                        name=content.name,
                        label=content.label,
                        url=content.url,
                        allowed_tools=content.allowed_tools,
                        catalog_key=content.catalog_key,
                        is_enabled=False,
                    ),
                )
                await service.update_for_org(
                    ctx,
                    connection_id=row.id,
                    data=OrgMcpConnectionUpdate(
                        include_instructions=content.include_instructions,
                        trust_read_only_hints=content.trust_read_only_hints,
                    ),
                )
                return row.id
        except ValidationError as exc:
            raise BadRequestError(
                message="A mapped resource needs its configuration completed before import"
            ) from exc
        raise BadRequestError(
            message="Creating this resource type is not supported by this importer",
            details={"kind": kind.value},
        )
