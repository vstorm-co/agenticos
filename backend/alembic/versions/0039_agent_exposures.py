"""Agent exposures: where an agent is available, stated rather than assumed

Revision ID: 0039_exposures
Revises: 0038_vault
Create Date: 2026-07-27

`@slug` in a Slack or Telegram channel resolved against every published agent
in the bot's organization. One bot was therefore a door onto all of them, and
nobody decided that - it fell out of resolving a handle against the org instead
of against the bot. This table is the decision: an agent answers through a bot
when a row here says so.

**Nothing is backfilled, and that is the point.** Writing an exposure per
(bot x published agent) would preserve the hole and, worse, an upgrade would
create bindings no admin ever reviewed. For a change whose whole purpose is that
reach becomes explicit, the safe default is closed. Confirmed acceptable: this
is pre-release and self-hosted. The cost is that a bot stops answering handles
until they are bound, which the bot now says out loud rather than leaving
someone to find in a changelog.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0039_exposures"
down_revision = "0038_vault"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_exposures",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(16), nullable=False),
        sa.Column(
            "channel_bot_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("channel_bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # A second binding for the same pair would make "is this agent available
        # here" a question with two answers, and revoking would remove one.
        sa.UniqueConstraint("agent_id", "channel_bot_id", name="uq_exposure_agent_bot"),
        sa.CheckConstraint("surface IN ('slack', 'telegram')", name="ck_exposure_surface"),
    )
    op.create_index("ix_agent_exposures_organization_id", "agent_exposures", ["organization_id"])
    op.create_index("ix_agent_exposures_agent_id", "agent_exposures", ["agent_id"])
    op.create_index("ix_agent_exposures_channel_bot_id", "agent_exposures", ["channel_bot_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_exposures_channel_bot_id", table_name="agent_exposures")
    op.drop_index("ix_agent_exposures_agent_id", table_name="agent_exposures")
    op.drop_index("ix_agent_exposures_organization_id", table_name="agent_exposures")
    op.drop_table("agent_exposures")
