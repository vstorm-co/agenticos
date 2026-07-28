"""Record which provider and which stored key each run spent on

Revision ID: 0050_run_provider
Revises: 0049_agent_embeds
Create Date: 2026-07-28

A run recorded `model_label`, which is a display name somebody chose - "GPT-4.1
(prod)". Two questions a bill arrives with could therefore not be answered at
all: what did we spend at OpenAI versus Anthropic, and which key is costing the
most. Both are now columns.

Recorded on the run rather than joined through the model profile it used,
because a profile is a *pointer*: repointing it at a different provider or
rotating its key would silently rewrite what last month's runs appear to have
spent. A run's own history has to stay what happened.

`credential_id` is SET NULL rather than CASCADE for the same reason
`exposure_id` is: deleting a key must not delete the record of what it spent.

Existing rows keep NULL in both. Backfilling from the profile would be exactly
the rewrite this column exists to prevent - a profile pointing somewhere else
today would attribute old spend to a provider that never served it. Reports read
NULL as "before this was recorded" and say so.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0050_run_provider"
down_revision = "0049_agent_embeds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "agent_runs_credential_id_fkey",
        "agent_runs",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_runs_provider", "agent_runs", ["provider"])
    # The shape every cost query has: one organization, one window, grouped by
    # where the money went.
    op.create_index(
        "ix_agent_runs_org_started_provider",
        "agent_runs",
        ["organization_id", "started_at", "provider"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_org_started_provider", table_name="agent_runs")
    op.drop_index("ix_agent_runs_provider", table_name="agent_runs")
    op.drop_constraint("agent_runs_credential_id_fkey", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "credential_id")
    op.drop_column("agent_runs", "provider")
