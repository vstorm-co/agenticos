"""Remote sandboxes still to be destroyed after their rows were deleted (#2209).

Deleting a conversation or a project destroys its remote sandboxes after the
deletion commits, and the workspace rows that named them go in the same
transaction. A destroy that failed left nothing that knew the sandbox existed -
for Daytona, a sandbox the organization paid for until somebody noticed. A row
here is written with the deletion, removed once the provider confirms the
destroy, and retried by the worker's `sandbox-destroy-retry` sweep until then.

`next_attempt_at` is indexed because the sweep asks "which are due" every
minute; the foreign keys are indexed because both cascade. `created_at` and
`updated_at` are the `TimestampMixin` pair every model carries.

Revision ID: 0144_pending_sandbox_destroys
Revises: 0143_pg_stat_statements
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0144_pending_sandbox_destroys"
down_revision: str | None = "0143_pg_stat_statements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_sandbox_destroys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ref_id", sa.String(length=255), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("pending_sandbox_destroys_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["sandbox_connections.id"],
            name=op.f("pending_sandbox_destroys_connection_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pending_sandbox_destroys_pkey")),
    )
    op.create_index(
        op.f("pending_sandbox_destroys_organization_id_idx"),
        "pending_sandbox_destroys",
        ["organization_id"],
    )
    op.create_index(
        op.f("pending_sandbox_destroys_connection_id_idx"),
        "pending_sandbox_destroys",
        ["connection_id"],
    )
    op.create_index(
        op.f("pending_sandbox_destroys_next_attempt_at_idx"),
        "pending_sandbox_destroys",
        ["next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("pending_sandbox_destroys_next_attempt_at_idx"), table_name="pending_sandbox_destroys"
    )
    op.drop_index(
        op.f("pending_sandbox_destroys_connection_id_idx"), table_name="pending_sandbox_destroys"
    )
    op.drop_index(
        op.f("pending_sandbox_destroys_organization_id_idx"), table_name="pending_sandbox_destroys"
    )
    op.drop_table("pending_sandbox_destroys")
