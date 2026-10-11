"""`WorkflowPortableService` - a workflow exported as a file, and imported from one (#1953).

Both go through `WorkflowRegistryService`, so an export needs what reading the
workflow needs and an import what creating one does, and the draft an import
writes is parsed, sized and scoped exactly as an edit's is. What makes a graph
portable - no id of this deployment's, no pinned data - is `graph.portable`.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.field_errors import field_problems
from app.core.permissions import AuthContext
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowDraftUpdate,
    WorkflowSettings,
    WorkflowUpdate,
)
from app.schemas.workflow_portable import UnresolvedResource, WorkflowExport, WorkflowImported
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import WorkflowGraph
from app.workflows.graph.portable import Unresolved, portable


def _listed(unresolved: list[Unresolved]) -> list[UnresolvedResource]:
    return [
        UnresolvedResource(node_id=item.node_id, step=item.step, field=item.field, kind=item.kind)
        for item in unresolved
    ]


class WorkflowPortableService:
    """Export a workflow's draft as a file, and make a draft from one."""

    def __init__(self, db: AsyncSession) -> None:
        self.registry = WorkflowRegistryService(db)

    async def export(self, ctx: AuthContext, workflow_id: UUID) -> WorkflowExport:
        """The workflow's draft, name, tags and settings, with nothing that names
        this deployment.

        Raises:
            NotFoundError: The workflow does not exist, or this caller may not view it.
        """
        workflow = await self.registry.get(ctx, workflow_id)
        graph, unresolved = (
            (None, []) if workflow.draft_graph is None else portable(workflow.draft_graph)
        )
        settings = WorkflowSettings.model_validate(
            workflow.settings.model_dump(exclude={"error_workflow_run_as", "error_workflow_id"})
        )
        return WorkflowExport(
            name=workflow.name,
            description=workflow.description,
            tags=workflow.tags,
            settings=settings,
            graph=None if graph is None else graph.model_dump(mode="json"),
            unresolved=_listed(unresolved),
        )

    async def import_(self, ctx: AuthContext, data: WorkflowExport) -> WorkflowImported:
        """A new draft workflow from an exported file, and every pin to choose again:
        the ones the file lists as left out, and any it still named.

        The file's graph is stripped of any id it names, whatever made the file:
        an id from another deployment resolves to nothing here, or to the wrong
        thing. Nothing is published - the draft waits for its pins.

        Raises:
            AuthorizationError: The caller lacks `workflows:create`.
            GraphValidationError: The graph does not parse, is too large, or has
                a step of a kind or version this deployment does not have.
        """
        stripped: WorkflowGraph | None = None
        unresolved: list[Unresolved] = []
        if data.graph is not None:
            try:
                graph = WorkflowGraph.model_validate(data.graph)
            except PydanticValidationError as exc:
                raise GraphValidationError(
                    [
                        (problem["field"], problem["message"])
                        for problem in field_problems(
                            exc.errors(include_url=False, include_input=False), root="graph"
                        )
                    ]
                ) from exc
            stripped, unresolved = portable(graph)

        created = await self.registry.create(
            ctx, WorkflowCreate(name=data.name, description=data.description)
        )
        if data.tags:
            await self.registry.update(ctx, created.id, WorkflowUpdate(tags=data.tags))
        await self.registry.update_settings(
            ctx, created.id, data.settings.model_copy(update={"error_workflow_id": None})
        )
        if stripped is not None:
            draft = await self.registry.get(ctx, created.id)
            await self.registry.update_draft(
                ctx,
                created.id,
                WorkflowDraftUpdate(
                    graph=stripped.model_dump(mode="json"),
                    expected_revision=draft.draft_revision,
                ),
            )
        workflow = await self.registry.get(ctx, created.id)
        # What the export already took out is only listed in the file; what a
        # hand-made file still named was taken out just now. Both are to choose.
        steps = set() if stripped is None else {node.id for node in stripped.nodes}
        listed = {
            (item.node_id, item.field): item
            for item in [*data.unresolved, *_listed(unresolved)]
            if item.node_id in steps
        }
        return WorkflowImported(workflow=workflow, unresolved=list(listed.values()))
