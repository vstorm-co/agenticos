"""Install a reviewed collection of private drafts in one request transaction."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.clients.redis import RedisClient
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import Visibility
from app.repositories import solution_installation as receipts
from app.schemas.solution import (
    PreparedSolution,
    PreparedSolutionInstall,
    SolutionInstall,
    SolutionManifest,
    SolutionPlan,
    SolutionReceipt,
    SolutionResource,
)
from app.services.agent_registry import AgentRegistryService
from app.services.context import ContextService
from app.services.dataset import DatasetService
from app.services.knowledge_base import KnowledgeBaseService
from app.services.skills import SkillService
from app.services.workflow_registry import WorkflowRegistryService


def plan_solution(manifest: SolutionManifest) -> SolutionPlan:
    """Validate the shape and fingerprint the exact reviewed bundle; no I/O or spend."""
    payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    permissions: set[Perm] = {Perm.AGENTS_EDIT}
    for entries, required in (
        (manifest.contexts, {Perm.CONTEXT_EDIT}),
        (manifest.skills, {Perm.SKILLS_EDIT}),
        (manifest.knowledge, {Perm.COLLECTIONS_EDIT}),
        (manifest.datasets, {Perm.DATASETS_EDIT}),
        (manifest.agents, {Perm.AGENTS_EDIT}),
        (manifest.workflows, {Perm.WORKFLOWS_CREATE, Perm.WORKFLOWS_EDIT}),
    ):
        if entries:
            permissions.update(required)
    if any(entry.data.table is not None for entry in manifest.workflows):
        permissions.add(Perm.TABLES_CREATE)
    return SolutionPlan(
        name=manifest.name,
        manifest_hash=hashlib.sha256(payload.encode()).hexdigest(),
        required_permissions=sorted(permission.value for permission in permissions),
        resources=[
            entry.key
            for entry in [
                *manifest.contexts,
                *manifest.skills,
                *manifest.knowledge,
                *manifest.datasets,
                *manifest.agents,
                *manifest.workflows,
            ]
        ],
    )


class SolutionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _plan_key(ctx: AuthContext, plan_id: UUID) -> str:
        return f"solution-plan:{ctx.organization_id}:{ctx.subject_id}:{plan_id}"

    async def prepare(
        self, ctx: AuthContext, manifest: SolutionManifest, cache: RedisClient
    ) -> PreparedSolution:
        """Keep a private, bounded review document, not credentials or live resources.

        The cache's TTL owns cleanup. Installation revalidates its hash and every
        live permission. Cache loss/expiry asks for a fresh preparation; reusing
        the original installation key and manifest still replays its durable receipt.
        """
        if not ctx.has(Perm.AGENTS_EDIT):
            raise AuthorizationError(message="Preparing a solution requires agents:edit")
        payload = manifest.model_dump_json()
        if len(payload.encode()) > 1024 * 1024:
            raise BadRequestError(
                message="A prepared solution is limited to 1 MiB; install smaller bundles"
            )
        plan_id = uuid4()
        key = self._plan_key(ctx, plan_id)
        if not await cache.set(key, payload, ttl=86400, nx=True):
            raise ConflictError(message="The review could not be reserved; prepare again")
        return PreparedSolution(
            **plan_solution(manifest).model_dump(),
            plan_id=plan_id,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

    async def install_prepared(
        self, ctx: AuthContext, request: PreparedSolutionInstall, cache: RedisClient
    ) -> SolutionReceipt:
        """Resolve only this principal's review, then use the normal atomic installer."""
        payload = await cache.get(self._plan_key(ctx, request.plan_id))
        if payload is None:
            raise NotFoundError(
                message="Review not found or expired; prepare again and reuse the installation key"
            )
        manifest = SolutionManifest.model_validate_json(payload)
        return await self.install(
            ctx,
            SolutionInstall(
                installation_key=request.installation_key,
                expected_manifest_hash=request.expected_manifest_hash,
                manifest=manifest,
            ),
        )

    async def read_installation(self, ctx: AuthContext, installation_key: str) -> SolutionReceipt:
        """Read this principal's historical identities, never grant access to their resources."""
        if not ctx.has(Perm.AGENTS_EDIT):
            raise AuthorizationError(message="Reading an installation receipt requires agents:edit")
        existing = await receipts.get(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            key=installation_key,
        )
        if existing is None:
            raise NotFoundError(message="Installation receipt not found")
        return SolutionReceipt(
            installation_key=existing.installation_key,
            manifest_hash=existing.manifest_hash,
            resources={
                key: SolutionResource.model_validate(value)
                for key, value in existing.resources.items()
            },
            replayed=True,
        )

    async def install(self, ctx: AuthContext, request: SolutionInstall) -> SolutionReceipt:
        """Create once, replay unchanged retries, refuse changed payloads and narrower callers.

        Services share the request transaction. Nothing is published, executed or
        ingested. A failure rolls back all resources with its receipt. Replaying
        after deleting or editing a resource does not recreate or overwrite it;
        the receipt is installation history, not a claim of current readiness.
        """
        plan = plan_solution(request.manifest)
        if request.expected_manifest_hash != plan.manifest_hash:
            raise ConflictError(
                message="The solution changed since review",
                details={"manifest_hash": plan.manifest_hash},
            )
        missing = [
            permission for permission in plan.required_permissions if not ctx.has(Perm(permission))
        ]
        if missing or ctx.subject_id is None:
            raise AuthorizationError(
                message="You cannot install this solution", details={"required": missing}
            )
        await receipts.lock(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            key=request.installation_key,
        )
        existing = await receipts.get(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            key=request.installation_key,
        )
        if existing is not None:
            if existing.manifest_hash != plan.manifest_hash:
                raise ConflictError(
                    message="Installation key already names another solution",
                    details={"installation_key": request.installation_key},
                )
            return SolutionReceipt(
                installation_key=existing.installation_key,
                manifest_hash=existing.manifest_hash,
                resources={
                    key: SolutionResource.model_validate(value)
                    for key, value in existing.resources.items()
                },
                replayed=True,
            )
        resources: dict[str, SolutionResource] = {}
        manifest = request.manifest
        for entry in manifest.contexts:
            data = entry.data
            row = await ContextService(self.db).create(
                ctx,
                name=data.name,
                description=data.description,
                content=data.content,
                content_format=data.format,
                mode=data.mode,
                visibility=Visibility.PRIVATE,
            )
            resources[entry.key] = SolutionResource(kind="context", id=row.id)
        for entry in manifest.skills:
            data = entry.data
            row = await SkillService(self.db).create(
                ctx,
                name=data.name,
                description=data.description,
                content=data.content,
                category=data.category,
                visibility=Visibility.PRIVATE,
            )
            resources[entry.key] = SolutionResource(kind="skill", id=row.id)
        for entry in manifest.knowledge:
            data = entry.data.model_copy(
                update={
                    "scope": "personal",
                    "visibility": "private",
                    "group_ids": [],
                    "user_ids": [],
                }
            )
            row = await KnowledgeBaseService(self.db).create(data, ctx=ctx)
            resources[entry.key] = SolutionResource(kind="knowledge", id=row.id)
        for entry in manifest.datasets:
            data = entry.data.model_copy(update={"visibility": "private"})
            row = await DatasetService(self.db).create(ctx, data)
            resources[entry.key] = SolutionResource(kind="dataset", id=row.id)
            for case in entry.cases:
                await DatasetService(self.db).add_case(ctx, row.id, case)
        for entry in manifest.agents:
            spec = AgentSpec.model_validate(
                {
                    **entry.spec.model_dump(mode="json"),
                    "context_ids": [
                        *entry.spec.context_ids,
                        *(resources[key].id for key in entry.context_keys),
                    ],
                    "skill_ids": [
                        *entry.spec.skill_ids,
                        *(resources[key].id for key in entry.skill_keys),
                    ],
                    "collection_ids": [
                        *entry.spec.collection_ids,
                        *(resources[key].id for key in entry.knowledge_keys),
                    ],
                }
            )
            row = await AgentRegistryService(self.db).create(
                ctx, spec, visibility=Visibility.PRIVATE, choose_model=False
            )
            resources[entry.key] = SolutionResource(kind="agent", id=row.id)
        for entry in manifest.workflows:
            prepared = await WorkflowRegistryService(self.db).prepare(ctx, entry.data)
            resources[entry.key] = SolutionResource(kind="workflow", id=prepared.workflow.id)
            if prepared.table is not None:
                resources[entry.key + ".table"] = SolutionResource(
                    kind="table", id=prepared.table.id
                )
        await receipts.create(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            key=request.installation_key,
            manifest_hash=plan.manifest_hash,
            resources={
                key: {"kind": value.kind, "id": str(value.id)} for key, value in resources.items()
            },
        )
        return SolutionReceipt(
            installation_key=request.installation_key,
            manifest_hash=plan.manifest_hash,
            resources=resources,
        )
