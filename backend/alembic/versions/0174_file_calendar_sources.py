"""Files and calendars join the polled sources (#2195).

Revision ID: 0174_file_calendar_sources
Revises: 0173_hubspot_zendesk_sources
Create Date: 2026-10-23

Google Drive, OneDrive/SharePoint, Google Calendar and Outlook Calendar are read
from a connected account like the mailboxes: polled, so no inbound door and no
per-trigger secret. Both constraints that name the polled sources widen to them;
no existing row changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0174_file_calendar_sources"
down_revision: str | None = "0173_hubspot_zendesk_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE = "ck_trigger_event_source"
_SHAPE = "ck_trigger_shape"
_NEW = "'google_calendar', 'google_drive', 'microsoft_files', 'outlook_calendar'"

_SCHEDULE = (
    "(trigger_type = 'schedule' AND next_fire_at IS NOT NULL "
    "AND event_source IS NULL "
    "AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
    "AND cron_expression IS NULL) "
    "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
    "AND interval_seconds IS NULL)))"
)


def _event(polled: str) -> str:
    return (
        "(trigger_type = 'event' AND event_source IS NOT NULL "
        f"AND ((event_source IN ({polled}) AND event_secret_encrypted IS NULL "
        "AND secret_key_version IS NULL) "
        f"OR (event_source NOT IN ({polled}) AND event_secret_encrypted IS NOT NULL "
        "AND secret_key_version IS NOT NULL)) "
        "AND next_fire_at IS NULL AND interval_seconds IS NULL "
        "AND cron_expression IS NULL)"
    )


def _swap(*, sources: str, polled: str) -> None:
    op.drop_constraint(_SOURCE, "agent_triggers", type_="check")
    op.drop_constraint(_SHAPE, "agent_triggers", type_="check")
    op.create_check_constraint(
        _SOURCE, "agent_triggers", f"event_source IS NULL OR event_source IN ({sources})"
    )
    op.create_check_constraint(_SHAPE, "agent_triggers", f"{_SCHEDULE} OR {_event(polled)}")


def upgrade() -> None:
    _swap(
        sources=f"'github', 'gmail', 'hubspot', 'outlook', 'webhook', 'zendesk', {_NEW}",
        polled=f"'gmail', 'outlook', {_NEW}",
    )


def downgrade() -> None:
    """Back to the mailboxes; a file or calendar trigger has nowhere to go."""
    op.execute(f"DELETE FROM agent_triggers WHERE event_source IN ({_NEW})")
    _swap(
        sources="'github', 'gmail', 'hubspot', 'outlook', 'webhook', 'zendesk'",
        polled="'gmail', 'outlook'",
    )
