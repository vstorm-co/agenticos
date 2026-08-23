"""The email relay source becomes Gmail, which is polled rather than posted to

Revision ID: 0052_gmail_event_source
Revises: 0051_trigger_fire_in_flight
Create Date: 2026-08-21

`email` named itself after a mailbox and then asked the user to run a relay - an
inbound parser, a Zapier code step, their own script - that POSTs signed JSON at
us. That is the `webhook` source with two renamed filter fields and the word
*email* on a promise nothing here could keep: `app/services/email/` is send-only,
with no IMAP and no inbound parse. It is the same defect `linkedin` was removed
for (agenticos#1068).

`gmail` replaces it and is delivered by **polling** a connected mailbox, so it has
no inbound door and no per-trigger secret at all.

**Existing `email` rows become `webhook` rows, not `gmail` ones.** What they
actually are is a relay posting signed JSON, which is exactly what `webhook`
means - and they hold a secret their sender knows, so re-labelling them `gmail`
would leave a row whose delivery mechanism no longer exists and whose trigger
would never fire again. As `webhook` they keep working unchanged. Their
`subject_contains` / `sender_contains` config is left in place: the generic source
carries no filter, so the keys are inert rather than wrong, and deleting a user's
filter to tidy a vocabulary is not this migration's business.

The vocabulary CHECK is swapped rather than widened, so a row cannot be written
with the retired value afterwards.
"""

from alembic import op

revision = "0052_gmail_event_source"
down_revision = "0051_trigger_fire_in_flight"
branch_labels = None
depends_on = None

_CHECK = "ck_trigger_event_source"


def upgrade() -> None:
    op.drop_constraint(_CHECK, "agent_triggers", type_="check")
    op.execute("UPDATE agent_triggers SET event_source = 'webhook' WHERE event_source = 'email'")
    # A portal-created row points at the portal it came from, and the `email`
    # portal is gone; a relay-fed row is the API source's now, which has no portal.
    op.execute("UPDATE agent_triggers SET portal_key = NULL WHERE portal_key = 'email'")
    op.create_check_constraint(
        _CHECK,
        "agent_triggers",
        "event_source IS NULL OR event_source IN ('github', 'gmail', 'webhook')",
    )


def downgrade() -> None:
    """The vocabulary goes back; the rows do not.

    A row rewritten to `webhook` above is indistinguishable from one created as
    `webhook`, so there is nothing to send back - and it works either way, which
    is the point of having moved it there rather than to `gmail`.
    """
    op.drop_constraint(_CHECK, "agent_triggers", type_="check")
    op.execute("UPDATE agent_triggers SET event_source = 'webhook' WHERE event_source = 'gmail'")
    op.create_check_constraint(
        _CHECK,
        "agent_triggers",
        "event_source IS NULL OR event_source IN ('github', 'email', 'webhook')",
    )
