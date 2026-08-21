"""The target an auto-registered webhook points at, kept so delete can deregister it

Revision ID: 0049_trigger_webhook_target
Revises: 0048_portal_triggers
Create Date: 2026-08-17

A provider webhook id is not enough to remove the hook: GitHub deletes a hook by
`(repository, id)`, with no delete-by-id-alone, so the target the hook was
registered against has to be remembered. Additive and nullable - null on every
schedule and every manual or raw event trigger.
"""

import sqlalchemy as sa

from alembic import op

revision = "0049_trigger_webhook_target"
down_revision = "0048_portal_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers", sa.Column("provider_target", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_triggers", "provider_target")
