"""One vault for every secret, and secrets that have a kind

Revision ID: 0038_vault
Revises: 0037_mcp_owner
Create Date: 2026-07-27

Three mechanisms held secrets at rest and only one of them bound a ciphertext
to its owner. Provider keys went through `app.core.vault` (an envelope keyed
on the organization); channel bot tokens went through a single deployment-wide
Fernet key; MCP bearer tokens and OAuth payloads went through another one. A
ciphertext for a Slack token or an MCP token could be copied from one
organization's row into another's and it decrypted. That is what this removes:
everything now seals through the vault, bound to an organization or - for a
member's personal MCP connection, which has no organization - to the member.

Three schema changes follow from that:

* `channel_bots.secret_key_version` - the token is now an envelope, and a
  staged master-key rotation has to know which key sealed each row.
* `credentials.kind` plus a nullable `sealed_secret` - a credential is no
  longer always an API key. Azure needs an endpoint and an API version, Bedrock
  an AWS key pair and a region, Vertex a service account, and a self-hosted
  model server needs no credential at all. The check constraint ties the two
  together so a row cannot claim to be keyless and carry a secret, or claim a
  shape and carry nothing.
* `organization_secrets` - a named, kind-tagged secret a capability can be
  pointed at by id. Referenced, never handed around: the plaintext reaches the
  capability instance and nothing else.

**This migration destroys unreadable secrets rather than leaving them.** The old
ciphertexts cannot be read by the new format and there is no dual-read path on
purpose - one mechanism, one format. A credential or a bot whose secret cannot
be decrypted is not a row worth keeping: it fails at its next use, silently in
the bot's case. MCP connections keep their row (URL, allowed tools, name) and
lose only the credential, so re-entering a token or re-authorizing is enough.
Confirmed acceptable: there is nothing in the database worth keeping.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0038_vault"
down_revision = "0037_mcp_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column("secret_key_version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.add_column("credentials", sa.Column("kind", sa.String(32), nullable=True))
    op.alter_column("credentials", "sealed_secret", nullable=True)

    # Old envelopes are unreadable under the new derivation. A credential
    # without a usable secret only fails later, in someone's agent, so it goes;
    # profiles pointing at it are left keyless by ON DELETE SET NULL and fail
    # loudly at resolution, which is the designed behaviour. A bot goes for the
    # same reason, and its failure would otherwise be silent.
    op.execute("DELETE FROM credentials")
    op.execute("DELETE FROM channel_bots")
    op.execute(
        "UPDATE mcp_connections SET auth_token = NULL, oauth_payload = NULL, "
        "oauth_pending_payload = NULL, oauth_state = NULL"
    )

    op.alter_column("credentials", "kind", nullable=False)
    op.create_check_constraint(
        "ck_credential_kind_matches_secret",
        "credentials",
        "(kind = 'none') = (sealed_secret IS NULL)",
    )

    op.create_table(
        "organization_secrets",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("sealed_secret", sa.String(), nullable=False),
        sa.Column("hint", sa.String(8), nullable=False, server_default=""),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_organization_secrets_organization_id", "organization_secrets", ["organization_id"]
    )
    op.create_unique_constraint(
        "uq_organization_secret_org_name", "organization_secrets", ["organization_id", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_organization_secret_org_name", "organization_secrets", type_="unique")
    op.drop_index("ix_organization_secrets_organization_id", table_name="organization_secrets")
    op.drop_table("organization_secrets")

    op.drop_constraint("ck_credential_kind_matches_secret", "credentials", type_="check")
    # A credential with no secret cannot exist in the old schema, and the rows
    # this migration would have to invent are exactly the keyless ones it
    # introduced. Removing them is the honest downgrade.
    op.execute("DELETE FROM credentials WHERE sealed_secret IS NULL")
    op.alter_column("credentials", "sealed_secret", nullable=False)
    op.drop_column("credentials", "kind")

    op.drop_column("channel_bots", "secret_key_version")
