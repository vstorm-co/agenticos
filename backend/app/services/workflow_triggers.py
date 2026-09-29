"""`WorkflowTriggerSync` - switch on the trigger a version just published starts from.

A workflow starts from one trigger node, its entry. Publishing a version is
what makes that trigger live, the way a builder expects from n8n or Zapier:

* a webhook or a schedule gets its exposure (`WorkflowExposureService`), and a
  new table record its subscription (`TableTriggerService`), running the new
  version as the member who published it. The row a node already had is kept,
  so a webhook's address and signing secret survive the publish;
* a trigger the new version no longer starts from is removed, so a workflow
  never keeps a second way in that its graph does not show;
* manual/API and chat triggers need no row - whoever starts the run is present
  and acts as themselves - so they only remove whatever row a previous version
  left.

`workflows.live_trigger` records which trigger the live version has, for the
surfaces that list what they can start.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, Perm
from app.db.models.workflow import Workflow, WorkflowVersion
from app.repositories import virtual_table_trigger as table_trigger_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_exposure as workflow_exposure_repo
from app.schemas.workflow_exposure import WorkflowExposureRead, WorkflowExposureUpdate
from app.services.access import WORKFLOW, resolve_access
from app.services.virtual_tables.triggers import TableTriggerService
from app.services.workflow_exposure import WorkflowExposureService
from app.workflows.graph.model import WorkflowGraph
from app.workflows.nodes._triggers import ScheduleTriggerConfig, TableRecordTriggerConfig
from app.workflows.triggers import SCHEDULE, TABLE_RECORD, WEBHOOK, live_trigger

# The triggers nobody is present for: each fire acts as the publisher.
_UNATTENDED = frozenset({WEBHOOK, SCHEDULE, TABLE_RECORD})


@dataclass(frozen=True)
class SwitchedOn:
    """What a publish switched on: the trigger, and a new webhook's secret, once."""

    trigger: str | None
    exposure: WorkflowExposureRead | None
    webhook_secret: str | None


class WorkflowTriggerSync:
    """Make a published version's trigger the workflow's one live way in."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.exposures = WorkflowExposureService(db)
        self.tables = TableTriggerService(db)

    async def switch_on(
        self, ctx: AuthContext, workflow: Workflow, version: WorkflowVersion, graph: WorkflowGraph
    ) -> SwitchedOn:
        """Switch on `version`'s trigger as `ctx`, and switch off every other.

        `graph` is the version's, already validated - its trigger's
        configuration and table were checked by `validate_graph`.

        Raises:
            AuthorizationError: The trigger runs unattended, as the publisher,
                and the publisher may edit the workflow but not run it.
            NotFoundError: A new-record trigger's table is out of reach.
            TableArchivedError: A new-record trigger's table is archived.
            BadRequestError: A new-record trigger's filter no longer fits its table.
        """
        trigger = live_trigger(graph)
        if trigger in _UNATTENDED and not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        ):
            raise AuthorizationError(
                message="This trigger runs as you once published, so you need to be able to run it",
                details={"workflow_id": str(workflow.id)},
            )
        node = graph.node_by_id[graph.entry_node_id]
        exposure: WorkflowExposureRead | None = None
        secret: str | None = None
        if trigger == WEBHOOK:
            exposure, secret = await self.exposures.switch_on_webhook(
                ctx, workflow, version, node.id
            )
        elif trigger == SCHEDULE:
            exposure = await self.exposures.switch_on_schedule(
                ctx, workflow, version, node.id, ScheduleTriggerConfig.model_validate(node.config)
            )
        else:
            await self.exposures.switch_off(ctx, workflow)
        if trigger == TABLE_RECORD:
            await self.tables.switch_on(
                ctx,
                workflow,
                version,
                node.id,
                TableRecordTriggerConfig.model_validate(node.config),
            )
        else:
            await self.tables.switch_off(ctx, workflow)
        await workflow_repo.update(
            self.db, workflow=workflow, update_data={"live_trigger": trigger}
        )
        return SwitchedOn(trigger=trigger, exposure=exposure, webhook_secret=secret)

    async def states(self, organization_id: UUID, workflow_ids: list[UUID]) -> dict[UUID, bool]:
        """Whether each workflow's unattended trigger is on, for those that have one."""
        states = await workflow_exposure_repo.active_by_workflow(
            self.db, organization_id=organization_id, workflow_ids=workflow_ids
        )
        states.update(
            await table_trigger_repo.active_by_workflow(
                self.db, organization_id=organization_id, workflow_ids=workflow_ids
            )
        )
        return states

    async def set_active(self, ctx: AuthContext, workflow: Workflow, active: bool) -> None:
        """Switch the live version's unattended trigger on or pause it.

        The caller has been let edit and run the workflow: resumed, the trigger
        runs as its publisher again.

        Raises:
            BadRequestError: The live version starts by hand, from an API call or
                from chat, so there is nothing to switch.
        """
        exposure = await workflow_exposure_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if exposure is not None:
            await self.exposures.set_active(
                ctx, workflow.id, exposure.id, WorkflowExposureUpdate(is_active=active)
            )
            return
        if await self.tables.set_active_for_workflow(ctx, workflow, active) is None:
            raise BadRequestError(
                message="This workflow starts by hand, from an API call or from chat, "
                "so it has no trigger to switch on or off",
                details={"workflow_id": str(workflow.id)},
            )

    async def pause(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Pause whatever trigger the workflow has - what archiving it does."""
        await self.exposures.pause(ctx, workflow)
        await self.tables.set_active_for_workflow(ctx, workflow, False)


__all__ = ["SwitchedOn", "WorkflowTriggerSync"]
