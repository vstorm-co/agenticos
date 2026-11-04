"""Publish and maintain independent workflow entry registrations.

Each unattended kind has one registration. Republishing keeps its node's address
and credentials, updates the pinned version, and removes entries no longer present.
`live_trigger` retains the default for older clients; `live_triggers` lists all starts.
"""

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
from app.services.workflow_authority import require_human_publisher
from app.services.workflow_exposure import WorkflowExposureService
from app.workflows.graph.model import WorkflowGraph
from app.workflows.nodes._triggers import ScheduleTriggerConfig, TableRecordTriggerConfig
from app.workflows.nodes.trigger_channel_message._handler import ChannelMessageTriggerConfig
from app.workflows.nodes.trigger_github._handler import GithubTriggerConfig
from app.workflows.triggers import (
    CHANNEL_MESSAGE,
    FORM,
    GITHUB,
    GMAIL,
    OUTLOOK,
    SCHEDULE,
    TABLE_RECORD,
    TRIGGERS,
    UNATTENDED,
    WEBHOOK,
    entry_nodes,
    live_trigger,
)


@dataclass(frozen=True)
class SwitchedOn:
    """What a publish switched on: the trigger, and a secret to paste, once."""

    trigger: str | None
    exposure: WorkflowExposureRead | None
    webhook_secret: str | None
    exposures: tuple[WorkflowExposureRead, ...] = ()
    trigger_secrets: dict[str, str] | None = None


class WorkflowTriggerSync:
    """Synchronize every published entry and its retained publisher authority."""

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
            AlreadyExistsError: Another workflow already starts from the channel
                trigger's bot.
            BadRequestError: A Gmail or Outlook trigger, and no mailbox connected.
        """
        nodes = entry_nodes(graph)
        unattended = any(node.definition_id in UNATTENDED for node in nodes)
        if unattended:
            require_human_publisher(ctx)
        if unattended and not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        ):
            raise AuthorizationError(
                message="Publishing unattended triggers requires permission to run this workflow",
                details={"workflow_id": str(workflow.id)},
            )
        registered: list[WorkflowExposureRead] = []
        secrets: dict[str, str] = {}
        for node in nodes:
            trigger = node.definition_id
            exposure: WorkflowExposureRead | None = None
            secret: str | None = None
            if trigger == WEBHOOK:
                exposure, secret = await self.exposures.switch_on_webhook(
                    ctx, workflow, version, node.id
                )
            elif trigger == SCHEDULE:
                exposure = await self.exposures.switch_on_schedule(
                    ctx,
                    workflow,
                    version,
                    node.id,
                    ScheduleTriggerConfig.model_validate(node.config),
                )
            elif trigger == GITHUB:
                exposure, secret = await self.exposures.switch_on_github(
                    ctx, workflow, version, node.id, GithubTriggerConfig.model_validate(node.config)
                )
            elif trigger == GMAIL:
                exposure = await self.exposures.switch_on_gmail(ctx, workflow, version, node.id)
            elif trigger == OUTLOOK:
                exposure = await self.exposures.switch_on_outlook(ctx, workflow, version, node.id)
            elif trigger == FORM:
                exposure = await self.exposures.switch_on_form(ctx, workflow, version, node.id)
            elif trigger == CHANNEL_MESSAGE:
                exposure = await self.exposures.switch_on_channel(
                    ctx,
                    workflow,
                    version,
                    node.id,
                    ChannelMessageTriggerConfig.model_validate(node.config),
                )
            if trigger == TABLE_RECORD:
                await self.tables.switch_on(
                    ctx,
                    workflow,
                    version,
                    node.id,
                    TableRecordTriggerConfig.model_validate(node.config),
                )
            if exposure is not None:
                registered.append(exposure)
            if secret is not None:
                secrets[str(node.id)] = secret
        await self.exposures.switch_off(
            ctx, workflow, keep_node_ids=frozenset(node.id for node in nodes)
        )
        if not any(node.definition_id == TABLE_RECORD for node in nodes):
            await self.tables.switch_off(ctx, workflow)
        trigger = live_trigger(graph)
        await workflow_repo.update(
            self.db,
            workflow=workflow,
            update_data={
                "live_trigger": trigger,
                "live_triggers": [
                    node.definition_id for node in nodes if node.definition_id in TRIGGERS
                ],
            },
        )
        return SwitchedOn(
            trigger=trigger,
            exposure=registered[0] if registered else None,
            webhook_secret=secrets.get(str(registered[0].node_instance_id)) if registered else None,
            exposures=tuple(registered),
            trigger_secrets=secrets,
        )

    async def remove(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Remove trigger registrations before their workflow is deleted."""
        await self.exposures.switch_off(ctx, workflow)
        await self.tables.switch_off(ctx, workflow)

    async def states(self, organization_id: UUID, workflow_ids: list[UUID]) -> dict[UUID, bool]:
        """Whether each workflow's unattended trigger is on, for those that have one."""
        states = await workflow_exposure_repo.active_by_workflow(
            self.db, organization_id=organization_id, workflow_ids=workflow_ids
        )
        table_states = await table_trigger_repo.active_by_workflow(
            self.db, organization_id=organization_id, workflow_ids=workflow_ids
        )
        for workflow_id, active in table_states.items():
            states[workflow_id] = states.get(workflow_id, False) or active
        return states

    async def set_active(self, ctx: AuthContext, workflow: Workflow, active: bool) -> None:
        """Switch the live version's unattended trigger on or pause it.

        The caller has been let edit and run the workflow: resumed, the trigger
        runs as its publisher again.

        Raises:
            BadRequestError: The live version starts by hand, from an API call or
                from chat, so there is nothing to switch.
        """
        exposures = await workflow_exposure_repo.list_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        for exposure in exposures:
            await self.exposures.set_active(
                ctx, workflow.id, exposure.id, WorkflowExposureUpdate(is_active=active)
            )
        table = await self.tables.set_active_for_workflow(ctx, workflow, active)
        if not exposures and table is None:
            raise BadRequestError(
                message="This workflow starts by hand, from an API call or from chat, "
                "so it has no trigger to switch on or off",
                details={"workflow_id": str(workflow.id)},
            )

    async def retime(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Keep the workflow's schedule in the timezone its settings now name."""
        await self.exposures.retime(ctx, workflow)

    async def pause(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Pause whatever trigger the workflow has - what archiving it does."""
        await self.exposures.pause(ctx, workflow)
        await self.tables.set_active_for_workflow(ctx, workflow, False)


__all__ = ["SwitchedOn", "WorkflowTriggerSync"]
