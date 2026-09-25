"""Virtual Tables - typed records an organization keeps for its agents and workflows.

A virtual table is *metadata plus JSONB*, not a physical SQL table. The
alternative - one `CREATE TABLE` per user-defined table - would put DDL on the
request path, hand tenants a way to grow the catalog without bound, and make a
column rename a migration. Here the shape of a table lives in
`virtual_table_schema_versions` and its rows live in `virtual_table_records`, so
the physical schema never changes and every query is scoped by
`organization_id` and `table_id`.

Four rules shape the rest of this module:

- **Stable identifiers.** A table, a column and a select option each have an id
  that survives a rename. Record values are keyed by *column id*, so renaming a
  column rewrites one schema version and no records.
- **Schema versions are immutable snapshots.** A schema change appends version N+1
  and never edits N. A record remembers the version it was last written under, so
  what a record meant when it was written stays answerable. A column is
  archived, never deleted: its values stay readable, and writing to it is refused.
- **A record has a revision.** Every change increments it, and an update or a
  delete must name the revision it saw, so two people editing one record cannot
  silently overwrite each other.
- **The history outlives the row.** `virtual_table_record_history` keeps no
  foreign key to a record, because a hard delete must not delete the trail of it.

The idempotency receipts and the created-event outbox are written in the same
transaction as the change they describe - see `app/services/virtual_tables/`.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class VirtualTable(Base, TimestampMixin):
    """One table: a name, an owner, a visibility, and a pointer to its schema version."""

    __tablename__ = "virtual_tables"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Archiving keeps the rows and the history readable and refuses writes. A
    # table is never dropped: a workflow or a view may still name it.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Not a second key: it is what the composite foreign keys of the records,
        # history and outbox point at, so a child row cannot name a table from
        # another organization than its own `organization_id`.
        UniqueConstraint("organization_id", "id", name="uq_virtual_table_org_id"),
        # Unique among live tables only, so an archived table's name can be reused.
        Index(
            "uq_virtual_table_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="visibility"),
        CheckConstraint("schema_version >= 1", name="schema_version"),
    )

    def __repr__(self) -> str:
        return f"<VirtualTable(org={self.organization_id}, name={self.name})>"


class VirtualTableSchemaVersion(Base):
    """One immutable snapshot of a table's columns."""

    __tablename__ = "virtual_table_schema_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("virtual_tables.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # A list of column definitions, ordered as the table shows them. Validated by
    # `app.schemas.virtual_table.ColumnDef` on the way in and out; the column
    # type registry decides what a value of each type may be.
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("table_id", "version", name="uq_virtual_table_schema_version"),
        CheckConstraint("version >= 1", name="version"),
    )

    def __repr__(self) -> str:
        return f"<VirtualTableSchemaVersion(table={self.table_id}, version={self.version})>"


class VirtualTableRecord(Base, TimestampMixin):
    """One record: values keyed by column id, a revision, and an optional external id."""

    __tablename__ = "virtual_table_records"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # The caller's own key for the record - an order number, a file name. Unique
    # per table when set, which is what lets an upsert find "the same record".
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            ondelete="CASCADE",
            name="virtual_table_records_org_table_fkey",
        ),
        Index(
            "uq_virtual_table_record_external_id",
            "table_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        # The default order of a listing, so a page is an index range scan.
        Index("virtual_table_records_table_created_idx", "table_id", "created_at", "id"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint("schema_version >= 1", name="schema_version"),
    )

    def __repr__(self) -> str:
        return f"<VirtualTableRecord(table={self.table_id}, id={self.id}, rev={self.revision})>"


class VirtualTableRecordHistory(Base):
    """One change to a record: what it was, what it became, and who did it.

    `record_id` is deliberately not a foreign key: a hard delete removes the row
    and must leave this behind.
    """

    __tablename__ = "virtual_table_record_history"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            ondelete="CASCADE",
            name="virtual_table_record_history_org_table_fkey",
        ),
        Index("virtual_table_record_history_record_idx", "record_id", "revision"),
        CheckConstraint(
            "operation IN ('create', 'update', 'delete')",
            name="operation",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<VirtualTableRecordHistory(record={self.record_id}, rev={self.revision}, "
            f"op={self.operation})>"
        )


class VirtualTableReceipt(Base):
    """The stored outcome of a keyed write, so a retry returns it instead of writing again.

    Scoped to the organization, the principal and the operation: two callers
    that pick the same key, or one caller using it for two operations, never
    meet. `payload_hash` is what makes a reused key with a changed body a
    refusal rather than a silent replay of the old answer.
    """

    __tablename__ = "virtual_table_receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "principal_id",
            "operation",
            "operation_key",
            name="uq_virtual_table_receipt_key",
        ),
        CheckConstraint(
            "operation IN ('record.create', 'record.update', 'record.delete', 'record.upsert')",
            name="operation",
        ),
    )

    def __repr__(self) -> str:
        return f"<VirtualTableReceipt(op={self.operation}, key={self.operation_key})>"


class VirtualTableOutbox(Base):
    """An event written with the change that caused it, for a worker to deliver.

    Only `table.record.created` exists so far. A row here means the record
    committed; a consumer claims undelivered rows in its own session and marks
    `dispatched_at` when it has handed them on.
    """

    __tablename__ = "virtual_table_outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            ondelete="CASCADE",
            name="virtual_table_outbox_org_table_fkey",
        ),
        Index(
            "virtual_table_outbox_pending_idx",
            "created_at",
            postgresql_where=text("dispatched_at IS NULL"),
        ),
        CheckConstraint("event_type IN ('table.record.created')", name="event_type"),
    )

    def __repr__(self) -> str:
        return f"<VirtualTableOutbox(event={self.event_type}, record={self.record_id})>"
