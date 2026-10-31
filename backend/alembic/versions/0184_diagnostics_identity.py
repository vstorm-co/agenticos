"""Persist a deployment-scoped diagnostic identity, never account identifiers.

The seed is sealed by the existing vault. A singleton primary key makes identity
creation atomic across replicas; no migration performs network I/O or generates
keys. Downgrade removes only this diagnostic state.

Revision ID: 0184_diagnostics_identity
Revises: 0183_channel_prompt_defaults
"""

import sqlalchemy as sa

from alembic import op

revision = "0184_diagnostics_identity"
down_revision = "0183_channel_prompt_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostics_identity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sealed_seed", sa.Text(), nullable=False),
        sa.Column("secret_key_version", sa.Integer(), nullable=False),
        sa.Column("last_attempt", sa.DateTime(timezone=True)),
        sa.Column("last_success", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(16)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="singleton"),
    )


def downgrade() -> None:
    op.drop_table("diagnostics_identity")
