"""Bind internal MCP reporting credentials to their exact agent run.

No foreign key: the runner mints the credential in a committed short session
before its run row is committed. Reporting refuses absent or terminal runs.
Existing credentials have no reporting authority. No credential is exposed.
"""

import sqlalchemy as sa

from alembic import op

revision = "0350_run_reporting_credential"
down_revision = "0349_personal_work_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("source_run_id", sa.UUID(), nullable=True))
    op.add_column("agent_triggers", sa.Column("action_mode", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_trigger_action_mode",
        "agent_triggers",
        "action_mode IS NULL OR action_mode IN ('agent', 'manual', 'per_tool')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_action_mode", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "action_mode")
    op.drop_column("api_keys", "source_run_id")
