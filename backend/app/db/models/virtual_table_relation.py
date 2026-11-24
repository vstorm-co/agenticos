"""Constrained links between virtual records, with retained migration evidence.

The source field ID remains the relationship's identity. Reverse traversal reads
the same edges; it never maintains a second editable list. Composite references
bind both endpoints to the organization and tables declared by the relationship.
"""

import uuid

from pydantic import JsonValue
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class VirtualTableRelation(Base, TimestampMixin):
    """A link field's stable definition, retained while the field is archived."""

    __tablename__ = "virtual_table_relations"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    column_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    target_table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_links: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "source_table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="virtual_table_relations_source_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "target_table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="virtual_table_relations_target_fkey",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "source_table_id",
            "column_id",
            "target_table_id",
            "max_links",
            name="uq_virtual_table_relation_target",
        ),
        CheckConstraint("max_links BETWEEN 1 AND 100", name="max_links"),
        Index("virtual_table_relations_target_idx", "organization_id", "target_table_id"),
    )

    def __repr__(self) -> str:
        return f"<VirtualTableRelation(table={self.source_table_id}, column={self.column_id})>"


class VirtualTableRecordLink(Base, TimestampMixin):
    """One ordered connection, constrained against the definition and both records."""

    __tablename__ = "virtual_table_record_links"

    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    column_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_record_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    target_table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    target_record_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    max_links: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "source_table_id", "column_id", "target_table_id", "max_links"],
            [
                "virtual_table_relations.organization_id",
                "virtual_table_relations.source_table_id",
                "virtual_table_relations.column_id",
                "virtual_table_relations.target_table_id",
                "virtual_table_relations.max_links",
            ],
            name="virtual_table_record_links_relation_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "source_table_id", "source_record_id"],
            [
                "virtual_table_records.organization_id",
                "virtual_table_records.table_id",
                "virtual_table_records.id",
            ],
            name="virtual_table_record_links_source_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "target_table_id", "target_record_id"],
            [
                "virtual_table_records.organization_id",
                "virtual_table_records.table_id",
                "virtual_table_records.id",
            ],
            name="virtual_table_record_links_target_fkey",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "source_table_id",
            "column_id",
            "source_record_id",
            "position",
            name="uq_virtual_table_link_position",
        ),
        CheckConstraint("position >= 0 AND position < max_links", name="position"),
        Index(
            "virtual_table_record_links_target_idx",
            "organization_id",
            "target_table_id",
            "target_record_id",
            "source_table_id",
            "column_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<VirtualTableRecordLink(source={self.source_record_id}, column={self.column_id})>"


class VirtualTableLinkEvidence(Base, TimestampMixin):
    """An unresolvable stored link kept for repair, never exposed as a live edge.

    Source-record and destination identifiers deliberately have no record foreign
    key: deleting a record must not delete evidence of what was stored before the
    relationship backfill. Deleting its organization or table still removes it.
    """

    __tablename__ = "virtual_table_link_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_table_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    column_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[JsonValue] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "source_table_id"],
            ["virtual_tables.organization_id", "virtual_tables.id"],
            name="virtual_table_link_evidence_table_fkey",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "source_table_id",
            "source_record_id",
            "column_id",
            "source_revision",
            "position",
            name="uq_virtual_table_link_evidence_position",
        ),
        CheckConstraint("source_revision >= 1", name="source_revision"),
        CheckConstraint("position >= -1", name="position"),
        CheckConstraint(
            "reason IN ('invalid_cell', 'invalid_id', 'missing_target', 'duplicate_target', 'limit_exceeded')",
            name="reason",
        ),
    )

    def __repr__(self) -> str:
        return f"<VirtualTableLinkEvidence(source={self.source_record_id}, reason={self.reason})>"
