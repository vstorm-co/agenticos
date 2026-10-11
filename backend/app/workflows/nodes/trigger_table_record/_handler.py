"""`trigger.table_record`: a workflow a table record's creation, change or deletion starts.

A record added to the table, changed or deleted - in the console, over the API,
by an agent or by another workflow - that matches every filter starts one run
with the record, for each event the trigger listens for. A change starts it only
when one of the table's chosen columns changed, when columns are chosen.
Publishing a version is what subscribes the workflow; nothing done before that
starts it.
"""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables.types import COLUMN_TYPES, CellProblem, validate_filter
from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._tables import check_table
from app.workflows.nodes._triggers import (
    TableRecordTriggerConfig,
    TableRecordTriggerOutput,
    run_input_as,
)


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """The table, readable by the graph's author and current, every filter on one of
    its live columns with an operand that suits the column's type, and every watched
    column one a record stores - a column worked out on read never changes."""
    if not isinstance(config, TableRecordTriggerConfig):
        return []
    problems = await check_table(db, ctx, config.table, writes=False)
    if problems or not (config.filters or config.table.column_ids):
        return problems
    version = await virtual_table_repo.get_schema_version(
        db, table_id=config.table.table_id, version=config.table.schema_version
    )
    live = {
        column.id: column
        for column in (ColumnDef.model_validate(item) for item in version.columns)
        if not column.archived
    }
    for index, column_id in enumerate(config.table.column_ids or []):
        watched = live.get(column_id)
        if watched is None or COLUMN_TYPES[watched.type].computed:
            problems.append(
                (f"table.column_ids.{index}", "A change is watched on a column a record stores")
            )
    for index, condition in enumerate(config.filters):
        column = live.get(condition.column_id)
        if column is None:
            problems.append((f"filters.{index}.column_id", "Not a live column of this table"))
            continue
        try:
            validate_filter(column, condition.op, condition.value)
        except CellProblem as problem:
            problems.append((f"filters.{index}", str(problem)))
    return problems


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the record the run was started with."""
    record = run_input_as(TableRecordTriggerOutput)
    if isinstance(record, Failed):
        return record
    return Completed[TableRecordTriggerOutput](output=record)
