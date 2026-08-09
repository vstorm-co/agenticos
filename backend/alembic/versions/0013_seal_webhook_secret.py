"""Seal the shared secret that authenticates an inbound webhook.

`channel_bots.webhook_secret` was a 32-byte credential written straight to a
`String(255)` column, in the same row as `token_encrypted`,
`slack_signing_secret_encrypted` and `slack_app_token_encrypted` - all sealed.
It is the only thing standing between the internet and a run charged to this
organization: Telegram sends it back in `X-Telegram-Bot-Api-Secret-Token`, and a
Mattermost outgoing webhook carries it in the body, where it is the whole of the
authentication because Mattermost does not sign payloads.

CLAUDE.md: every secret at rest goes through `app/core/vault.py`, and there is no
second mechanism. This was the second mechanism.

The rows are re-sealed rather than dropped. A `NULL` here is not a bot that
merely loses a setting - the Telegram receiver skips verification when the secret
is absent, so discarding these values would turn every configured webhook into an
unauthenticated endpoint, which is the opposite of the point.

`app.core.vault` is imported rather than reimplemented, for the same reason: a
second copy of the envelope format is exactly the second mechanism this migration
removes. The coupling is real - a later change to the envelope has to keep
`seal`/`unseal` working, or replace this file with one that no longer needs them.

Revision ID: 0013_seal_webhook_secret
Revises: 0012_message_parts_timeline
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.vault import VaultScope, seal, unseal

revision: str = "0013_seal_webhook_secret"
down_revision: str | Sequence[str] | None = "0012_message_parts_timeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Both columns hold the same credential in the two forms this migration moves it
# between, so one statement each, with the column named at the call site. The
# name is a literal in this file - never a value from a row.
_SELECT = (
    "SELECT id, organization_id, secret_key_version, {column} AS secret "
    "FROM channel_bots WHERE {column} IS NOT NULL"
)
_UPDATE = "UPDATE channel_bots SET {column} = :secret WHERE id = :bot_id"


def upgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column("webhook_secret_encrypted", sa.String(length=1000), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text(_SELECT.format(column="webhook_secret"))).fetchall()
    for row in rows:
        sealed = seal(
            row.secret,
            scope=VaultScope.organization(row.organization_id),
            key_version=row.secret_key_version,
        )
        bind.execute(
            sa.text(_UPDATE.format(column="webhook_secret_encrypted")),
            {"secret": sealed.ciphertext, "bot_id": row.id},
        )

    op.drop_column("channel_bots", "webhook_secret")


def downgrade() -> None:
    """Unseal back into the plaintext column.

    Symmetric on purpose: `make test-migrations` runs the whole chain forwards
    and back, and a downgrade that drops the envelopes would leave every
    webhook-mode bot unauthenticated on the way down.
    """
    op.add_column("channel_bots", sa.Column("webhook_secret", sa.String(length=255), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(_SELECT.format(column="webhook_secret_encrypted"))).fetchall()
    for row in rows:
        bind.execute(
            sa.text(_UPDATE.format(column="webhook_secret")),
            {
                "secret": unseal(
                    row.secret,
                    scope=VaultScope.organization(row.organization_id),
                    key_version=row.secret_key_version,
                ),
                "bot_id": row.id,
            },
        )

    op.drop_column("channel_bots", "webhook_secret_encrypted")
