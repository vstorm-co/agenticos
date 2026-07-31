"""Slack app credentials move onto the bot row

Revision ID: 0064_slack_creds_per_bot
Revises: 0063_kb_org_visibility
Create Date: 2026-07-30

`SLACK_SIGNING_SECRET` and `SLACK_APP_TOKEN` were deployment-wide, which meant
every Slack bot on an installation was the same Slack app - a second
workspace's bot verified inbound events with the first's secret. Each bot now
carries its own pair, sealed in the vault exactly as its token is.

The backfill seals the environment's values - when they are set - into every
existing Slack bot, because that is precisely what those bots have been using:
one deployment, one Slack app, every bot on it. A deployment without the
variables gets NULLs, and the webhook refuses with the sentence that says
where to add the secret.

The downgrade drops the columns; the environment variables it would hand the
job back to no longer exist, which is the point of the change.
"""

import os

import sqlalchemy as sa

from alembic import op

revision = "0064_slack_creds_per_bot"
down_revision = "0063_kb_org_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column("slack_signing_secret_encrypted", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "channel_bots",
        sa.Column("slack_app_token_encrypted", sa.String(length=1000), nullable=True),
    )

    # Read from the process environment rather than Settings: the fields are
    # gone from Settings in the same change, and this migration is the one
    # place the old variables still mean something.
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    if not signing_secret and not app_token:
        return

    from app.core.vault import VaultScope, seal

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, organization_id, secret_key_version FROM channel_bots "
            "WHERE platform = 'slack'"
        )
    ).fetchall()
    for bot_id, organization_id, key_version in rows:
        scope = VaultScope.organization(organization_id)
        params = {
            "id": bot_id,
            "signing": (
                seal(signing_secret, scope=scope, key_version=key_version).ciphertext
                if signing_secret
                else None
            ),
            "app": (
                seal(app_token, scope=scope, key_version=key_version).ciphertext
                if app_token
                else None
            ),
        }
        bind.execute(
            sa.text(
                "UPDATE channel_bots SET "
                "slack_signing_secret_encrypted = :signing, "
                "slack_app_token_encrypted = :app "
                "WHERE id = :id"
            ),
            params,
        )


def downgrade() -> None:
    op.drop_column("channel_bots", "slack_app_token_encrypted")
    op.drop_column("channel_bots", "slack_signing_secret_encrypted")
