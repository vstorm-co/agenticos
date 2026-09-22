"""Workflow registry service - draft CRUD, publish, and the node catalog.

Mirrors `AgentRegistryService`'s shape for a resource with a draft and
published versions, and reuses `#1782`'s `expected_revision` pattern for the
draft write exactly - same field name, same conflict shape, same ordering:
authorization and the archived-lifecycle check run first, then the revision
compare-and-set runs before the graph is even looked at.
"""

import logging
import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, AppException, AuthorizationError, NotFoundError
from app.core.field_errors import field_problems
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow, WorkflowStatus
from app.repositories import workflow as workflow_repo
from app.schemas.workflow import (
    NodeCatalog,
    NodeCatalogEntry,
    NodeCatalogPort,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowDraftUpdate,
    WorkflowList,
    WorkflowPublish,
    WorkflowRead,
    WorkflowVersionList,
    WorkflowVersionRead,
)
from app.services.access import WORKFLOW, resolve_access, visible_resource_ids
from app.workflows._registry import all_node_definitions
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import WorkflowGraph
from app.workflows.graph.validate import derive_scopes, validate_graph

_SLUG_ALLOWED = re.compile(r"[^a-z0-9]+")
_SLUG_TRIM = re.compile(r"-{2,}")

logger = logging.getLogger(__name__)


def slugify(name: str) -> str:
    """A URL-safe handle derived from a name, generated once at creation.

    The same shape `app.services.agent_registry.slugify` builds, duplicated
    rather than imported: an agent's handle also has to dodge the room-wide
    `@channel`/`@everyone` mentions a workflow is never addressed by, so the
    two functions would diverge the moment either grew a rule the other does
    not need.
    """
    slug = _SLUG_ALLOWED.sub("-", name.strip().lower())
    slug = _SLUG_TRIM.sub("-", slug).strip("-")
    return slug[:64] or "workflow"


class WorkflowArchivedError(AppException):
    """A write was attempted on an archived workflow (409)."""

    message = "This workflow is archived and cannot be edited"
    code = "WORKFLOW_ARCHIVED"
    status_code = 409

    def __init__(self, *, workflow_id: UUID) -> None:
        super().__init__(details={"workflow_id": workflow_id})


class WorkflowRevisionConflictError(AppException):
    """The draft changed since the caller read it (409). Nothing was written.

    #1782's `RevisionConflictError`, retargeted from a record to a workflow:
    same shape, same field names besides the one that names what changed.
    """

    message = "This workflow was changed by someone else. Read it again and retry."
    code = "REVISION_CONFLICT"
    status_code = 409

    def __init__(self, *, workflow_id: UUID, expected_revision: int, current_revision: int) -> None:
        super().__init__(
            details={
                "workflow_id": workflow_id,
                "expected_revision": expected_revision,
                "current_revision": current_revision,
            }
        )


def _read(workflow: Workflow) -> WorkflowRead:
    return WorkflowRead(
        id=workflow.id,
        slug=workflow.slug,
        name=workflow.name,
        description=workflow.description,
        status=workflow.status,
        visibility=workflow.visibility,
        owner_user_id=workflow.owner_user_id,
        current_version_id=workflow.current_version_id,
        draft_revision=workflow.draft_revision,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _parse_draft_graph(workflow: Workflow) -> WorkflowGraph | None:
    """`workflow.draft_graph` as a `WorkflowGraph`, or `None` for a draft
    nobody has edited yet.

    `Workflow.draft_graph` starts at `{}` (no `entry_node_id`, no `nodes`),
    which is not a valid `WorkflowGraph` - reported as "no graph yet" rather
    than surfaced as a parse failure. A non-empty stored value that still
    fails to parse is a different problem - stored data corrupted or left
    behind by a schema this version no longer accepts - and is not silently
    folded into the same "never edited" answer without a trace of it existing:
    logged, since there is no second field yet to tell a caller one from the
    other.
    """
    raw = workflow.draft_graph
    try:
        return WorkflowGraph.model_validate(raw)
    except PydanticValidationError:
        if raw != {}:
            logger.warning(
                "workflow_draft_graph_unparsable", extra={"workflow_id": str(workflow.id)}
            )
        return None


def _parse_submitted_graph(raw: dict[str, Any]) -> WorkflowGraph:
    """The graph a caller is trying to write, validated only after
    authorization, the archived check and the revision compare-and-set have
    all passed - never before, so a stale or forbidden request is refused on
    its own terms rather than on the shape of a graph it will never get to
    write. `WorkflowDraftUpdate.graph` is deliberately a raw dict, not a
    `WorkflowGraph` field, so FastAPI's own request parsing cannot validate
    it ahead of those checks and turn an authorized, current write's
    malformed graph into a 422 in place of the 403/404/409 they promise.

    `derive_scopes` runs here too, not only at publish: `scopes` is
    server-derived by contract (see its own docstring), and a draft written
    without this step would store whatever a client claimed about scope
    membership until the next publish silently replaced it - readable by a
    `GET` in between, and by the editor, as if it were real.
    """
    try:
        graph = WorkflowGraph.model_validate(raw)
    except PydanticValidationError as exc:
        raise GraphValidationError(
            [
                (problem["field"], problem["message"])
                for problem in field_problems(
                    exc.errors(include_url=False, include_input=False), root="graph"
                )
            ]
        ) from exc
    return derive_scopes(graph)


def _detail(workflow: Workflow) -> WorkflowDetail:
    return WorkflowDetail(
        **_read(workflow).model_dump(),
        draft_graph=_parse_draft_graph(workflow),
    )


class WorkflowRegistryService:
    """Workflows: create, list, describe, edit the draft, publish."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def node_catalog(self) -> NodeCatalog:
        """Every registered node, for the editor's palette.

        Deployment-wide and gated by `Perm.WORKFLOWS_VIEW` alone - like
        `CapabilityCatalog`, there is no resource here for a grant to widen.
        """
        items = [
            NodeCatalogEntry(
                id=definition.id,
                version=definition.version,
                name=definition.name,
                category=definition.category,
                description=definition.description,
                kind=definition.kind,
                config_schema=definition.config_schema.model_json_schema()
                if definition.config_schema
                else None,
                input_schema=definition.input_schema.model_json_schema()
                if definition.input_schema
                else None,
                output_schema=definition.output_schema.model_json_schema()
                if definition.output_schema
                else None,
                ports=[
                    NodeCatalogPort(
                        id=port.id,
                        label=port.label,
                        kind=port.kind,
                        schema=port.schema.model_json_schema() if port.schema else None,
                    )
                    for port in definition.ports
                ],
                effect_kind=definition.effect_kind,
                retry_guarantee=definition.retry_guarantee,
                scopes=sorted(definition.scopes),
            )
            for definition in all_node_definitions()
        ]
        return NodeCatalog(items=items, total=len(items))

    async def create(self, ctx: AuthContext, data: WorkflowCreate) -> WorkflowRead:
        """Create a workflow in draft, with an empty graph.

        Raises:
            AuthorizationError: The caller lacks `workflows:create`.
            AlreadyExistsError: The derived slug is taken.
        """
        if not ctx.has(Perm.WORKFLOWS_CREATE):
            raise AuthorizationError(
                message="You cannot create workflows",
                details={"required": [Perm.WORKFLOWS_CREATE.value]},
            )
        slug = slugify(data.name)
        if await workflow_repo.get_by_slug(self.db, slug, organization_id=ctx.organization_id):
            raise AlreadyExistsError(
                message=(
                    f"The handle '{slug}' is already taken. It is derived from the name, "
                    "so give this workflow a name that produces a different handle."
                ),
                details={"slug": slug},
            )
        workflow = await workflow_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            slug=slug,
            name=data.name,
            description=data.description,
            owner_user_id=ctx.subject_id,
            created_by_user_id=ctx.subject_id,
            visibility=data.visibility.value,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="workflow.created",
            target_type="workflow",
            target_id=str(workflow.id),
            details={"name": workflow.name},
        )
        return _read(workflow)

    async def list(self, ctx: AuthContext, *, skip: int = 0, limit: int = 50) -> WorkflowList:
        """The workflows this caller may see: their own, org-visible ones and those shared."""
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=WORKFLOW, perm=Perm.WORKFLOWS_VIEW
        )
        items, total = await workflow_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=shared or [],
            skip=skip,
            limit=limit,
        )
        return WorkflowList(items=[_read(item) for item in items], total=total)

    async def get(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowDetail:
        """One workflow, with the draft graph currently being edited."""
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        return _detail(workflow)

    async def list_versions(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowVersionList:
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        versions = await workflow_repo.list_versions(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        return WorkflowVersionList(
            items=[
                WorkflowVersionRead(
                    id=version.id,
                    version=version.version,
                    note=version.note,
                    published_by_user_id=version.published_by_user_id,
                    budget_limit=float(version.budget_limit)
                    if version.budget_limit is not None
                    else None,
                    created_at=version.created_at,
                )
                for version in versions
            ]
        )

    async def update_draft(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowDraftUpdate
    ) -> WorkflowDetail:
        """Replace the draft graph, if it is still at `expected_revision`.

        Raises:
            WorkflowArchivedError: The workflow refuses edits.
            WorkflowRevisionConflictError: Someone changed the draft since it was read.
            GraphValidationError: `graph` does not parse as a `WorkflowGraph`.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        self._check_revision(workflow, data.expected_revision)
        graph = _parse_submitted_graph(data.graph)
        updated = await workflow_repo.update(
            self.db,
            workflow=workflow,
            update_data={
                "draft_graph": graph.model_dump(mode="json"),
                "draft_revision": workflow.draft_revision + 1,
            },
        )
        return _detail(updated)

    async def publish(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowPublish
    ) -> WorkflowVersionRead:
        """Validate the draft graph and freeze it as the next version.

        `expected_revision`-gated so a publish racing a draft edit cannot
        promote a stale draft. `validate_graph` runs only after the revision
        is confirmed current, and its own `GraphValidationError` (422) is
        what actually refuses an invalid graph.

        Raises:
            WorkflowArchivedError: The workflow refuses edits.
            WorkflowRevisionConflictError: Someone changed the draft since it was read.
            GraphValidationError: The graph fails a publish-time rule.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        self._check_revision(workflow, data.expected_revision)

        draft_graph = _parse_draft_graph(workflow)
        if draft_graph is None:
            raise GraphValidationError(
                [("draft_graph", "This workflow has no graph yet - add at least one node")]
            )
        graph = await validate_graph(self.db, ctx, draft_graph)
        version_number = await workflow_repo.next_version_number(self.db, workflow_id=workflow.id)
        version = await workflow_repo.create_version(
            self.db,
            workflow_id=workflow.id,
            organization_id=ctx.organization_id,
            version=version_number,
            graph=graph.model_dump(mode="json"),
            note=data.note,
            published_by_user_id=ctx.subject_id,
            budget_limit=None,
        )
        await workflow_repo.update(
            self.db,
            workflow=workflow,
            update_data={
                "current_version_id": version.id,
                "status": WorkflowStatus.PUBLISHED.value,
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="workflow.published",
            target_type="workflow",
            target_id=str(workflow.id),
            details={"version": version_number},
        )
        return WorkflowVersionRead(
            id=version.id,
            version=version.version,
            note=version.note,
            published_by_user_id=version.published_by_user_id,
            budget_limit=float(version.budget_limit) if version.budget_limit is not None else None,
            created_at=version.created_at,
        )

    async def _load(
        self, ctx: AuthContext, workflow_id: UUID, perm: Perm, *, lock: bool = False
    ) -> Workflow:
        """The workflow, if this caller may exercise `perm` on it.

        Another organization's workflow and one the caller may not reach are
        both a 404: whether a private workflow exists is itself something the
        caller may not learn.
        """
        workflow = (
            await workflow_repo.get_for_update(
                self.db, workflow_id, organization_id=ctx.organization_id
            )
            if lock
            else await workflow_repo.get(self.db, workflow_id, organization_id=ctx.organization_id)
        )
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, perm, resource_type=WORKFLOW
        ):
            raise NotFoundError(message="Workflow not found", details={"workflow_id": workflow_id})
        return workflow

    @staticmethod
    def _ensure_editable(workflow: Workflow) -> None:
        if workflow.status == WorkflowStatus.ARCHIVED.value:
            raise WorkflowArchivedError(workflow_id=workflow.id)

    @staticmethod
    def _check_revision(workflow: Workflow, expected_revision: int) -> None:
        if workflow.draft_revision != expected_revision:
            raise WorkflowRevisionConflictError(
                workflow_id=workflow.id,
                expected_revision=expected_revision,
                current_revision=workflow.draft_revision,
            )
