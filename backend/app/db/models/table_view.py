"""A saved view over a table's records: a filter/sort/grouping a person kept.

Deliberately not a shareable resource in its own right - it has no `ResourceType`,
no grant subject and no visibility beyond "private" or "shared with whoever can
already see the table". A view that outlived or leaked across a table it no
longer belongs to would be a saved filter over rows the viewer was never meant to
read, which is why `table_id` and `organization_id` are both stored (the same
reasoning `docs/virtual-tables.md#who-can-do-what` gives for records) rather than
relying on a join back through `virtual_tables` alone.
"""

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TableView(Base, TimestampMixin):
    """One saved table/kanban/list view, scoped to one table and owned by one member."""

    __tablename__ = "table_views"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    # `TableViewConfig`: filters, sort, visible_columns, group_by - a `RecordQuery`
    # plus the two console-only fields. See `app/schemas/table_view.py`.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        # Composite FK to `virtual_tables`' own `(organization_id, id)` unique key, the
        # same pattern `VirtualTableRecord` uses: a view naming a table from another
        # organization than its own `organization_id` is a constraint violation, not a
        # cross-tenant row a missed `WHERE` could ever return.
        ForeignKeyConstraint(
            ["organization_id", "table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="table_views_org_table_fkey",
            ondelete="CASCADE",
        ),
        # One member cannot save two views of the same name under one table - matches
        # how a live table's own name is unique per organization.
        UniqueConstraint("table_id", "owner_user_id", "name", name="uq_table_view_owner_name"),
        CheckConstraint("kind IN ('table', 'kanban', 'list')", name="kind"),
        CheckConstraint("visibility IN ('private', 'shared')", name="visibility"),
    )

    def __repr__(self) -> str:
        return f"<TableView(table={self.table_id}, name={self.name}, kind={self.kind})>"
