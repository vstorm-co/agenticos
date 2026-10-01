"""`TableTriggerService` - run a workflow when a record is added (#1785).

A workflow whose trigger node is `trigger.table_record` is subscribed to its
table when a version is published (`app.services.workflow_triggers`): the
trigger runs that version as the member who published it, and nobody can name
someone else. A later publish moves it to the new version. Pausing and resuming
from the table need `tables:edit`.

Switching a trigger on takes the table's schema lock, the one record writes
wait on, before stamping `activated_at`. A write that started before the switch
has committed by then and is on the far side of the boundary; none can start
until the stamp is in. So a trigger never starts on a record added before it
was on - no backlog on activation, no replay of the time it was off.

`TableTriggerConsumer` is the other half: it claims undelivered
`table.record.created` events and, per active trigger on the event's table,
records one `TableTriggerAdmission` - a queued run, or filtered, blocked or
failed with a coarse reason - in a savepoint of its own. The unique
`(trigger, event)` key is what makes a second consumer's pass admit nothing.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.virtual_table import (
    VirtualTable,
    VirtualTableOutbox,
    VirtualTableRecordHistory,
)
from app.db.models.virtual_table_trigger import (
    AdmissionReason,
    AdmissionStatus,
    VirtualTableTrigger,
)
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun, WorkflowRunTrigger
from app.repositories import member_repo, virtual_table_repo
from app.repositories import virtual_table_trigger as trigger_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_run as workflow_run_repo
from app.repositories.virtual_table import SqlKind
from app.schemas.virtual_table import ColumnDef, RecordFilter
from app.schemas.virtual_table_trigger import (
    TableTriggerAdmissionList,
    TableTriggerAdmissionRead,
    TableTriggerList,
    TableTriggerRead,
    TableTriggerUpdate,
)
from app.services.access import TABLE, WORKFLOW, resolve_access
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.presentation import readable
from app.services.virtual_tables.types import COLUMN_TYPES, CellProblem, validate_filter
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowRunInputTooLargeError,
)
from app.services.workflow_execution.facade import Causation, WorkflowExecutionService
from app.workflows.nodes._triggers import TableRecordTriggerConfig, TableRecordTriggerOutput

logger = logging.getLogger(__name__)

MAX_DEPTH = 5
"""How many table triggers deep one chain of runs may go before the next is blocked."""

MAX_RUNS_PER_ROOT = 50
"""How many runs one chain may start through table triggers, whatever its shape."""


def _typed(kind: SqlKind, value: Any) -> Any:
    """A cell or an operand as the value SQL would compare it as.

    Both were validated for the column's type - a cell when it was written, an
    operand when the trigger was saved - so the conversion cannot fail here.
    """
    match kind:
        case SqlKind.NUMERIC | SqlKind.INTEGER:
            return Decimal(str(value))
        case SqlKind.DATE:
            return date.fromisoformat(str(value))
        case SqlKind.DATETIME:
            return datetime.fromisoformat(str(value))
        case _:
            return value


def holds(column: ColumnDef, condition: RecordFilter, values: dict[str, Any]) -> bool:
    """Whether one filter holds on a record's values - what the record query's SQL
    says of the same row, so a trigger and a filtered view agree about a record."""
    cell = values.get(str(condition.column_id))
    if condition.op == "is_null":
        return (cell is None) == bool(condition.value)
    if cell is None:
        return False
    kind = COLUMN_TYPES[column.type].kind
    if kind is SqlKind.ARRAY:
        return isinstance(cell, list) and condition.value in cell
    if condition.op == "in":
        operands = condition.value if isinstance(condition.value, list) else []
        return _typed(kind, cell) in {_typed(kind, item) for item in operands}
    if condition.op == "contains":
        return str(condition.value).casefold() in str(cell).casefold()
    if condition.op == "starts_with":
        return str(cell).startswith(str(condition.value))
    left, right = _typed(kind, cell), _typed(kind, condition.value)
    match condition.op:
        case "eq":
            return bool(left == right)
        case "ne":
            return bool(left != right)
        case "lt":
            return bool(left < right)
        case "lte":
            return bool(left <= right)
        case "gt":
            return bool(left > right)
        case _:
            return bool(left >= right)


class TableTriggerService(Operations):
    """Create, change, remove and read a table's triggers and what they decided."""

    async def list_for_table(self, ctx: AuthContext, table_id: UUID) -> TableTriggerList:
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        triggers = await trigger_repo.list_for_table(
            self.db, table_id=table.id, organization_id=ctx.organization_id
        )
        return TableTriggerList(items=[await self._trigger_read(trigger) for trigger in triggers])

    async def switch_on(
        self,
        ctx: AuthContext,
        workflow: Workflow,
        version: WorkflowVersion,
        node_id: UUID,
        config: TableRecordTriggerConfig,
    ) -> VirtualTableTrigger:
        """Subscribe a version just published to its table's new records, as its publisher.

        The row the same node had on the same table takes the new version and
        filters over, as a new revision; a trigger on another table or node is
        replaced. Switching one on - new, or paused until now - stamps
        `activated_at` under the table's schema lock, so no record added before
        this publish starts it.

        Raises:
            NotFoundError: The table is out of reach.
            TableArchivedError: The table is archived.
            BadRequestError: A filter names no live column or misfits its type.
        """
        table = await self._load_table(ctx, config.table.table_id, Perm.TABLES_VIEW, lock=True)
        self._ensure_live(table)
        filters = _checked_filters(await self._columns(table), config.filters)
        trigger = await trigger_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if trigger is not None and (trigger.node_instance_id, trigger.table_id) != (
            node_id,
            table.id,
        ):
            await self._remove(ctx, trigger)
            trigger = None
        if trigger is None:
            trigger = await trigger_repo.create(
                self.db,
                organization_id=ctx.organization_id,
                table_id=table.id,
                workflow_id=workflow.id,
                workflow_version_id=version.id,
                node_instance_id=node_id,
                revision=1,
                filters=filters,
                execution_principal_user_id=ctx.subject_id,
                is_active=True,
                activated_at=trigger_repo.activation_time(),
            )
            await trigger_repo.add_revision(self.db, trigger=trigger)
            await self._audit(ctx, trigger, "table.trigger_created")
            return trigger
        changes: dict[str, Any] = {
            "workflow_version_id": version.id,
            "filters": filters,
            "execution_principal_user_id": ctx.subject_id,
            "revision": trigger.revision + 1,
            "is_active": True,
        }
        if not trigger.is_active:
            changes["activated_at"] = trigger_repo.activation_time()
        trigger = await trigger_repo.update(self.db, trigger=trigger, update_data=changes)
        await trigger_repo.add_revision(self.db, trigger=trigger)
        await self._audit(ctx, trigger, "table.trigger_updated")
        return trigger

    async def switch_off(self, ctx: AuthContext, workflow: Workflow) -> None:
        """Remove the workflow's table trigger: its live version starts some other way.

        Runs it already started keep going.
        """
        trigger = await trigger_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if trigger is not None:
            await self._remove(ctx, trigger)

    async def set_active(
        self, ctx: AuthContext, table_id: UUID, trigger_id: UUID, data: TableTriggerUpdate
    ) -> TableTriggerRead:
        """Pause or resume a trigger; it keeps running as whoever published it.

        Resuming stamps a new `activated_at`, so the records added while it was
        paused never start it.

        Raises:
            NotFoundError: The table or the trigger is out of reach.
            TableArchivedError: The table is archived.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        self._ensure_live(table)
        trigger = await self._trigger(ctx, table.id, trigger_id)
        changes: dict[str, Any] = {"is_active": data.is_active}
        if data.is_active and not trigger.is_active:
            changes["activated_at"] = trigger_repo.activation_time()
        trigger = await trigger_repo.update(self.db, trigger=trigger, update_data=changes)
        await self._audit(
            ctx, trigger, "table.trigger_resumed" if data.is_active else "table.trigger_paused"
        )
        return await self._trigger_read(trigger)

    async def set_active_for_workflow(
        self, ctx: AuthContext, workflow: Workflow, active: bool
    ) -> bool | None:
        """Pause or resume the workflow's table trigger; `None` when it has none.

        For the workflow's own switch, so what it needs is the caller's say over
        the workflow, which is theirs to check first - not edit access to the table.
        Resuming reads the table, as publishing did, and stamps a new `activated_at`
        under its schema lock, so the records added while it was paused never start
        it. Pausing touches no table.

        Raises:
            NotFoundError: Resuming, and the table is out of reach.
            TableArchivedError: Resuming, and the table is archived.
        """
        trigger = await trigger_repo.get_for_workflow(
            self.db, workflow_id=workflow.id, organization_id=ctx.organization_id
        )
        if trigger is None:
            return None
        if trigger.is_active == active:
            return active
        changes: dict[str, Any] = {"is_active": active}
        if active:
            table = await self._load_table(ctx, trigger.table_id, Perm.TABLES_VIEW, lock=True)
            self._ensure_live(table)
            changes["activated_at"] = trigger_repo.activation_time()
        await trigger_repo.update(self.db, trigger=trigger, update_data=changes)
        await self._audit(
            ctx, trigger, "table.trigger_resumed" if active else "table.trigger_paused"
        )
        return active

    async def admissions(
        self, ctx: AuthContext, table_id: UUID, trigger_id: UUID, *, skip: int, limit: int
    ) -> TableTriggerAdmissionList:
        """What the trigger decided about each added record, newest first."""
        table = await self._load_table(ctx, table_id, Perm.TABLES_VIEW)
        trigger = await self._trigger(ctx, table.id, trigger_id)
        rows, total = await trigger_repo.list_admissions(
            self.db, trigger_id=trigger.id, skip=skip, limit=limit
        )
        return TableTriggerAdmissionList(
            items=[TableTriggerAdmissionRead.model_validate(row) for row in rows], total=total
        )

    async def _trigger(
        self, ctx: AuthContext, table_id: UUID, trigger_id: UUID
    ) -> VirtualTableTrigger:
        trigger = await trigger_repo.get(
            self.db, trigger_id, organization_id=ctx.organization_id, table_id=table_id
        )
        if trigger is None:
            raise NotFoundError(
                message="Trigger not found", details={"trigger_id": str(trigger_id)}
            )
        return trigger

    async def _remove(self, ctx: AuthContext, trigger: VirtualTableTrigger) -> None:
        await self._audit(ctx, trigger, "table.trigger_deleted")
        await trigger_repo.delete(self.db, trigger=trigger)

    async def _trigger_read(self, trigger: VirtualTableTrigger) -> TableTriggerRead:
        workflow = await workflow_repo.get(
            self.db, trigger.workflow_id, organization_id=trigger.organization_id
        )
        version = await workflow_repo.get_version(
            self.db, trigger.workflow_version_id, organization_id=trigger.organization_id
        )
        return TableTriggerRead(
            id=trigger.id,
            table_id=trigger.table_id,
            workflow_id=trigger.workflow_id,
            workflow_name=workflow.name if workflow is not None else "",
            workflow_version_id=trigger.workflow_version_id,
            version_number=version.version if version is not None else 0,
            node_instance_id=trigger.node_instance_id,
            revision=trigger.revision,
            filters=[RecordFilter.model_validate(item) for item in trigger.filters],
            execution_principal_user_id=trigger.execution_principal_user_id,
            is_active=trigger.is_active,
            activated_at=trigger.activated_at,
            created_at=trigger.created_at,
            updated_at=trigger.updated_at,
        )

    async def _audit(
        self, ctx: AuthContext, trigger: VirtualTableTrigger, action: str, **details: Any
    ) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="table",
            target_id=str(trigger.table_id),
            details={
                "trigger_id": str(trigger.id),
                "workflow_id": str(trigger.workflow_id),
                **details,
            },
        )


def _checked_filters(columns: list[ColumnDef], filters: list[RecordFilter]) -> list[dict[str, Any]]:
    """The filters as stored, refused when one names no live column or misfits its type."""
    live = {column.id: column for column in columns if not column.archived}
    stored: list[dict[str, Any]] = []
    for index, condition in enumerate(filters):
        column = live.get(condition.column_id)
        if column is None:
            raise BadRequestError(
                message="A filter names a column this table does not have",
                details={"field": f"filters.{index}.column_id"},
            )
        try:
            value = validate_filter(column, condition.op, condition.value)
        except CellProblem as problem:
            raise BadRequestError(
                message=str(problem), details={"field": f"filters.{index}"}
            ) from None
        stored.append(
            RecordFilter(column_id=column.id, op=condition.op, value=value).model_dump(mode="json")
        )
    return stored


class TableTriggerConsumer:
    """Turn undelivered record-created events into admissions, once each per trigger."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runs = WorkflowExecutionService(db)

    async def consume(self, *, limit: int = 100) -> list[tuple[UUID, UUID]]:
        """Judge every claimed event against every active trigger on its table.

        One transaction for the claim, each trigger's decision in a savepoint of
        its own, and the event marked delivered last - so a decision that raised
        costs only itself, and a crash leaves the event for the next pass, where
        the triggers already decided are found by their admission row.

        Returns `(run_id, entry_node_run_id)` for every run admitted, for the
        caller to submit once this transaction commits.
        """
        admitted: list[tuple[UUID, UUID]] = []
        now = datetime.now(UTC)
        for event in await trigger_repo.claim_pending(self.db, limit=limit):
            triggers = await trigger_repo.list_for_table(
                self.db,
                table_id=event.table_id,
                organization_id=event.organization_id,
                active_only=True,
            )
            if triggers:
                snapshot = await trigger_repo.creation_snapshot(
                    self.db,
                    record_id=event.record_id,
                    revision=int(event.payload.get("revision", 1)),
                )
                causing = await self._causing_run(event)
                for trigger in triggers:
                    if await trigger_repo.admitted(
                        self.db, trigger_id=trigger.id, event_id=event.id
                    ):
                        continue
                    async with self.db.begin_nested():
                        # Judged as it is now: one switched off or changed since
                        # the list was read starts nothing under what it was.
                        current = await trigger_repo.lock_active(self.db, trigger_id=trigger.id)
                        pair = (
                            None
                            if current is None
                            else await self._decide(current, event, snapshot, causing)
                        )
                    if pair is not None:
                        admitted.append(pair)
            await trigger_repo.mark_dispatched(self.db, event=event, now=now)
        return admitted

    async def _causing_run(self, event: VirtualTableOutbox) -> WorkflowRun | None:
        """The run whose step wrote this record, if a workflow did."""
        raw = event.payload.get("causation_run_id")
        if not isinstance(raw, str):
            return None
        return await workflow_run_repo.get_run(
            self.db, UUID(raw), organization_id=event.organization_id
        )

    async def _decide(
        self,
        trigger: VirtualTableTrigger,
        event: VirtualTableOutbox,
        snapshot: VirtualTableRecordHistory | None,
        causing: WorkflowRun | None,
    ) -> tuple[UUID, UUID] | None:
        async def record(
            status: AdmissionStatus, reason: AdmissionReason | None, run_id: UUID | None = None
        ) -> None:
            await trigger_repo.add_admission(
                self.db,
                organization_id=event.organization_id,
                trigger_id=trigger.id,
                outbox_event_id=event.id,
                trigger_revision=trigger.revision,
                workflow_run_id=run_id,
                status=status.value,
                reason=reason.value if reason is not None else None,
            )

        if trigger.activated_at is None or event.created_at < trigger.activated_at:
            await record(AdmissionStatus.FILTERED, AdmissionReason.PRE_ACTIVATION)
            return None
        if causing is not None and str(trigger.id) in causing.visited_trigger_ids:
            await record(AdmissionStatus.BLOCKED, AdmissionReason.CYCLE)
            return None
        if causing is not None and causing.depth + 1 > MAX_DEPTH:
            await record(AdmissionStatus.BLOCKED, AdmissionReason.DEPTH_LIMIT)
            return None
        if snapshot is None:
            await record(AdmissionStatus.FAILED, AdmissionReason.UNAVAILABLE)
            return None
        values = snapshot.after or {}
        # The trigger's table foreign key cascades, so the table is there while it is.
        table = cast(
            VirtualTable,
            await virtual_table_repo.get_table(
                self.db, trigger.table_id, organization_id=trigger.organization_id
            ),
        )
        columns = await self._columns(table)
        conditions = [RecordFilter.model_validate(item) for item in trigger.filters]
        if not all(
            column is not None and holds(column, condition, values)
            for condition in conditions
            for column in [columns.get(condition.column_id)]
        ):
            await record(AdmissionStatus.FILTERED, AdmissionReason.FILTER_MISMATCH)
            return None
        fire = await self._fire_context(trigger, table)
        if fire is None:
            await record(AdmissionStatus.FAILED, AdmissionReason.PERMISSION_DENIED)
            return None
        ctx, workflow, version = fire
        if (
            causing is not None
            and await workflow_run_repo.count_runs_in_chain(
                self.db, root_run_id=causing.root_run_id
            )
            >= MAX_RUNS_PER_ROOT
        ):
            await record(AdmissionStatus.BLOCKED, AdmissionReason.QUOTA)
            return None
        payload = TableRecordTriggerOutput(
            table_id=table.id,
            record_id=event.record_id,
            values=values,
            fields={
                column.label: readable(column, values[str(column.id)])
                for column in columns.values()
                if not column.archived and str(column.id) in values
            },
            author_id=snapshot.actor_user_id,
        ).model_dump(mode="json")
        causation = Causation(
            root_run_id=causing.root_run_id if causing is not None else None,
            causation_run_id=causing.id if causing is not None else None,
            visited_trigger_ids=[
                *(causing.visited_trigger_ids if causing else []),
                str(trigger.id),
            ],
            depth=causing.depth + 1 if causing is not None else 0,
        )
        try:
            # A savepoint of its own, so a refused admission leaves the
            # `BLOCKED` row below and nothing of the half-made run.
            async with self.db.begin_nested():
                run, entry_node_run_id = await self.runs.admit_pinned(
                    ctx,
                    workflow,
                    version,
                    triggered_by=WorkflowRunTrigger.TABLE_CREATED,
                    run_input=payload,
                    causation=causation,
                )
        except (WorkflowAdmissionQuotaError, WorkflowRunInputTooLargeError):
            await record(AdmissionStatus.BLOCKED, AdmissionReason.QUOTA)
            return None
        await record(AdmissionStatus.QUEUED, None, run.id)
        return run.id, entry_node_run_id

    async def _columns(self, table: VirtualTable) -> dict[UUID, ColumnDef]:
        version = await virtual_table_repo.get_schema_version(
            self.db, table_id=table.id, version=table.schema_version
        )
        return {
            column.id: column
            for column in (ColumnDef.model_validate(item) for item in version.columns)
        }

    async def _fire_context(
        self, trigger: VirtualTableTrigger, table: VirtualTable
    ) -> tuple[AuthContext, Workflow, WorkflowVersion] | None:
        """The member it runs as, the workflow and its pinned version - or None when
        that member can no longer read the table or run the workflow."""
        if trigger.execution_principal_user_id is None:
            return None
        membership = await member_repo.get_active(
            self.db,
            organization_id=trigger.organization_id,
            user_id=trigger.execution_principal_user_id,
        )
        if membership is None:
            return None
        ctx = AuthContext(
            user_id=trigger.execution_principal_user_id,
            organization_id=trigger.organization_id,
            role=membership.role,
        )
        workflow = await workflow_repo.get(
            self.db, trigger.workflow_id, organization_id=trigger.organization_id
        )
        if (
            workflow is None
            or workflow.status == WorkflowStatus.ARCHIVED.value
            or not await resolve_access(self.db, ctx, table, Perm.TABLES_VIEW, resource_type=TABLE)
            or not await resolve_access(
                self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
            )
        ):
            return None
        # The pinned version's foreign key cascades, so it is there while the trigger is.
        version = cast(
            WorkflowVersion,
            await workflow_repo.get_version(
                self.db, trigger.workflow_version_id, organization_id=trigger.organization_id
            ),
        )
        return ctx, workflow, version
