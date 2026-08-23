"""A polled event trigger carries no signing secret, and the shape says so

Revision ID: 0053_polled_trigger_no_secret
Revises: 0052_gmail_event_source
Create Date: 2026-08-21

`0052` gave `gmail` no inbound door - `accepts_delivery` refuses a POST naming a
polled source before a signature is looked for - but left `ck_trigger_shape`
requiring `event_secret_encrypted` on *every* event row. So the create path went
on minting a secret and calling the row `manual`, and creating a Gmail trigger
answered with a webhook URL and a reveal-once secret for a door that refuses
them: an instruction to go and configure a relay that cannot work
(agenticos#1068).

The constraint now ties the secret to the source: a polled one must carry
**none**, and a posted one must carry one. Stated in the schema rather than
trusted to the service, because it was the service that got it wrong - and a
credential nobody can spend, handed to somebody as "copy it now, it won't be
shown again", is the kind of mistake worth making impossible rather than fixing
twice.

Any `gmail` row the broken create already wrote is repaired rather than deleted:
it is dropped to `polling` and its secret cleared. That is what the person meant
to create - a trigger on their mailbox - and the credential it held was never
spendable, since the door refuses a delivery naming a polled source. Deleting
their trigger to satisfy a constraint would be the wrong half to give up.
"""

from alembic import op

revision = "0053_polled_trigger_no_secret"
down_revision = "0052_gmail_event_source"
branch_labels = None
depends_on = None

_CHECK = "ck_trigger_shape"

_SCHEDULE = (
    "(trigger_type = 'schedule' AND next_fire_at IS NOT NULL "
    "AND event_source IS NULL "
    "AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
    "AND cron_expression IS NULL) "
    "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
    "AND interval_seconds IS NULL)))"
)

_EVENT_WITH_CONDITIONAL_SECRET = (
    "(trigger_type = 'event' AND event_source IS NOT NULL "
    "AND ((event_source IN ('gmail') AND event_secret_encrypted IS NULL "
    "AND secret_key_version IS NULL) "
    "OR (event_source NOT IN ('gmail') AND event_secret_encrypted IS NOT NULL "
    "AND secret_key_version IS NOT NULL)) "
    "AND next_fire_at IS NULL AND interval_seconds IS NULL "
    "AND cron_expression IS NULL)"
)

_EVENT_ALWAYS_SECRET = (
    "(trigger_type = 'event' AND event_source IS NOT NULL "
    "AND event_secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL "
    "AND next_fire_at IS NULL AND interval_seconds IS NULL "
    "AND cron_expression IS NULL)"
)


def upgrade() -> None:
    op.drop_constraint(_CHECK, "agent_triggers", type_="check")
    # The rows the broken create wrote: a polled source carrying a secret nothing
    # can spend, and calling itself `manual`. Repaired into the shape the person
    # was asking for.
    op.execute(
        "UPDATE agent_triggers SET delivery_mode = 'polling', "
        "event_secret_encrypted = NULL, secret_key_version = NULL "
        "WHERE event_source = 'gmail'"
    )
    op.create_check_constraint(
        _CHECK, "agent_triggers", f"{_SCHEDULE} OR {_EVENT_WITH_CONDITIONAL_SECRET}"
    )


def downgrade() -> None:
    """Back to a secret on every event row.

    A `gmail` row has none, so it would fail the restored constraint - and there
    is no honest secret to invent for it. Such rows are deleted: the source is
    gone on the way down anyway (`0052`'s own downgrade rewrites them), and a
    trigger nothing can deliver to is not a row worth keeping alive through a
    rollback.
    """
    op.execute("DELETE FROM agent_triggers WHERE event_source = 'gmail'")
    op.drop_constraint(_CHECK, "agent_triggers", type_="check")
    op.create_check_constraint(_CHECK, "agent_triggers", f"{_SCHEDULE} OR {_EVENT_ALWAYS_SECRET}")
