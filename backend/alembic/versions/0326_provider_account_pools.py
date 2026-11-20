"""Allow explicitly selected personal coding accounts and opt-in pools.

Revision ID: 0326_provider_account_pools
Revises: 0325_merge_t3_rooms_v173
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0326_provider_account_pools"
down_revision: str | Sequence[str] | None = "0325_merge_t3_rooms_v173"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "coding_accounts",
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "coding_accounts",
        sa.Column("pool_member", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "coding_accounts",
        sa.Column("provider_identity_fingerprint", sa.String(length=64), nullable=True),
    )
    op.execute(sa.text("UPDATE coding_accounts SET is_default = true"))
    op.alter_column("coding_accounts", "is_default", server_default=None)
    op.alter_column("coding_accounts", "pool_member", server_default=None)
    op.drop_constraint(
        "coding_accounts_organization_id_key",
        "coding_accounts",
        type_="unique",
    )
    op.create_check_constraint(
        "ck_coding_account_pool",
        "coding_accounts",
        "pool_member IS FALSE OR (harness = 'codex' AND provider_identity_fingerprint IS NOT NULL)",
    )
    op.create_index(
        "coding_accounts_default_idx",
        "coding_accounts",
        ["organization_id", "user_id", "harness"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index(
        "coding_accounts_identity_idx",
        "coding_accounts",
        ["organization_id", "user_id", "harness", "provider_identity_fingerprint"],
        unique=True,
        postgresql_where=sa.text("provider_identity_fingerprint IS NOT NULL"),
    )


def downgrade() -> None:
    duplicate_accounts = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS ("
                "SELECT 1 FROM coding_accounts "
                "GROUP BY organization_id, user_id, harness HAVING count(*) > 1"
                ")"
            )
        )
        .scalar_one()
    )
    if duplicate_accounts:
        raise RuntimeError("Cannot downgrade while multiple coding accounts exist")

    op.drop_index("coding_accounts_identity_idx", table_name="coding_accounts")
    op.drop_index("coding_accounts_default_idx", table_name="coding_accounts")
    op.drop_constraint("ck_coding_account_pool", "coding_accounts", type_="check")
    op.create_unique_constraint(
        "coding_accounts_organization_id_key",
        "coding_accounts",
        ["organization_id", "user_id", "harness"],
    )
    op.drop_column("coding_accounts", "provider_identity_fingerprint")
    op.drop_column("coding_accounts", "pool_member")
    op.drop_column("coding_accounts", "is_default")
