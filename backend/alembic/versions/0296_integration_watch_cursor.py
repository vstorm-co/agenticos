"""Keep each integration watch's consumed position across worker restarts.

A connection's portal cursor belongs to its trigger poller. Sharing that cursor
with a watch would let the first reader consume events the other has not seen.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0296_integration_watch_cursor"
down_revision: str = "0295_tool_approval_consent"
branch_labels: None = None
depends_on: None = None


_NEW_CHECKS = {
    "ck_trigger_event_source": "event_source IS NULL OR event_source IN ('github', 'gmail', 'google_calendar', 'google_drive', 'hubspot', 'microsoft_files', 'outlook', 'outlook_calendar', 'webhook', 'zendesk', 'slack', 'teams', 'google_sheets', 'imap_mail', 'odoo')",
    "ck_trigger_shape": "(trigger_type = 'schedule' AND (next_fire_at IS NOT NULL OR one_shot) AND event_source IS NULL AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))) OR (trigger_type = 'event' AND event_source IS NOT NULL AND ((event_source IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar', 'slack', 'teams', 'google_sheets', 'imap_mail', 'odoo') AND event_secret_encrypted IS NULL AND secret_key_version IS NULL) OR (event_source NOT IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar', 'slack', 'teams', 'google_sheets', 'imap_mail', 'odoo') AND event_secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL)) AND next_fire_at IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL)",
}
_OLD_CHECKS = {
    "ck_trigger_event_source": "event_source IS NULL OR event_source IN ('github', 'gmail', 'google_calendar', 'google_drive', 'hubspot', 'microsoft_files', 'outlook', 'outlook_calendar', 'webhook', 'zendesk')",
    "ck_trigger_shape": "(trigger_type = 'schedule' AND (next_fire_at IS NOT NULL OR one_shot) AND event_source IS NULL AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL AND cron_expression IS NULL) OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL AND interval_seconds IS NULL))) OR (trigger_type = 'event' AND event_source IS NOT NULL AND ((event_source IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar') AND event_secret_encrypted IS NULL AND secret_key_version IS NULL) OR (event_source NOT IN ('gmail', 'google_calendar', 'google_drive', 'microsoft_files', 'outlook', 'outlook_calendar') AND event_secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL)) AND next_fire_at IS NULL AND interval_seconds IS NULL AND cron_expression IS NULL)",
}


def _replace_checks(checks: dict[str, str]) -> None:
    for name, expression in checks.items():
        op.drop_constraint(name, "agent_triggers", type_="check")
        op.create_check_constraint(name, "agent_triggers", expression)


def upgrade() -> None:
    op.create_index("agent_triggers_connection_id_idx", "agent_triggers", ["connection_id"])
    _replace_checks(_NEW_CHECKS)
    op.add_column("watches", sa.Column("integration_cursor", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    count = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM agent_triggers WHERE event_source IN ('slack', 'teams', 'google_sheets', 'imap_mail', 'odoo')"
            )
        )
        .scalar_one()
    )
    if count:
        raise RuntimeError(
            "Remove native Slack, Teams, Sheets, IMAP and Odoo triggers before downgrading"
        )
    _replace_checks(_OLD_CHECKS)
    op.drop_column("watches", "integration_cursor")
    op.drop_index("agent_triggers_connection_id_idx", table_name="agent_triggers")
