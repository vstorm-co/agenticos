"""Stable field identities: Table, Kanban and task tools edit the same record."""

from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.task_board import TaskBoard
from app.repositories import task as task_repo
from app.schemas.task import TaskFields, TaskStatus
from app.schemas.virtual_table import CellValue, ColumnInput, OptionInput

STATUSES: tuple[TaskStatus, ...] = (
    "planned",
    "in_progress",
    "waiting_for_user",
    "blocked",
    "done",
    "cancelled",
)
_CELL = TypeAdapter(CellValue)


def task_columns() -> list[ColumnInput]:
    return [
        ColumnInput(label="Task", type="text", nullable=False),
        ColumnInput(
            label="Status",
            type="single_select",
            nullable=False,
            default="Planned",
            options=[
                OptionInput(label=status.replace("_", " ").capitalize()) for status in STATUSES
            ],
        ),
        ColumnInput(label="Notes", type="rich_text"),
        ColumnInput(label="Person", type="user"),
        ColumnInput(label="Agent", type="agent"),
        ColumnInput(label="Start at", type="datetime"),
        ColumnInput(label="Due at", type="datetime"),
        ColumnInput(
            label="Next step",
            type="single_select",
            nullable=False,
            default="Person",
            options=[OptionInput(label="Person"), OptionInput(label="Agent")],
        ),
    ]


def to_cells(board: TaskBoard, data: TaskFields) -> dict[str, CellValue]:
    return {
        board.column_ids[name]: board.status_ids[data.status]
        if name == "status"
        else board.status_ids[f"actor:{data.next_actor}"]
        if name == "next_actor"
        else _CELL.validate_python(value)
        for name, value in data.model_dump(mode="json").items()
    }


def from_cells(board: TaskBoard, values: dict[str, object]) -> TaskFields:
    status = values.get(board.column_ids["status"])
    actor = values.get(board.column_ids["next_actor"])
    next_actor = next(
        (name for name in ("user", "agent") if actor == board.status_ids[f"actor:{name}"]), None
    )
    selected = next((item for item in STATUSES if board.status_ids[item] == status), None)
    return TaskFields.model_validate(
        {
            **{
                name: values.get(board.column_ids[name])
                for name in TaskFields.model_fields
                if name != "status"
            },
            "description": values.get(board.column_ids["description"]) or "",
            "status": selected,
            "next_actor": next_actor,
        }
    )


async def normalize_task_cells(
    db: AsyncSession, organization_id: UUID, table_id: UUID, values: dict[str, CellValue]
) -> dict[str, CellValue]:
    board = await task_repo.for_table(db, table_id, organization_id)
    if board is not None and values.get(board.column_ids["status"]) in {
        board.status_ids["waiting_for_user"],
        board.status_ids["blocked"],
    }:
        return {**values, board.column_ids["next_actor"]: board.status_ids["actor:user"]}
    return values
