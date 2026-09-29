"""`TableTriggerService` - run a workflow when a record is added (#1785).

Setting one up needs `tables:edit` on the table and `workflows:run` on the
workflow, because it runs as the member doing it: whoever creates or changes a
trigger becomes the one its runs act as, and nobody can name someone else. The
workflow's live version is pinned when the trigger is made, and moves only when
asked.

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
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
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
    TableTriggerCreate,
    TableTriggerList,
    TableTriggerRead,
    TableTriggerUpdate,
)
from app.services.access import TABLE, WORKFLOW, resolve_access
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.types import COLUMN_TYPES, CellProblem, validate_filter
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowNotRunnableError,
    WorkflowRunInputTooLargeError,
)
from app.services.workflow_execution.facade import Causation, WorkflowExecutionService

logger = logging.getLogger(__name__)

AUTHOR = "@author"
"""The mapping source naming the record's author - not a column."""

RECORD_ID = "@record_id"
"""The mapping source naming the record itself, for a run that changes it back."""

_BUILT_IN_SOURCES = frozenset({AUTHOR, RECORD_ID})

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

    async def create(
        self, ctx: AuthContext, table_id: UUID, data: TableTriggerCreate
    ) -> TableTriggerRead:
        """A trigger on the table, pinned to the workflow's live version, switched on.

        Raises:
            NotFoundError: The table or the workflow is out of reach.
            AuthorizationError: The caller may edit the table but not run the workflow.
            WorkflowNotRunnableError: The workflow has never been published.
            BadRequestError: A filter or a mapping names something the table lacks.
        """
        # Locked: the same lock a record write waits on, so `activated_at` is a
        # boundary no write can straddle.
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        self._ensure_live(table)
        workflow = await self._runnable_workflow(ctx, data.workflow_id)
        if workflow.current_version_id is None:
            raise WorkflowNotRunnableError(workflow_id=workflow.id)
        columns = await self._columns(table)
        filters = _checked_filters(columns, data.filters)
        mapping = _checked_mapping(columns, data.input_mapping)
        trigger = await trigger_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            table_id=table.id,
            workflow_id=workflow.id,
            workflow_version_id=workflow.current_version_id,
            name=data.name,
            revision=1,
            filters=filters,
            input_mapping=mapping,
            execution_principal_user_id=ctx.subject_id,
            is_active=True,
            activated_at=trigger_repo.activation_time(),
        )
        await trigger_repo.add_revision(self.db, trigger=trigger)
        await self._audit(ctx, trigger, "table.trigger_created")
        return await self._trigger_read(trigger)

    async def update(
        self, ctx: AuthContext, table_id: UUID, trigger_id: UUID, data: TableTriggerUpdate
    ) -> TableTriggerRead:
        """Change a trigger; it runs as the caller from then on.

        Switching it back on stamps a new `activated_at`, so the records added
        while it was off never start it.

        Raises:
            NotFoundError: The table, the trigger or its workflow is out of reach.
            AuthorizationError: The caller may edit the table but not run the workflow.
            WorkflowNotRunnableError: `pin_current_version` with nothing published.
            BadRequestError: A filter or a mapping names something the table lacks.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT, lock=True)
        self._ensure_live(table)
        trigger = await self._trigger(ctx, table.id, trigger_id)
        workflow = await self._runnable_workflow(ctx, trigger.workflow_id)
        columns = await self._columns(table)
        changes: dict[str, Any] = {"execution_principal_user_id": ctx.subject_id}
        if "name" in data.model_fields_set:
            changes["name"] = data.name
        if data.filters is not None:
            changes["filters"] = _checked_filters(columns, data.filters)
        if data.input_mapping is not None:
            changes["input_mapping"] = _checked_mapping(columns, data.input_mapping)
        if data.pin_current_version:
            if workflow.current_version_id is None:
                raise WorkflowNotRunnableError(workflow_id=workflow.id)
            changes["workflow_version_id"] = workflow.current_version_id
        if data.is_active is not None:
            changes["is_active"] = data.is_active
            if data.is_active and not trigger.is_active:
                changes["activated_at"] = trigger_repo.activation_time()
        configured = {"filters", "input_mapping", "workflow_version_id"} & set(changes)
        if (
            configured
            or changes["execution_principal_user_id"] != trigger.execution_principal_user_id
        ):
            changes["revision"] = trigger.revision + 1
        trigger = await trigger_repo.update(self.db, trigger=trigger, update_data=changes)
        if "revision" in changes:
            await trigger_repo.add_revision(self.db, trigger=trigger)
        await self._audit(
            ctx,
            trigger,
            "table.trigger_updated",
            changed=sorted(key for key in changes if key != "execution_principal_user_id"),
        )
        return await self._trigger_read(trigger)

    async def delete(self, ctx: AuthContext, table_id: UUID, trigger_id: UUID) -> None:
        """Remove a trigger. Runs it already started keep going.

        Raises:
            NotFoundError: The table or the trigger is out of reach.
        """
        table = await self._load_table(ctx, table_id, Perm.TABLES_EDIT)
        trigger = await self._trigger(ctx, table.id, trigger_id)
        await self._audit(ctx, trigger, "table.trigger_deleted")
        await trigger_repo.delete(self.db, trigger=trigger)

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

    async def _runnable_workflow(self, ctx: AuthContext, workflow_id: UUID) -> Workflow:
        workflow = await workflow_repo.get(
            self.db, workflow_id, organization_id=ctx.organization_id
        )
        if workflow is None or not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
        ):
            raise NotFoundError(
                message="Workflow not found", details={"workflow_id": str(workflow_id)}
            )
        if workflow.status == WorkflowStatus.ARCHIVED.value or not await resolve_access(
            self.db, ctx, workflow, Perm.WORKFLOWS_RUN, resource_type=WORKFLOW
        ):
            raise AuthorizationError(
                message="A trigger runs as you, so you need to be able to run its workflow",
                details={"workflow_id": str(workflow_id)},
            )
        return workflow

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
            name=trigger.name,
            revision=trigger.revision,
            filters=[RecordFilter.model_validate(item) for item in trigger.filters],
            input_mapping=trigger.input_mapping,
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


def _checked_mapping(columns: list[ColumnDef], mapping: dict[str, str]) -> dict[str, str]:
    """The mapping with its keys trimmed, refused when a key is blank or a source is
    neither a live column nor one of `@author` and `@record_id`. Two keys that are the
    same once trimmed are refused by the request schema, before they collapse."""
    live = {str(column.id) for column in columns if not column.archived}
    checked: dict[str, str] = {}
    for raw, source in mapping.items():
        key = raw.strip()
        if not key or len(key) > 64:
            raise BadRequestError(
                message="A mapping key must be 1 to 64 characters",
                details={"field": "input_mapping"},
            )
        if source not in _BUILT_IN_SOURCES and source not in live:
            raise BadRequestError(
                message=f"'{key}' takes its value from a column this table does not have",
                details={"field": f"input_mapping.{key}"},
            )
        checked[key] = source
    return checked


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
        built_in = {
            AUTHOR: str(snapshot.actor_user_id) if snapshot.actor_user_id else None,
            RECORD_ID: str(event.record_id),
        }
        payload = {
            key: built_in[source] if source in built_in else values.get(source)
            for key, source in trigger.input_mapping.items()
        }
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
