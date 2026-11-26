"""Remember when an attempt only delivers an earlier result.

Older attempts have no durable evidence that the handler could not run. Leave
their marker false so that an interrupted external write is never guessed safe.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0365_attempt_receipt_only"
down_revision: str = "0370_console_role_presentation"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "node_attempts",
        sa.Column("receipt_only", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("node_attempts", "receipt_only")
