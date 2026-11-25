"""Journal resumable, private portable-resource transfers.

A transfer records its owner, immutable request identity, selected data, worker
fence and staged object paths so retries do not repeat committed creates and
abandoned uploads can expire. Credentials are never transfer payloads. Nullable owner references preserve the
cleanup journal after account deletion until its private storage prefix expires.
The
requesting API-key UUID deliberately has no nulling foreign key: deleting a key
must refuse the queued request rather than promote it to session authority.

Revision ID: 0367_portability_operations
Revises: 0366_shared_mcp_oauth_clients
Create Date: 2026-11-24 23:38:14.281657

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0367_portability_operations"
down_revision: str | None = "0366_shared_mcp_oauth_clients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portability_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("worker_attempt", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("choices", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_bytes", sa.BigInteger(), nullable=False),
        sa.Column("output_path", sa.String(length=1024), nullable=True),
        sa.Column("completed_bytes", sa.BigInteger(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "direction IN ('export', 'import')", name=op.f("portability_operations_direction_check")
        ),
        sa.CheckConstraint(
            "phase IN ('prepare', 'apply')", name=op.f("portability_operations_phase_check")
        ),
        sa.CheckConstraint(
            "status != 'ready' OR ((direction = 'export' AND output_path IS NOT NULL) OR (direction = 'import' AND result IS NOT NULL))",
            name=op.f("portability_operations_ready_result_check"),
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_upload', 'queued', 'running', 'review', 'needs_bindings', 'ready', 'failed', 'expired')",
            name=op.f("portability_operations_status_check"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('review', 'needs_bindings', 'ready') OR manifest IS NOT NULL",
            name=op.f("portability_operations_review_manifest_check"),
        ),
        sa.CheckConstraint(
            "completed_bytes >= 0 AND total_bytes >= completed_bytes",
            name=op.f("portability_operations_progress_check"),
        ),
        sa.CheckConstraint(
            "revision >= 1 AND worker_attempt >= 0",
            name=op.f("portability_operations_revision_check"),
        ),
        sa.CheckConstraint(
            "source_bytes >= 0", name=op.f("portability_operations_source_bytes_check")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["background_jobs.id"],
            name=op.f("portability_operations_job_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("portability_operations_organization_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("portability_operations_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request) = 'object' "
            "AND (manifest IS NULL OR jsonb_typeof(manifest) = 'object') "
            "AND (choices IS NULL OR jsonb_typeof(choices) = 'object') "
            "AND (result IS NULL OR jsonb_typeof(result) = 'object')",
            name=op.f("portability_operations_payload_objects_check"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("portability_operations_pkey")),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "request_id",
            name=op.f("portability_operations_organization_id_key"),
        ),
    )
    op.create_index(
        "portability_operations_expiry_idx",
        "portability_operations",
        ["expires_at", "id"],
        unique=False,
    )
    op.create_index(
        "portability_operations_owner_created_idx",
        "portability_operations",
        ["organization_id", "user_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("portability_operations_owner_created_idx", table_name="portability_operations")
    op.drop_index("portability_operations_expiry_idx", table_name="portability_operations")
    op.drop_table("portability_operations")
