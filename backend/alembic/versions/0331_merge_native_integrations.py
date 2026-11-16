"""Join native integrations with the current platform migration history.

Both branches extend the trigger source constraint. Reapply their union after
both histories run, so migration order cannot remove either set of sources.
"""

from alembic import op

revision: str = "0331_merge_native_integrations"
down_revision: tuple[str, str] = ("0330_linear_trigger", "0296_integration_watch_cursor")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint("ck_trigger_event_source", "agent_triggers", type_="check")
    op.create_check_constraint(
        "ck_trigger_event_source",
        "agent_triggers",
        "event_source IS NULL OR event_source IN "
        "('github', 'gmail', 'google_calendar', 'google_drive', 'hubspot', "
        "'linear', 'microsoft_files', 'outlook', 'outlook_calendar', 'webhook', 'zendesk', "
        "'slack', 'teams', 'google_sheets', 'imap_mail', 'odoo')",
    )


def downgrade() -> None:
    pass
