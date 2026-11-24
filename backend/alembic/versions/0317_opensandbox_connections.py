"""OpenSandbox connection images and optional Kubernetes secure access."""

import sqlalchemy as sa

from alembic import op

revision: str = "0317_opensandbox_connections"
down_revision: str = "0316_trigger_attempts"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.alter_column(
        "sandbox_connections",
        "default_runtime",
        type_=sa.String(512),
        existing_type=sa.String(64),
        existing_nullable=True,
    )
    op.add_column(
        "sandbox_connections",
        sa.Column("secure_access", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    connection = op.get_bind()
    unsupported = connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM sandbox_connections WHERE kind = 'opensandbox' OR length(default_runtime) > 64)"
        )
    )
    if unsupported:
        raise RuntimeError(
            "Remove OpenSandbox connections and shorten runtime names to 64 characters before downgrading"
        )
    op.alter_column(
        "sandbox_connections",
        "default_runtime",
        type_=sa.String(64),
        existing_type=sa.String(512),
        existing_nullable=True,
    )
    op.drop_column("sandbox_connections", "secure_access")
