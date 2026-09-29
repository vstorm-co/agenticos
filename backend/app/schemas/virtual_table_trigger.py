"""Table trigger schemas - the workflows a table runs when a record is added (#1785)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.models.virtual_table_trigger import AdmissionStatus
from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.virtual_table import RecordFilter

MAX_FILTERS = 20
MAX_MAPPING_KEYS = 50


class TableTriggerCreate(BaseSchema):
    """A trigger on the table in the path, running the workflow's live version as you.

    Every filter must hold on the record as it was created. Each `input_mapping`
    key becomes a key of the run's `payload`, taking a column's value (by column
    id), the record's author (`@author`) or the record's own id (`@record_id`).
    """

    workflow_id: UUID
    name: str | None = Field(default=None, max_length=120)
    filters: list[RecordFilter] = Field(default_factory=list, max_length=MAX_FILTERS)
    input_mapping: dict[str, str] = Field(default_factory=dict, max_length=MAX_MAPPING_KEYS)


class TableTriggerUpdate(BaseSchema):
    """Rename, switch on or off, re-filter, re-map, or move to the live version.

    The trigger runs as you from then on.
    """

    name: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    filters: list[RecordFilter] | None = Field(default=None, max_length=MAX_FILTERS)
    input_mapping: dict[str, str] | None = Field(default=None, max_length=MAX_MAPPING_KEYS)
    pin_current_version: bool = False


class TableTriggerRead(BaseSchema, TimestampSchema):
    id: UUID
    table_id: UUID
    workflow_id: UUID
    workflow_name: str
    workflow_version_id: UUID
    version_number: int
    name: str | None
    revision: int
    filters: list[RecordFilter]
    input_mapping: dict[str, str]
    execution_principal_user_id: UUID | None
    is_active: bool
    activated_at: datetime | None


class TableTriggerList(BaseSchema):
    items: list[TableTriggerRead]


class TableTriggerAdmissionRead(BaseSchema):
    """What one trigger decided about one added record - never the record's data."""

    id: UUID
    trigger_revision: int
    status: AdmissionStatus
    reason: str | None
    workflow_run_id: UUID | None
    created_at: datetime


class TableTriggerAdmissionList(BaseSchema):
    items: list[TableTriggerAdmissionRead]
    total: int
