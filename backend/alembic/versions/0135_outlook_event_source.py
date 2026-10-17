"""Outlook joins Gmail as a polled mail source

Revision ID: 0135_outlook_event_source
Revises: 0134_channel_prompt_free_text
Create Date: 2026-10-17

`outlook` is a Microsoft 365 mailbox read through the organization's Microsoft
grant, the same delivery as `gmail`: polled, so it has no inbound door and no
per-trigger secret (agenticos#1984). Both constraints that name the polled
sources widen to it; no existing row changes.
"""

from alembic import op

revision = "0135_outlook_event_source"
down_revision = "0134_channel_prompt_free_text"
branch_labels = None
depends_on = None

_SOURCE = "ck_trigger_event_source"
_SHAPE = "ck_trigger_shape"

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
    _swap(sources="'github', 'gmail', 'outlook', 'webhook'", polled="'gmail', 'outlook'")


def downgrade() -> None:
    """Back to Gmail alone.

    An `outlook` row has no secret and no source to fall back to, so it is
    deleted - the same call `0053` makes for a polled row on its way down.
    """
    op.execute("DELETE FROM agent_triggers WHERE event_source = 'outlook'")
    _swap(sources="'github', 'gmail', 'webhook'", polled="'gmail'")
