"""Portal lineage on a trigger, and the scope an account consented to

Revision ID: 0045_portal_triggers
Revises: 0044_agent_trigger_name
Create Date: 2026-08-17

The setup layer for trigger portals - an event trigger built from a preset,
whose webhook the platform registered at the provider through a connected
account instead of the user pasting a URL. All additive and nullable, so every
existing trigger (and every hand-wired event trigger) is unchanged: the columns
only carry the portal lineage and the provider-side registration.

`agent_triggers` gains:
- `connection_id` - the `mcp_connections` row whose OAuth token registered the
  webhook, and which (being an MCP connection) also backs the agent's tools. SET
  NULL so disconnecting the account leaves the trigger firing on the hook that
  already exists rather than deleting it.
- `provider_webhook_id` - the hook id the provider returned, so a delete can
  deregister it.
- `delivery_mode` - `auto_webhook` (platform registered it) or `manual` (pasted).
- `portal_key` - which portal's preset created it.
- `ck_trigger_registered_hook_has_connection` - a registered hook must name the
  account that owns it, or a delete has no token to deregister with.

`mcp_connections` gains `granted_scopes` - the scopes an account consented to
when authorized for more than tool-reading. NULL on every existing row and read
only by the webhook-registration path, so the tool path is untouched.

If `0040` collides at merge with the stacked #589 (`0040_trigger_fire_in_flight`),
one is renumbered onto the other's head, as the earlier trigger merges were.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0045_portal_triggers"
down_revision = "0044_agent_trigger_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("granted_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "agent_triggers",
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("agent_triggers", sa.Column("delivery_mode", sa.String(length=16), nullable=True))
    op.add_column(
        "agent_triggers", sa.Column("provider_webhook_id", sa.String(length=255), nullable=True)
    )
    op.add_column("agent_triggers", sa.Column("portal_key", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "agent_triggers_connection_id_fkey",
        "agent_triggers",
        "mcp_connections",
        ["connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_trigger_registered_hook_has_connection",
        "agent_triggers",
        "provider_webhook_id IS NULL OR connection_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_registered_hook_has_connection", "agent_triggers", type_="check")
    op.drop_constraint("agent_triggers_connection_id_fkey", "agent_triggers", type_="foreignkey")
    op.drop_column("agent_triggers", "portal_key")
    op.drop_column("agent_triggers", "provider_webhook_id")
    op.drop_column("agent_triggers", "delivery_mode")
    op.drop_column("agent_triggers", "connection_id")
    op.drop_column("mcp_connections", "granted_scopes")
