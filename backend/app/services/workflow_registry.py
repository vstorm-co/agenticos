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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.field_errors import field_problems
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.updates import writable
from app.repositories import resource_grant_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import (
    NodeCatalog,
    NodeCatalogEntry,
    NodeCatalogPort,
    StoredWorkflowSettings,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowDraftUpdate,
    WorkflowList,
    WorkflowPublish,
    WorkflowPublished,
    WorkflowRead,
    WorkflowSettings,
    WorkflowUpdate,
    WorkflowVersionDetail,
    WorkflowVersionList,
    WorkflowVersionRead,
    WorkflowVersionRestore,
)
from app.services.access import WORKFLOW, resolve_access, visible_resource_ids
from app.services.virtual_tables.dependencies import Dependent, register_dependency_checker
from app.services.workflow_execution.exceptions import WorkflowArchivedError
from app.services.workflow_triggers import WorkflowTriggerSync
from app.workflows._registry import all_node_definitions
from app.workflows.contracts.io import TableIORef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import WorkflowGraph
from app.workflows.graph.validate import derive_scopes, graph_size_problems, validate_graph
from app.workflows.triggers import WORKFLOW_FAILED

_SLUG_ALLOWED = re.compile(r"[^a-z0-9]+")
_SLUG_TRIM = re.compile(r"-{2,}")

# `WorkflowCreate.name`'s ceiling. The numbering suffix eats into it rather than
# growing past it, so the suffix - the part that says which one this is - always
# survives, and the base is what gets truncated.
_NAME_LIMIT = 128

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


def _numbered_name(base: str, n: int) -> str:
    """The nth default name derived from `base`: `base`, then `base 2`, `base 3`.

    Creation offers no name field - the name is a fixed default ("Untitled
    workflow") or a template's title - so a second blank or a reused template
    has nothing to rename with. Numbering the name here is what lets it be
    created at all, the same reason `agent_registry` numbers a clone's name.
    """
    if n == 1:
        return base
    suffix = f" {n}"
    return f"{base[: _NAME_LIMIT - len(suffix)].rstrip()}{suffix}"


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


class WorkflowInUseError(AppException):
    """The workflow cannot be deleted while it is still in use (409). Nothing was removed."""

    message = "This workflow is still in use"
    code = "WORKFLOW_IN_USE"
    status_code = 409


class WorkflowSettingsInvalidError(AppException):
    """A setting names something it cannot (422): `details["field"]` says which."""

    message = "These settings cannot be saved"
    code = "WORKFLOW_SETTINGS_INVALID"
    status_code = 422

    def __init__(self, *, field: str, message: str) -> None:
        super().__init__(message=message, details={"field": field})


def _read(workflow: Workflow, *, trigger_active: bool | None = None) -> WorkflowRead:
    return WorkflowRead(
        id=workflow.id,
        slug=workflow.slug,
        name=workflow.name,
        description=workflow.description,
        status=workflow.status,
        visibility=workflow.visibility,
        owner_user_id=workflow.owner_user_id,
        current_version_id=workflow.current_version_id,
        live_trigger=workflow.live_trigger,
        tags=list(workflow.tags),
        trigger_active=trigger_active,
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

    `graph_size_problems` also runs here, not only at publish: an oversized
    graph is worth refusing before it is ever persisted, not only before the
    quadratic dominator computation that graph's own `graph_size_problems`
    docstring explains.
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
    size_problems = graph_size_problems(graph)
    if size_problems:
        raise GraphValidationError(size_problems)
    return derive_scopes(graph)


def _without_pins(graph: WorkflowGraph) -> WorkflowGraph:
    """The graph as a version freezes it: data pinned for testing stays in the draft."""
    return graph.model_copy(
        update={
            "nodes": tuple(node.model_copy(update={"pinned_output": None}) for node in graph.nodes)
        }
    )


def _detail(
    workflow: Workflow, *, can_edit: bool, trigger_active: bool | None = None
) -> WorkflowDetail:
    return WorkflowDetail(
        **_read(workflow, trigger_active=trigger_active).model_dump(),
        draft_graph=_parse_draft_graph(workflow),
        settings=StoredWorkflowSettings.model_validate(workflow.settings),
        can_edit=can_edit,
    )


def _table_references(graph: dict[str, Any]) -> list[tuple[UUID, tuple[UUID, ...] | None]]:
    """Every table a stored graph names - a node's pinned `table`, or a table
    binding - with the columns it pins, `None` meaning all of them."""
    refs: list[dict[str, Any]] = [
        node.get("config", {}).get("table")
        for node in graph.get("nodes", [])
        if isinstance(node.get("config", {}).get("table"), dict)
    ]
    refs += [
        binding.get("source")
        for binding in graph.get("bindings", [])
        if isinstance(binding.get("source"), dict) and binding["source"].get("kind") == "table"
    ]
    found: list[tuple[UUID, tuple[UUID, ...] | None]] = []
    for ref in refs:
        try:
            parsed = TableIORef.model_validate(ref)
        except PydanticValidationError:
            continue
        found.append((parsed.table_id, parsed.column_ids))
    return found


async def workflow_table_dependents(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    column_ids: frozenset[UUID] | None,
    caller: AuthContext,
) -> list[Dependent]:
    """The published workflows that would break if this table, or these columns, went.

    Only a version that can still run counts - each live workflow's current one;
    a superseded version is history, and letting it block a change would make one
    old reference a permanent lock nobody could clear. Archiving the whole table
    is blocked by any reference to it; archiving columns only by a reference that
    pins one of them. A workflow the caller cannot edit is neither reported nor
    blocking: it is not theirs to fix, and its step fails with a typed error at
    run time instead.
    """
    dependents: list[Dependent] = []
    for workflow, version in await workflow_repo.list_runnable_versions(
        db, organization_id=organization_id
    ):
        hit = any(
            ref_table == table_id
            and (column_ids is None or (pinned is not None and bool(set(pinned) & column_ids)))
            for ref_table, pinned in _table_references(version.graph)
        )
        if hit and await resolve_access(
            db, caller, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        ):
            dependents.append(Dependent(kind="workflow", id=workflow.id, name=workflow.name))
    return dependents


register_dependency_checker(workflow_table_dependents)


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
                loop_body_only=definition.loop_body_only,
            )
            for definition in all_node_definitions()
        ]
        return NodeCatalog(items=items, total=len(items))

    async def create(self, ctx: AuthContext, data: WorkflowCreate) -> WorkflowRead:
        """Create a workflow in draft, with an empty graph.

        The handle is derived from the name, and the name at creation is a fixed
        default or a template title with no field to change it, so a taken handle
        is disambiguated by numbering the name (`Untitled workflow 2`) rather
        than refused - a second blank or a reused template must be creatable.

        Raises:
            AuthorizationError: The caller lacks `workflows:create`.
            AlreadyExistsError: The handle and every numbered variant are taken.
        """
        if not ctx.has(Perm.WORKFLOWS_CREATE):
            raise AuthorizationError(
                message="You cannot create workflows",
                details={"required": [Perm.WORKFLOWS_CREATE.value]},
            )
        name, slug = await self._available_name(ctx, data.name)
        workflow = await workflow_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            slug=slug,
            name=name,
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

    async def _available_name(self, ctx: AuthContext, base_name: str) -> tuple[str, str]:
        """A `(name, slug)` whose handle nobody in the org has taken yet.

        One query reads every handle that could collide - the base and its
        numbered variants - and the first free number wins, so the common case
        of a handful of `Untitled workflow`s costs a single round trip. Distinct
        numbers give distinct handles until the 64-char slug ceiling truncates
        them together; only then, with every candidate genuinely colliding, is
        the handle reported taken - the honest answer at that point.
        """
        base_slug = slugify(base_name)
        taken = await workflow_repo.slugs_with_prefix(
            self.db, base_slug, organization_id=ctx.organization_id
        )
        for n in range(1, len(taken) + 2):
            name = _numbered_name(base_name, n)
            slug = slugify(name)
            if slug not in taken:
                return name, slug
        raise AlreadyExistsError(
            message=(
                f"The handle '{base_slug}' and its numbered variants are all taken. "
                "Give this workflow a name that produces a different handle."
            ),
            details={"slug": base_slug},
        )

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
        states = await WorkflowTriggerSync(self.db).states(
            ctx.organization_id, [item.id for item in items]
        )
        return WorkflowList(
            items=[_read(item, trigger_active=states.get(item.id)) for item in items],
            total=total,
        )

    async def get(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowDetail:
        """One workflow, with the draft graph currently being edited."""
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        can_edit = workflow.status != WorkflowStatus.ARCHIVED.value and await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_EDIT, resource_type=WORKFLOW
        )
        return await self._detail(workflow, can_edit=can_edit)

    async def update(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowUpdate
    ) -> WorkflowDetail:
        """Rename the workflow, change its description or its tags. Its handle stays.

        Raises:
            NotFoundError: The workflow is out of reach, or this caller may not edit it.
            WorkflowArchivedError: The workflow is archived.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        changes = writable(data, over=Workflow)
        if data.tags is not None:
            # In the order given, each once: `Sales` and `sales` are one tag.
            changes["tags"] = list(dict.fromkeys(data.tags))
        if not changes:
            return await self._detail(workflow, can_edit=True)
        updated = await workflow_repo.update(self.db, workflow=workflow, update_data=changes)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="workflow.updated",
            target_type="workflow",
            target_id=str(workflow.id),
            details={"fields": sorted(changes)},
        )
        return await self._detail(updated, can_edit=True)

    async def update_settings(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowSettings
    ) -> WorkflowDetail:
        """Replace what the workflow is run with. Its schedule keeps the new timezone
        from its next tick; the other settings apply to the runs admitted after.

        An error workflow runs as the member who chose it, who must be able to run
        it, and must start from On failure of a workflow in its published version.

        Raises:
            NotFoundError: The workflow is out of reach, or this caller may not edit it.
            WorkflowArchivedError: The workflow is archived.
            WorkflowSettingsInvalidError: The error workflow is this one, one the
                caller cannot run, or one that does not start from a failure.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        before = StoredWorkflowSettings.model_validate(workflow.settings)
        run_as = before.error_workflow_run_as
        if data.error_workflow_id is None:
            run_as = None
        elif data.error_workflow_id != before.error_workflow_id:
            await self._check_error_workflow(ctx, workflow, data.error_workflow_id)
            run_as = ctx.subject_id
        stored = StoredWorkflowSettings(**data.model_dump(), error_workflow_run_as=run_as)
        updated = await workflow_repo.update(
            self.db, workflow=workflow, update_data={"settings": stored.model_dump(mode="json")}
        )
        if stored.timezone != before.timezone:
            await WorkflowTriggerSync(self.db).retime(ctx, updated)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="workflow.settings_updated",
            target_type="workflow",
            target_id=str(workflow.id),
            details={
                "fields": sorted(
                    name
                    for name in WorkflowSettings.model_fields
                    if getattr(stored, name) != getattr(before, name)
                )
            },
        )
        return await self._detail(updated, can_edit=True)

    async def _check_error_workflow(
        self, ctx: AuthContext, workflow: Workflow, error_workflow_id: UUID
    ) -> None:
        field = "error_workflow_id"
        if error_workflow_id == workflow.id:
            raise WorkflowSettingsInvalidError(
                field=field, message="A workflow cannot be its own error workflow"
            )
        target = await workflow_repo.get(
            self.db, error_workflow_id, organization_id=ctx.organization_id
        )
        if target is None or not await resolve_access(
            self.db, ctx, target, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        ):
            raise WorkflowSettingsInvalidError(
                field=field, message="No workflow you can run has that id"
            )
        if target.live_trigger != WORKFLOW_FAILED:
            raise WorkflowSettingsInvalidError(
                field=field,
                message="Publish that workflow starting from On failure of a workflow first",
            )

    async def set_active(self, ctx: AuthContext, workflow_id: UUID, active: bool) -> WorkflowDetail:
        """Switch the published version's unattended trigger on, or pause it.

        Raises:
            NotFoundError: The workflow is out of reach, or this caller may not edit it.
            WorkflowArchivedError: The workflow is archived.
            AuthorizationError: The caller may edit the workflow but not run it - the
                trigger runs as its publisher, who must be able to.
            BadRequestError: The live version has no trigger that runs unattended.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        if not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        ):
            raise AuthorizationError(
                message="This trigger runs as its publisher, so you need to be able to run it",
                details={"workflow_id": str(workflow.id)},
            )
        await WorkflowTriggerSync(self.db).set_active(ctx, workflow, active)
        return await self._detail(workflow, can_edit=True)

    async def archive(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowDetail:
        """Retire a workflow, keeping its versions and runs, and pause its trigger.

        An archived workflow cannot be edited or run, so whatever started it on
        its own - a webhook, a schedule, a new table record - is paused rather
        than left to be refused on every delivery. Restoring it leaves the trigger
        paused, for its owner to switch back on.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        if workflow.status == WorkflowStatus.ARCHIVED.value:
            return await self._detail(workflow, can_edit=False)
        await WorkflowTriggerSync(self.db).pause(ctx, workflow)
        updated = await workflow_repo.update(
            self.db, workflow=workflow, update_data={"status": WorkflowStatus.ARCHIVED.value}
        )
        await self._audit(ctx, workflow, "workflow.archived")
        return await self._detail(updated, can_edit=False)

    async def unarchive(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowDetail:
        """Bring a retired workflow back: published if it has a version, else a draft.

        Raises:
            BadRequestError: The workflow is not archived.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        if workflow.status != WorkflowStatus.ARCHIVED.value:
            raise BadRequestError(
                message=f"Workflow '{workflow.name}' is not archived",
                details={"workflow_id": str(workflow.id), "status": workflow.status},
            )
        restored = (
            WorkflowStatus.PUBLISHED.value
            if workflow.current_version_id is not None
            else WorkflowStatus.DRAFT.value
        )
        updated = await workflow_repo.update(
            self.db, workflow=workflow, update_data={"status": restored}
        )
        await self._audit(ctx, workflow, "workflow.unarchived")
        return await self._detail(updated, can_edit=True)

    async def delete(self, ctx: AuthContext, workflow_id: UUID) -> None:
        """Permanently remove a workflow, its versions, its runs and its shares.

        Refused while one of its runs has not ended - it would be removed from under
        a worker still running it - and when runs of another workflow were started
        by its runs, whose chain would lose its start. Archiving keeps all of that.

        Raises:
            NotFoundError: The workflow is out of reach, or this caller may not edit it.
            WorkflowInUseError: A run has not ended, or another workflow's runs
                descend from this one's.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        unfinished = await workflow_run_repo.count_unfinished_runs(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if unfinished:
            raise WorkflowInUseError(
                message=f"{unfinished} of this workflow's runs have not ended. "
                "Cancel them or let them finish, then delete it.",
                details={"workflow_id": str(workflow.id), "unfinished_runs": unfinished},
            )
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=WORKFLOW.key,
            resource_id=workflow.id,
        )
        try:
            async with self.db.begin_nested():
                await workflow_repo.delete(self.db, workflow)
        except IntegrityError:
            raise WorkflowInUseError(
                message="Runs of another workflow were started by this one's. Archive it instead.",
                details={"workflow_id": str(workflow_id)},
            ) from None
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="workflow.deleted",
            target_type="workflow",
            target_id=str(workflow_id),
            details={"name": workflow.name},
        )

    async def _audit(self, ctx: AuthContext, workflow: Workflow, action: str) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="workflow",
            target_id=str(workflow.id),
        )

    async def _detail(self, workflow: Workflow, *, can_edit: bool) -> WorkflowDetail:
        """The workflow as the editor reads it, with whether its trigger is on."""
        states = await WorkflowTriggerSync(self.db).states(workflow.organization_id, [workflow.id])
        return _detail(workflow, can_edit=can_edit, trigger_active=states.get(workflow.id))

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

    async def get_version(
        self, ctx: AuthContext, workflow_id: UUID, version_id: UUID
    ) -> WorkflowVersionDetail:
        """One published version with its frozen graph, for a read-only preview.

        Gated the same way `get` and `list_versions` are - the caller must be able
        to view the workflow the version belongs to. A version id that names no
        row, or one belonging to another workflow or organization, is a 404: the
        version is reached through its workflow, so it cannot leak past it.

        Raises:
            NotFoundError: The workflow or the version does not exist, or the
                caller may not view it.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_VIEW)
        version = await workflow_repo.get_version(
            self.db, version_id, organization_id=ctx.organization_id
        )
        if version is None or version.workflow_id != workflow.id:
            raise NotFoundError(
                message="Workflow version not found", details={"version_id": version_id}
            )
        return WorkflowVersionDetail(
            id=version.id,
            version=version.version,
            note=version.note,
            published_by_user_id=version.published_by_user_id,
            budget_limit=float(version.budget_limit) if version.budget_limit is not None else None,
            created_at=version.created_at,
            graph=WorkflowGraph.model_validate(version.graph),
        )

    async def update_draft(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowDraftUpdate
    ) -> WorkflowDetail:
        """Replace the draft graph, if it is still at `expected_revision`.

        A graph with no steps is stored as no graph at all, the draft a new
        workflow starts with: it has no entry to name, and a builder who
        deleted every step is part-way through an edit, not submitting a
        malformed one.

        Raises:
            WorkflowArchivedError: The workflow refuses edits.
            WorkflowRevisionConflictError: Someone changed the draft since it was read.
            GraphValidationError: `graph` does not parse as a `WorkflowGraph`.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        self._check_revision(workflow, data.expected_revision)
        empty = data.graph.get("nodes") == []
        graph = None if empty else _parse_submitted_graph(data.graph).model_dump(mode="json")
        updated = await workflow_repo.update(
            self.db,
            workflow=workflow,
            update_data={
                "draft_graph": graph,
                "draft_revision": workflow.draft_revision + 1,
            },
        )
        return await self._detail(updated, can_edit=True)

    async def restore_version(
        self,
        ctx: AuthContext,
        workflow_id: UUID,
        version_id: UUID,
        data: WorkflowVersionRestore,
    ) -> WorkflowDetail:
        """Replace the draft with a published version's frozen graph.

        The same order `update_draft` refuses in: access, then the archived
        check, then the revision compare-and-set, and only then the version
        lookup - so a stale restore is a conflict whichever version it names.
        The version is reached through its workflow: one that belongs to
        another workflow or organization is a 404, as `get_version` answers.

        The stored graph is copied as it was frozen, not re-validated: a node
        version the registry has since dropped still opens in the editor,
        where the next publish reports it, rather than making the restore
        itself fail.

        Raises:
            NotFoundError: The workflow or the version does not exist, or the
                caller may not edit the workflow.
            WorkflowArchivedError: The workflow refuses edits.
            WorkflowRevisionConflictError: Someone changed the draft since it was read.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        self._check_revision(workflow, data.expected_revision)
        version = await workflow_repo.get_version(
            self.db, version_id, organization_id=ctx.organization_id
        )
        if version is None or version.workflow_id != workflow.id:
            raise NotFoundError(
                message="Workflow version not found", details={"version_id": version_id}
            )
        updated = await workflow_repo.update(
            self.db,
            workflow=workflow,
            update_data={
                "draft_graph": version.graph,
                "draft_revision": workflow.draft_revision + 1,
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="workflow.version_restored",
            target_type="workflow",
            target_id=str(workflow.id),
            details={"version": version.version},
        )
        return await self._detail(updated, can_edit=True)

    async def publish(
        self, ctx: AuthContext, workflow_id: UUID, data: WorkflowPublish
    ) -> WorkflowPublished:
        """Validate the draft graph, freeze it as the next version, and switch its
        trigger on (`WorkflowTriggerSync`).

        `expected_revision`-gated so a publish racing a draft edit cannot
        promote a stale draft. `validate_graph` runs only after the revision
        is confirmed current, and its own `GraphValidationError` (422) is
        what actually refuses an invalid graph.

        Raises:
            WorkflowArchivedError: The workflow refuses edits.
            WorkflowRevisionConflictError: Someone changed the draft since it was read.
            GraphValidationError: The graph fails a publish-time rule.
            AuthorizationError: Its trigger runs unattended, as the publisher, who
                may edit the workflow but not run it.
        """
        workflow = await self._load(ctx, workflow_id, Perm.WORKFLOWS_EDIT, lock=True)
        self._ensure_editable(workflow)
        self._check_revision(workflow, data.expected_revision)

        draft_graph = _parse_draft_graph(workflow)
        if draft_graph is None:
            raise GraphValidationError(
                [("draft_graph", "This workflow has no graph yet - add at least one node")]
            )
        graph = _without_pins(await validate_graph(self.db, ctx, draft_graph))
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
        switched = await WorkflowTriggerSync(self.db).switch_on(ctx, workflow, version, graph)
        return WorkflowPublished(
            id=version.id,
            version=version.version,
            note=version.note,
            published_by_user_id=version.published_by_user_id,
            budget_limit=float(version.budget_limit) if version.budget_limit is not None else None,
            created_at=version.created_at,
            trigger=switched.trigger,
            exposure=switched.exposure,
            webhook_secret=switched.webhook_secret,
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
