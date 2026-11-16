"""A paid media effect survives its worker, independently of an attempt's lease.

The operation is the durable submission and storage journal. Incurred spend is
settled through the existing attempt/run ledger; a remaining reservation is not
spend. No prompt, credential value, provider URL or media bytes belong here.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkflowMediaOperation(Base, TimestampMixin):
    __tablename__ = "workflow_media_operations"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    node_run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    origin_attempt_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    collector_attempt_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    collector_token: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    submission_token: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    media_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_api: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    pricing_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB(), nullable=False)
    cost_evidence: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    # Immutable audit pins, deliberately not a cascading secret FK. Deleting or
    # rotating a key refuses collection; it cannot erase a paid operation's hold.
    secret_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    secret_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False, default="prepared")
    provider_receipt: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    effect_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set only by the canonical, explicit human retry decision. The old operation
    # and every unresolved hold remain after a replacement is authorized.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    held_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    incurred_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0), server_default="0"
    )
    booked_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0), server_default="0"
    )
    cost_source: Mapped[str | None] = mapped_column(String(24), nullable=True)
    accounting_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    held_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Allocate before the provider effect. A digest and verified metadata are
    # journaled before writing these exact bytes at this deterministic identity.
    output_file_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    output_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    stored_file_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            name="fk_media_operation_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workflow_run_id", "node_run_id"],
            ["node_runs.organization_id", "node_runs.workflow_run_id", "node_runs.id"],
            name="fk_media_operation_node",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["organization_id", "node_run_id", "origin_attempt_id"],
            ["node_attempts.organization_id", "node_attempts.node_run_id", "node_attempts.id"],
            name="fk_media_operation_origin",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["organization_id", "node_run_id", "collector_attempt_id"],
            ["node_attempts.organization_id", "node_attempts.node_run_id", "node_attempts.id"],
            name="fk_media_operation_collector",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workflow_run_id", "stored_file_id"],
            [
                "workflow_files.organization_id",
                "workflow_files.workflow_run_id",
                "workflow_files.id",
            ],
            name="fk_media_operation_output",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("organization_id", "origin_attempt_id", name="uq_media_operation_origin"),
        UniqueConstraint("organization_id", "output_file_id", name="uq_media_operation_output"),
        CheckConstraint("media_kind IN ('image', 'video')", name="ck_media_operation_kind"),
        CheckConstraint(
            "jsonb_typeof(pricing_snapshot) = 'object' "
            "AND octet_length(pricing_snapshot::text) <= 16384",
            name="ck_media_operation_pricing_snapshot",
        ),
        CheckConstraint(
            "cost_evidence IS NULL OR (jsonb_typeof(cost_evidence) = 'object' "
            "AND octet_length(cost_evidence::text) <= 4096)",
            name="ck_media_operation_cost_evidence",
        ),
        CheckConstraint(
            "(submission_token IS NULL) = (effect_started_at IS NULL)",
            name="ck_media_operation_submission_token",
        ),
        CheckConstraint(
            "phase IN ('prepared', 'submitting', 'submitted', 'collecting', 'stored', "
            "'unknown', 'failed', 'cancelled')",
            name="ck_media_operation_phase",
        ),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_media_operation_request_hash"),
        CheckConstraint(
            "output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_media_operation_output_hash",
        ),
        CheckConstraint(
            "reserved_usd > 0 AND reserved_usd <= 999999.999999 "
            "AND held_usd BETWEEN 0 AND reserved_usd "
            "AND incurred_usd BETWEEN 0 AND 999999.999999 "
            "AND booked_usd BETWEEN 0 AND incurred_usd",
            name="ck_media_operation_costs",
        ),
        CheckConstraint(
            "cost_source IS NULL OR cost_source IN ('reported', 'catalog_estimate')",
            name="ck_media_operation_cost_source",
        ),
        CheckConstraint(
            "(incurred_usd = 0 OR cost_source IS NOT NULL) "
            "AND (NOT accounting_complete OR held_usd = 0)",
            name="ck_media_operation_accounting",
        ),
        CheckConstraint(
            "reserved_bytes BETWEEN 1 AND 268435456 AND held_bytes BETWEEN 0 AND reserved_bytes",
            name="ck_media_operation_bytes",
        ),
        CheckConstraint(
            "(output_sha256 IS NULL) = (output_metadata IS NULL) "
            "AND (output_metadata IS NULL OR jsonb_typeof(output_metadata) = 'object')",
            name="ck_media_operation_output_metadata",
        ),
        CheckConstraint(
            "(phase = 'stored') = (stored_file_id IS NOT NULL) "
            "AND (stored_file_id IS NULL OR "
            "(stored_file_id = output_file_id AND output_sha256 IS NOT NULL AND held_bytes = 0))",
            name="ck_media_operation_stored_identity",
        ),
        CheckConstraint(
            "provider_receipt IS NULL OR (jsonb_typeof(provider_receipt) = 'object' "
            "AND provider_receipt ?& ARRAY['provider','api','model','kind','id'] "
            "AND provider_receipt - ARRAY['provider','api','model','kind','id'] = '{}'::jsonb "
            "AND provider_receipt->'provider' = to_jsonb(provider) "
            "AND provider_receipt->'api' = to_jsonb(provider_api) "
            "AND provider_receipt->'model' = to_jsonb(model) "
            "AND jsonb_typeof(provider_receipt->'kind') = 'string' "
            "AND provider_receipt->>'kind' IN ('job','file') "
            "AND jsonb_typeof(provider_receipt->'id') = 'string' "
            "AND length(provider_receipt->>'id') BETWEEN 1 AND 1024)",
            name="ck_media_operation_receipt",
        ),
        CheckConstraint(
            "(phase <> 'submitted' OR provider_receipt IS NOT NULL) "
            "AND (provider_receipt IS NULL OR "
            "(media_kind = 'video' AND submitted_at IS NOT NULL AND effect_started_at IS NOT NULL))",
            name="ck_media_operation_submission",
        ),
        Index(
            "uq_media_operation_current",
            "organization_id",
            "node_run_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_media_operation_run", "organization_id", "workflow_run_id"),
        Index("ix_media_operation_node", "node_run_id"),
        Index("ix_media_operation_origin", "origin_attempt_id"),
        Index("ix_media_operation_collector", "collector_attempt_id"),
        Index("ix_media_operation_file", "stored_file_id"),
        Index(
            "ix_media_operation_unresolved",
            "organization_id",
            "workflow_run_id",
            postgresql_where=text("held_usd > 0 OR held_bytes > 0 OR incurred_usd > booked_usd"),
        ),
    )

    def __repr__(self) -> str:
        return f"<WorkflowMediaOperation(id={self.id}, phase={self.phase})>"
