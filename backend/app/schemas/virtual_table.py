"""Schemas for Virtual Tables: the typed contract every table surface shares.

The web console, agent tools, workflow nodes and the public API all call the same
service with these models, so this module is the OpenAPI contract for tables.

**Text is preserved.** `BaseSchema` strips whitespace from every string, which is
right for a name typed in a form and wrong for a cell: a cell holding `"  a "`, a
trailing newline in a long text or a value that is all spaces is the user's data.
These models therefore do not inherit it. Names and labels are stripped explicitly
by `Label`; cell values are stored exactly as sent.

**Absent means null.** A record stores only the columns that hold a value. Sending
`null` for a column on an update clears it, and a read shows nothing for it.

**Requests reject unknown fields.** A misspelled `expected_revison` must be a 422,
not a write that silently skipped its concurrency check.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ColumnTypeName = Literal[
    "text",
    "long_text",
    "number",
    "integer",
    "boolean",
    "date",
    "datetime",
    "single_select",
    "multi_select",
]
FilterOp = Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "starts_with", "in", "is_null"]
SortDirection = Literal["asc", "desc"]
VisibilityName = Literal["private", "team", "org"]

CellValue = str | int | float | bool | list[str] | None
"""What one cell can hold. A select column stores option ids, a multi-select a list of them."""

FilterValue = CellValue | list[CellValue]

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
ExternalId = Annotated[str, StringConstraints(min_length=1, max_length=255)]
OperationKey = Annotated[str, StringConstraints(min_length=1, max_length=128)]

MAX_COLUMNS = 100
"""Columns per table, archived ones included: an archived column keeps its id and its values."""
MAX_OPTIONS = 100
MAX_FILTERS = 20
MAX_LIMIT = 100
MAX_SKIP = 10_000
"""A page never starts further in than this. Deep offsets scan and discard every row before them."""


class _Schema(BaseModel):
    """Read and write models: no whitespace stripping, see the module docstring."""

    model_config = ConfigDict(from_attributes=True)


class _Request(_Schema):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OptionDef(_Schema):
    """One choice of a select column, as stored."""

    id: UUID
    label: Label
    archived: bool = False


class OptionInput(_Request):
    """One choice as a schema change submits it. No `id` means a new one."""

    id: UUID | None = None
    label: Label
    archived: bool = False


class ColumnDef(_Schema):
    """One column of a schema version. The `id` never changes, whatever else does."""

    id: UUID
    label: Label
    type: ColumnTypeName
    nullable: bool = True
    default: CellValue = None
    options: list[OptionDef] = Field(default_factory=list)
    archived: bool = False


class ColumnInput(_Request):
    """One column as a schema change submits it.

    Send the `id` of an existing column to change it, and omit it to add one.
    An existing column left out of a change is archived, never deleted. A column's
    `type` cannot change: values already stored under the old type would no longer
    mean what they did.
    """

    id: UUID | None = None
    label: Label
    type: ColumnTypeName
    nullable: bool = True
    default: CellValue = None
    options: list[OptionInput] = Field(default_factory=list, max_length=MAX_OPTIONS)
    archived: bool = False


class TableCreate(_Request):
    name: Label = Field(description="Unique among the organization's live tables")
    description: str | None = Field(default=None, max_length=500)
    columns: list[ColumnInput] = Field(default_factory=list, max_length=MAX_COLUMNS)
    visibility: VisibilityName = "private"


class TableUpdate(_Request):
    name: Label | None = None
    description: str | None = Field(default=None, max_length=500)


class SchemaUpdate(_Request):
    """A new schema version. `expected_version` is the version the caller last saw."""

    expected_version: int = Field(ge=1)
    columns: list[ColumnInput] = Field(max_length=MAX_COLUMNS)


class TableSummary(_Schema):
    id: UUID
    name: str
    description: str | None = None
    visibility: VisibilityName
    owner_user_id: UUID | None = None
    schema_version: int
    archived_at: datetime | None = None
    created_at: datetime


class TableRead(TableSummary):
    columns: list[ColumnDef]
    updated_at: datetime | None = None


class TableList(_Schema):
    items: list[TableSummary]
    total: int


class SchemaVersionRead(_Schema):
    version: int
    columns: list[ColumnDef]
    created_by: UUID | None = None
    created_at: datetime


class SchemaVersionList(_Schema):
    items: list[SchemaVersionRead]


class RecordCreate(_Request):
    external_id: ExternalId | None = Field(
        default=None, description="Your own key for the record, unique within the table"
    )
    values: dict[str, CellValue] = Field(
        default_factory=dict, description="Cell values keyed by column id"
    )


class RecordUpdate(_Request):
    """A partial update: only the columns named change, and `null` clears one."""

    expected_revision: int = Field(ge=1, description="The revision the caller last read")
    values: dict[str, CellValue]


class RecordUpsert(_Request):
    """Create the record with this external id, or update it if it exists.

    `expected_revision` is required when the record already exists and ignored
    when it does not.
    """

    values: dict[str, CellValue]
    expected_revision: int | None = Field(default=None, ge=1)


class RecordRead(_Schema):
    id: UUID
    table_id: UUID
    external_id: str | None = None
    schema_version: int
    values: dict[str, Any]
    revision: int
    created_at: datetime
    updated_at: datetime | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None


class RecordFilter(_Request):
    """One condition on one column. All the filters of a query must hold."""

    column_id: UUID
    op: FilterOp
    value: FilterValue = Field(
        default=None,
        description=(
            "The operand. A list for `in`, a boolean for `is_null` (true means the cell is empty), "
            "otherwise a value of the column's type."
        ),
    )


class RecordSort(_Request):
    by: str = Field(
        default="created_at",
        description="`created_at`, `updated_at` or a column id. Ties always break on the record id.",
    )
    direction: SortDirection = "asc"


class RecordQuery(_Request):
    filters: list[RecordFilter] = Field(default_factory=list, max_length=MAX_FILTERS)
    sort: RecordSort = Field(default_factory=RecordSort)
    skip: int = Field(default=0, ge=0, le=MAX_SKIP)
    limit: int = Field(default=50, ge=1, le=MAX_LIMIT)


class RecordList(_Schema):
    """A page of records. There is no total: counting a filtered table is not cheap."""

    items: list[RecordRead]
    skip: int
    limit: int
    has_more: bool = Field(description="Whether another page follows this one")


class RecordExists(_Schema):
    exists: bool


class ErrorBody(_Schema):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(_Schema):
    """The one error shape every table route answers with, for OpenAPI clients."""

    error: ErrorBody
