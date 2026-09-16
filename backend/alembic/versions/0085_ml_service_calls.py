"""The usage record behind the standalone ML service API.

A caller who parses a document, recognises a scan or scans text for personal
data without starting an agent run appears in none of the platform's existing
ledgers - `agent_runs` and `ingestion_spend` both record work done inside the
product. FA-069 asks these services to carry tenant context, logging and usage
reporting, so each call leaves a row here: the service, the organization, how
much went in, how long it took, and how it ended. No content is stored (#1595).

Revision ID: 0085_ml_service_calls
Revises: 0080_audit_checkpoints
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0085_ml_service_calls"
down_revision: str | None = "0080_audit_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ml_service_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failure_stage", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.String(length=512), nullable=True),
        sa.Column("input_bytes", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('succeeded', 'failed')", name="ck_ml_service_calls_status"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="ml_service_calls_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="ml_service_calls_requested_by_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="ml_service_calls_pkey"),
    )
    op.create_index(
        "ix_ml_service_calls_org_created",
        "ml_service_calls",
        ["organization_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ml_service_calls_org_created", table_name="ml_service_calls")
    op.drop_table("ml_service_calls")
