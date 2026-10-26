"""HubSpot and Zendesk join the signed webhook sources (#2195).

Revision ID: 0177_hubspot_zendesk_sources
Revises: 0176_trigger_time_zone
Create Date: 2026-10-23

Both POST to the trigger's own URL and are verified by their provider's
signature, so they are webhook-shaped: a sealed secret, no polling. Only the
vocabulary widens; `ck_trigger_shape` already requires a secret of every source
it does not name as polled.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0177_hubspot_zendesk_sources"
down_revision: str | None = "0176_trigger_time_zone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE = "ck_trigger_event_source"


def _vocabulary(sources: str) -> None:
    op.drop_constraint(_SOURCE, "agent_triggers", type_="check")
    op.create_check_constraint(
        _SOURCE, "agent_triggers", f"event_source IS NULL OR event_source IN ({sources})"
    )


def upgrade() -> None:
    _vocabulary("'github', 'gmail', 'hubspot', 'outlook', 'webhook', 'zendesk'")


def downgrade() -> None:
    """Back to the four sources; a HubSpot or Zendesk trigger has nowhere to go."""
    op.execute("DELETE FROM agent_triggers WHERE event_source IN ('hubspot', 'zendesk')")
    _vocabulary("'github', 'gmail', 'outlook', 'webhook'")
