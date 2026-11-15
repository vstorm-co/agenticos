"""Allow Linear as a signed agent trigger source.

Downgrade refuses while Linear triggers exist, preserving their configuration.
"""

from alembic import op

revision: str = "0330_linear_trigger"
down_revision: str = "0329_merge_channel_and_coding"
branch_labels: None = None
depends_on: None = None

_OLD = (
    "'github', 'gmail', 'google_calendar', 'google_drive', 'hubspot', "
    "'microsoft_files', 'outlook', 'outlook_calendar', 'webhook', 'zendesk'"
)


def _set_sources(sources: str) -> None:
    op.drop_constraint("ck_trigger_event_source", "agent_triggers", type_="check")
    op.create_check_constraint(
        "ck_trigger_event_source",
        "agent_triggers",
        f"event_source IS NULL OR event_source IN ({sources})",
    )


def upgrade() -> None:
    _set_sources(_OLD + ", 'linear'")


def downgrade() -> None:
    _set_sources(_OLD)
