"""Track agreement on a claim independently of the Gmail event it first depended on."""

import sqlalchemy as sa

from alembic import op

revision: str = "0366_memory_source_agreement"
down_revision: str = "0365_memory_objects_and_history"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("memory_mail_sources", sa.Column("object_key", sa.String(260)))
    op.add_column("memory_claims", sa.Column("observation_source", sa.String(260)))
    op.add_column("memory_mail_events", sa.Column("observation_source", sa.String(260)))
    op.add_column("memory_mail_events", sa.Column("claim_statement", sa.Text()))
    op.add_column("memory_mail_events", sa.Column("supported_claim_id", sa.Uuid()))
    op.create_foreign_key(
        "memory_mail_events_supported_claim_id_fkey",
        "memory_mail_events",
        "memory_claims",
        ["supported_claim_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "memory_mail_events_supported_claim_id_idx", "memory_mail_events", ["supported_claim_id"]
    )


def downgrade() -> None:
    op.drop_index("memory_mail_events_supported_claim_id_idx", table_name="memory_mail_events")
    op.drop_constraint(
        "memory_mail_events_supported_claim_id_fkey", "memory_mail_events", type_="foreignkey"
    )
    op.drop_column("memory_mail_events", "supported_claim_id")
    op.drop_column("memory_mail_events", "claim_statement")
    op.drop_column("memory_mail_events", "observation_source")
    op.drop_column("memory_claims", "observation_source")
    op.drop_column("memory_mail_sources", "object_key")
