"""Table trigger schemas - the workflows a table runs when a record is added (#1785)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.db.models.virtual_table_trigger import AdmissionStatus
from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.virtual_table import RecordFilter

MAX_FILTERS = 20


class TableTriggerUpdate(BaseSchema):
    """Pause or resume a trigger. Its table, filters and version are its workflow's
    trigger node, which a publish switches on; it keeps running as the publisher."""

    is_active: bool


class TableTriggerRead(BaseSchema, TimestampSchema):
    id: UUID
    table_id: UUID
    workflow_id: UUID
    workflow_name: str
    workflow_version_id: UUID
    version_number: int
    node_instance_id: UUID
    revision: int
    filters: list[RecordFilter]
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
