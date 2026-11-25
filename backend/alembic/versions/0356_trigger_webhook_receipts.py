"""Keep authenticated agent-trigger webhook identities for the trigger's lifetime.

Provider delivery headers are not covered by GitHub or generic webhook signatures,
and Redis claims expire or fail open. A small PostgreSQL receipt commits with each
queued fire instead, so changing or omitting an unsigned header cannot replay the
same privileged request. Deleting the trigger or organization cascades its receipts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0356_trigger_webhook_receipts"
down_revision: str | None = "0355_magic_link_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "agent_trigger_webhook_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signed_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trigger_id"], ["agent_triggers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trigger_id",
            "signed_digest",
            name="uq_agent_trigger_webhook_receipt_signed",
        ),
    )
    op.create_index(
        "agent_trigger_webhook_receipts_organization_id_idx",
        "agent_trigger_webhook_receipts",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "agent_trigger_webhook_receipts_organization_id_idx",
        table_name="agent_trigger_webhook_receipts",
    )
    op.drop_table("agent_trigger_webhook_receipts")
