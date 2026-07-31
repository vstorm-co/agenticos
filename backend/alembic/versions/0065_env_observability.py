"""An environment can point its traces at its own Logfire project

Revision ID: 0065_env_observability
Revises: 0064_slack_creds_per_bot
Create Date: 2026-07-30

The spec's observability block carries a free-text `environment` tag, which is
exactly the thing agent environments made structural: production traces belong
in the client's project, dev noise in the operator's. An environment can now
carry its own write-token reference and service name; the Logfire environment
tag is always the environment's `name`, so the tag and the environment cannot
disagree. NULLs fall through to the spec's block, so nothing changes for an
agent that never opens this.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0065_env_observability"
down_revision = "0064_slack_creds_per_bot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_environments",
        sa.Column(
            "logfire_token_secret_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organization_secrets.id",
                ondelete="SET NULL",
                name="agent_environments_logfire_token_secret_id_fkey",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_environments",
        sa.Column("service_name", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_environments", "service_name")
    op.drop_column("agent_environments", "logfire_token_secret_id")
