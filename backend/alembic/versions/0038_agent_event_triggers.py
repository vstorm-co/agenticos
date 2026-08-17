"""Event triggers - fire an agent on a GitHub issue or an inbound email

Revision ID: 0038_agent_event_triggers
Revises: 0037_agent_triggers
Create Date: 2026-08-11

`0037` gave `agent_triggers` one shape: a clock schedule (interval or cron). This
adds the second concept behind agenticos#44 - an *event* trigger, fired when
something arrives rather than when the clock says so - to the same table, told
apart by a new `trigger_type` discriminator (`schedule` | `event`).

An event trigger carries an `event_source` (`github`, `email`, `linkedin`, or the
catch-all `webhook`), a per-source
`event_config` filter (which repository, which sender), and the secret its inbound
webhook is verified against - sealed for the organization through the one vault
(`app/core/vault.py`) and stored inline as `event_secret_encrypted` with the
`secret_key_version` that sealed it, exactly as a channel bot stores its signing
secret. It has no `next_fire_at`: nothing is due until an event lands, so
`next_fire_at` becomes nullable and the heartbeat's `next_fire_at <= now` claim
excludes an event row without a special case.

The single shape CHECK is replaced, not amended: `ck_trigger_schedule_shape`
becomes `ck_trigger_shape`, now asserting a schedule carries its cadence and a next
fire and no event source, *or* an event carries a source and none of the schedule
machinery. Two narrow CHECKs join it - `ck_trigger_type` for the discriminator's
vocabulary and `ck_trigger_event_source` for the source's. All three are declared
on the model too, because the integration tests build the schema from the models.

The downgrade is real but lossy by necessity: the pre-0038 schema has no concept of
an event trigger, so it deletes any event rows before restoring `next_fire_at`'s
NOT NULL and the schedule-only shape check - there is nothing in the old shape to
migrate them to.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0038_agent_event_triggers"
down_revision = "0037_agent_triggers"
branch_labels = None
depends_on = None

# The 0037 shape check, restored on downgrade. Kept as a constant so the
# upgrade's drop and the downgrade's recreate name the same expression.
_SCHEDULE_SHAPE = (
    "(schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
    "AND cron_expression IS NULL) "
    "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
    "AND interval_seconds IS NULL)"
)

# The shape check spanning both concepts, added on upgrade.
_TRIGGER_SHAPE = (
    "(trigger_type = 'schedule' AND next_fire_at IS NOT NULL "
    "AND event_source IS NULL "
    "AND ((schedule_kind = 'interval' AND interval_seconds IS NOT NULL "
    "AND cron_expression IS NULL) "
    "OR (schedule_kind = 'cron' AND cron_expression IS NOT NULL "
    "AND interval_seconds IS NULL))) "
    "OR (trigger_type = 'event' AND event_source IS NOT NULL "
    "AND event_secret_encrypted IS NOT NULL AND secret_key_version IS NOT NULL "
    "AND next_fire_at IS NULL AND interval_seconds IS NULL "
    "AND cron_expression IS NULL)"
)


def upgrade() -> None:
    # NOT NULL columns need a server default to populate the rows already here;
    # the model declares none, so the default is dropped again once they are set.
    op.add_column(
        "agent_triggers",
        sa.Column("trigger_type", sa.String(length=16), nullable=False, server_default="schedule"),
    )
    op.add_column(
        "agent_triggers",
        sa.Column(
            "event_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("agent_triggers", sa.Column("event_source", sa.String(length=16), nullable=True))
    op.add_column("agent_triggers", sa.Column("event_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("agent_triggers", sa.Column("secret_key_version", sa.Integer(), nullable=True))
    op.alter_column("agent_triggers", "trigger_type", server_default=None)
    op.alter_column("agent_triggers", "event_config", server_default=None)

    # A schedule always has a next fire; an event never does.
    op.alter_column(
        "agent_triggers",
        "next_fire_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    # Replace the schedule-only shape check with one that spans both concepts, and
    # add the two vocabularies the new columns bring.
    op.drop_constraint(
        op.f("agent_triggers_ck_trigger_schedule_shape_check"),
        "agent_triggers",
        type_="check",
    )
    op.create_check_constraint(
        op.f("agent_triggers_ck_trigger_type_check"),
        "agent_triggers",
        "trigger_type IN ('schedule', 'event')",
    )
    op.create_check_constraint(
        op.f("agent_triggers_ck_trigger_event_source_check"),
        "agent_triggers",
        "event_source IS NULL OR event_source IN ('github', 'email', 'linkedin', 'webhook')",
    )
    op.create_check_constraint(
        op.f("agent_triggers_ck_trigger_shape_check"),
        "agent_triggers",
        _TRIGGER_SHAPE,
    )


def downgrade() -> None:
    # The old schema cannot express an event trigger, so there is nowhere to
    # migrate one - drop them before restoring the constraints they would fail.
    op.execute("DELETE FROM agent_triggers WHERE trigger_type = 'event'")

    op.drop_constraint(
        op.f("agent_triggers_ck_trigger_shape_check"), "agent_triggers", type_="check"
    )
    op.drop_constraint(
        op.f("agent_triggers_ck_trigger_event_source_check"), "agent_triggers", type_="check"
    )
    op.drop_constraint(
        op.f("agent_triggers_ck_trigger_type_check"), "agent_triggers", type_="check"
    )
    op.create_check_constraint(
        op.f("agent_triggers_ck_trigger_schedule_shape_check"),
        "agent_triggers",
        _SCHEDULE_SHAPE,
    )
    op.alter_column(
        "agent_triggers",
        "next_fire_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    op.drop_column("agent_triggers", "secret_key_version")
    op.drop_column("agent_triggers", "event_secret_encrypted")
    op.drop_column("agent_triggers", "event_source")
    op.drop_column("agent_triggers", "event_config")
    op.drop_column("agent_triggers", "trigger_type")
