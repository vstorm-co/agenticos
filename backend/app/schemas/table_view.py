"""Schemas for a saved table view: a kept filter/sort/grouping over one table.

`config` reuses `RecordFilter`/`RecordSort` from `app/schemas/virtual_table.py`
directly - a saved view's config is literally a `RecordQuery` plus the two
console-only fields (`visible_columns`, `group_by`) that have no equivalent on a
raw record query. `visible_columns: None` means "all live columns", matching how
the table itself treats an absent column list.
"""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.virtual_table import MAX_FILTERS, RecordFilter, RecordSort, SearchTerm
from app.workflows.graph.model import jsonb_value_fits

ViewKind = Literal["table", "kanban", "list"]
ViewVisibility = Literal["private", "shared"]

ViewName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class _Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _Request(_Schema):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    @model_validator(mode="after")
    def _stored_values_fit(self) -> Self:
        jsonb_value_fits(self)
        return self


SystemColumnKey = Literal["created_at", "updated_at", "created_by", "updated_by"]
ViewColumnKey = UUID | SystemColumnKey


class TableDisplay(_Request):
    """Presentation only: never changes stored cells, query order or the table schema."""

    column_order: list[ViewColumnKey] = Field(default_factory=list, max_length=500)
    hidden_system_columns: list[SystemColumnKey] = Field(default_factory=list, max_length=4)
    wrap_text: bool = False
    date_format: Literal["locale", "iso", "day_first", "month_first", "long"] = "locale"
    time_format: Literal["locale", "24h", "12h", "hidden"] = "locale"

    @model_validator(mode="after")
    def _unique_columns(self) -> Self:
        if len(self.column_order) != len(set(self.column_order)):
            raise ValueError("Column order must not contain duplicates")
        if len(self.hidden_system_columns) != len(set(self.hidden_system_columns)):
            raise ValueError("Hidden system columns must not contain duplicates")
        return self


class TableViewConfig(_Request):
    """What a saved view remembers: the same shape a `RecordQuery` filters with,
    plus the two fields only the console's own rendering needs."""

    display: TableDisplay = Field(default_factory=TableDisplay)
    filters: list[RecordFilter] = Field(default_factory=list, max_length=MAX_FILTERS)
    search: SearchTerm | None = Field(default=None, description="As a `RecordQuery`'s.")
    sort: RecordSort = Field(default_factory=RecordSort)
    visible_columns: list[UUID] | None = Field(
        default=None, description="`null` means every live column."
    )
    group_by: UUID | None = Field(
        default=None, description="A live `single_select` column. Required for a kanban view."
    )


class TableViewCreate(_Request):
    name: ViewName
    kind: ViewKind
    visibility: ViewVisibility = "private"
    config: TableViewConfig = Field(default_factory=TableViewConfig)


class TableViewUpdate(_Request):
    """All fields optional; an absent field leaves it unchanged. `config` replaces
    the whole blob when sent, the same all-or-nothing shape `SchemaUpdate` uses."""

    name: ViewName | None = None
    visibility: ViewVisibility | None = None
    config: TableViewConfig | None = None


class TableViewRead(_Schema):
    id: UUID
    table_id: UUID
    owner_user_id: UUID
    name: str
    kind: ViewKind
    visibility: ViewVisibility
    config: TableViewConfig
    can_manage: bool = Field(
        description="Whether this caller may rename, reconfigure or reshare this view: "
        "its owner, or a caller whose `tables:edit` scope is `ALL`, while holding "
        "`tables:edit` on the table."
    )
    can_delete: bool = Field(
        description="Whether this caller may delete this view: its owner, or a caller whose "
        "`tables:edit` scope is `ALL`. Unlike `can_manage`, it does not need `tables:edit` "
        "on the table, so an owner who lost edit access can still remove their views."
    )
    created_at: datetime
    updated_at: datetime | None = None


class TableViewList(_Schema):
    items: list[TableViewRead]
    total: int
