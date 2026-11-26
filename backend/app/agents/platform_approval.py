"""Trusted platform task writes that may schedule independently approved work."""

from uuid import UUID

from pydantic import TypeAdapter

from app.agents.deps import AgentDeps
from app.core.platform_tool_policy import CONDITIONAL_EXECUTION
from app.db.session import get_db_context
from app.schemas.task import TaskCreate, TaskUpdate
from app.schemas.virtual_table import CellValue, RecordUpdate, RecordUpsert
from app.services.access import member_context
from app.services.tasks import TaskService, task_may_schedule_agent_work

_UUID = TypeAdapter(UUID)
_CELLS = TypeAdapter(dict[str, CellValue])


async def may_schedule_agent_work(tool_name: str, deps: AgentDeps, args: dict[str, object]) -> bool:
    """A floor, never permission; malformed/failed checks are caught by the gate."""
    if tool_name not in CONDITIONAL_EXECUTION:
        return True
    if tool_name == "create_task":
        return task_may_schedule_agent_work(TaskCreate.model_validate(args.get("task")))
    if tool_name == "update_task":
        return task_may_schedule_agent_work(TaskUpdate.model_validate(args.get("task")))
    if deps.organization_id is None or deps.run_person is None:
        return True
    table_id = _UUID.validate_python(args.get("table_id"))
    async with get_db_context() as db:
        ctx = await member_context(
            db, organization_id=deps.organization_id, user_id=deps.run_person
        )
        if ctx is None:
            return True
        service = TaskService(db)
        if tool_name == "add_virtual_table_record":
            return await service.record_may_schedule_agent_work(
                ctx, table_id, _CELLS.validate_python(args.get("values")), operation="add"
            )
        if tool_name == "update_virtual_table_record":
            update = RecordUpdate.model_validate(args.get("update"))
            return await service.record_may_schedule_agent_work(
                ctx,
                table_id,
                update.values,
                operation="update",
                record_id=_UUID.validate_python(args.get("record_id")),
                expected_revision=update.expected_revision,
            )
        record = RecordUpsert.model_validate(args.get("record"))
        return await service.record_may_schedule_agent_work(
            ctx, table_id, record.values, operation="upsert"
        )
