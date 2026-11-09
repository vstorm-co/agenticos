"""Choose reports or deduplicated Inbox cases without changing existing routines.

Revision ID: 0286_routine_inbox_results
Revises: 0285_member_proactivity
"""

import sqlalchemy as sa

from alembic import op

revision = "0286_routine_inbox_results"
down_revision = "0285_member_proactivity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("result_mode", sa.String(16), nullable=False, server_default="report"),
    )
    op.create_table(
        "routine_finding_revisions",
        sa.Column(
            "finding_id",
            sa.UUID(),
            sa.ForeignKey("suggestions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision_hash", sa.String(64), primary_key=True),
    )
    op.create_check_constraint(
        "ck_trigger_result_mode", "agent_triggers", "result_mode IN ('report', 'inbox')"
    )


def downgrade() -> None:
    op.drop_table("routine_finding_revisions")
    op.drop_constraint("ck_trigger_result_mode", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "result_mode")
