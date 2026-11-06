"""phone_cases

Revision ID: 0280_phone_cases
Revises: 0279_telephony
Create Date: 2026-11-04 14:32:14.794389

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0280_phone_cases"
down_revision: str | None = "0279_telephony"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("phone_calls_agent_id_fkey"), "phone_calls", type_="foreignkey")
    op.create_foreign_key(
        op.f("phone_calls_agent_id_fkey"),
        "phone_calls",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "outcomes", sa.Column("phone_attempted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("phone_calls", sa.Column("outcome_id", sa.UUID(), nullable=True))
    op.add_column(
        "phone_calls",
        sa.Column("purpose", sa.String(length=16), server_default="direct", nullable=False),
    )
    op.add_column("phone_calls", sa.Column("importance_reason", sa.Text(), nullable=True))
    op.add_column("phone_calls", sa.Column("not_before", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("phone_calls_outcome_id_idx"), "phone_calls", ["outcome_id"], unique=False)
    op.create_foreign_key(
        op.f("phone_calls_outcome_id_fkey"),
        "phone_calls",
        "outcomes",
        ["outcome_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "phone_contacts",
        sa.Column(
            "agent_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "phone_contacts",
        sa.Column("allow_important", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "phone_contacts",
        sa.Column("importance_instructions", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "phone_contacts",
        sa.Column("escalation_delay_seconds", sa.Integer(), server_default="0", nullable=False),
    )

    for table, column in (
        ("phone_calls", "purpose"),
        ("phone_contacts", "agent_ids"),
        ("phone_contacts", "allow_important"),
        ("phone_contacts", "importance_instructions"),
        ("phone_contacts", "escalation_delay_seconds"),
    ):
        op.alter_column(table, column, server_default=None)


def downgrade() -> None:
    op.drop_constraint(op.f("phone_calls_agent_id_fkey"), "phone_calls", type_="foreignkey")
    op.create_foreign_key(
        op.f("phone_calls_agent_id_fkey"),
        "phone_calls",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("outcomes", "phone_attempted_at")
    op.drop_column("phone_contacts", "escalation_delay_seconds")
    op.drop_column("phone_contacts", "importance_instructions")
    op.drop_column("phone_contacts", "allow_important")
    op.drop_column("phone_contacts", "agent_ids")
    op.drop_constraint(op.f("phone_calls_outcome_id_fkey"), "phone_calls", type_="foreignkey")
    op.drop_index(op.f("phone_calls_outcome_id_idx"), table_name="phone_calls")
    op.drop_column("phone_calls", "not_before")
    op.drop_column("phone_calls", "importance_reason")
    op.drop_column("phone_calls", "purpose")
    op.drop_column("phone_calls", "outcome_id")
