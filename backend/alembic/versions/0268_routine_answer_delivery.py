"""Keep resumed final answers and their retryable handoffs in the terminal transaction.

A primary-key receipt makes console delivery idempotent across worker restarts.
Existing runs are not replayed or assigned a guessed delivery history.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0268_routine_answer_delivery"
down_revision: str | None = "0267_routine_action_consents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "routine_deliveries",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("trigger_id", sa.UUID(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'unavailable', 'run_log', 'no_answer')",
            name=op.f("routine_deliveries_ck_routine_delivery_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("routine_deliveries_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("routine_deliveries_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("routine_deliveries_owner_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("routine_deliveries_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("routine_deliveries_pkey")),
    )
    op.create_index(
        op.f("routine_deliveries_organization_id_idx"),
        "routine_deliveries",
        ["organization_id"],
        unique=False,
    )

    op.create_index(
        op.f("routine_deliveries_owner_user_id_idx"),
        "routine_deliveries",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("routine_deliveries_organization_id_idx"), table_name="routine_deliveries")
    op.drop_index(op.f("routine_deliveries_owner_user_id_idx"), table_name="routine_deliveries")
    op.drop_table("routine_deliveries")
