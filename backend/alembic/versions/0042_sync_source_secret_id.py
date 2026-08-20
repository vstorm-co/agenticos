"""A sync source references a vault secret, and belongs to an organization.

`sync_sources.config` held the credential: a Google service account JSON or an
AWS key pair, pasted into a JSONB column and encrypted by `app/core/crypto.py` -
one deployment-wide Fernet key for every tenant, which is exactly the weakness
the vault exists to remove. `CLAUDE.md` says "every secret at rest goes through
`app/core/vault.py`. There is no second mechanism", and this table was the one
place that was untrue.

What kept it there was this migration's other half. A vault envelope is derived
from its owner's id, so a ciphertext needs an owner - and `organization_id` was
nullable, because the CLI created rows without one. #707 gave `rag-source-add` an
organization; this makes the column say so.

**An encrypted credential is cleared out of `config`, not decrypted and not
refused.** Three options and only one of them is followable:

* *Decrypt and re-seal here.* That means importing the application's crypto into
  a schema migration and writing a vault envelope from it. A half-moved
  credential is worse than either alternative - the operator gets a row pointing
  at a secret nobody can open, and no way to tell which.
* *Refuse the upgrade until the operator re-points each source.* This is what
  this migration did before review, and the instruction cannot be carried out:
  before the migration there is no `secret_id` column to point at. It asked for
  something impossible and left deleting the source as the only way forward.
* *Clear the ciphertext and leave the source without a credential.* Nothing
  readable is lost - the value is a Fernet token over `SECRET_KEY`, and the
  application that could read it is the one being replaced - and the source then
  says exactly what it needs: "this source has no credential. Pick one in the
  Vault and point the source at it." Which is now possible, because the column
  exists.

So the affected sources are **named in the log** and their credential fields
removed. What is left is inert rather than secret: a `config` with no credential
in it, and a `secret_id` of `NULL` that every sync refuses on.

A row with no organization is a different matter and still stops the upgrade:
`organization_id` is about to be `NOT NULL`, there is nothing to derive one from,
and the fix - set it, or delete the row - can be carried out before running this.

Revision ID: 0042_sync_source_secret_id
Revises: 0041_invitation_reservations
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0042_sync_source_secret_id"
down_revision: str | None = "0041_invitation_reservations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The prefix `app/core/crypto.py` put on everything it encrypted. Spelled out
# rather than imported: a migration that imports application code runs whatever
# that module means *today*, and this one has to keep meaning the same thing
# after the module is deleted.
_CIPHERTEXT_PREFIX = "enc:"


def _refuse(sources: Sequence[tuple[str, str]], reason: str, fix: str) -> None:
    listed = "\n".join(f"  - {name} ({source_id})" for source_id, name in sources)
    raise RuntimeError(
        f"{len(sources)} sync source(s) {reason}:\n{listed}\n\n{fix}\n"
        "This migration refuses rather than guessing: a credential moved wrongly "
        "is a source that cannot sync and cannot say why."
    )


def upgrade() -> None:
    connection = op.get_bind()

    orphans = connection.execute(
        sa.text("SELECT id::text, name FROM sync_sources WHERE organization_id IS NULL")
    ).all()
    if orphans:
        _refuse(
            [(row[0], row[1]) for row in orphans],
            "have no organization, and `organization_id` is about to be NOT NULL",
            "Delete them, or set their organization: a source belongs to one, and a "
            "vault credential is sealed to it. `rag-source-add` has required `--org` "
            "since #707, so these were written before that.",
        )

    op.alter_column(
        "sync_sources",
        "organization_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.add_column(
        "sync_sources",
        sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # The column exists now, which is what makes the instruction below possible.
    encrypted = connection.execute(
        sa.text(
            "SELECT id::text, name FROM sync_sources"
            " WHERE EXISTS ("
            "   SELECT 1 FROM jsonb_each_text(config) AS entry(key, value)"
            "   WHERE entry.value LIKE :prefix"
            " )"
        ),
        {"prefix": f"{_CIPHERTEXT_PREFIX}%"},
    ).all()
    if encrypted:
        # `-` on a jsonb object removes a key. Only the ciphertext keys go: the
        # folder id, bucket and prefix beside them are how the source finds its
        # documents and are not secret.
        connection.execute(
            sa.text(
                "UPDATE sync_sources SET config = ("
                "  SELECT coalesce(jsonb_object_agg(entry.key, entry.value), '{}'::jsonb)"
                "  FROM jsonb_each(config) AS entry(key, value)"
                "  WHERE entry.value::text NOT LIKE :quoted_prefix"
                ")"
                " WHERE EXISTS ("
                "   SELECT 1 FROM jsonb_each_text(config) AS inner_entry(key, value)"
                "   WHERE inner_entry.value LIKE :prefix"
                " )"
            ),
            {"prefix": f"{_CIPHERTEXT_PREFIX}%", "quoted_prefix": f'"{_CIPHERTEXT_PREFIX}%'},
        )
        listed = "\n".join(f"  - {name} ({source_id})" for source_id, name in encrypted)
        print(  # noqa: T201 - alembic's own output is how a migration talks
            f"\n{len(encrypted)} sync source(s) held a credential encrypted in `config`.\n"
            f"{listed}\n\n"
            "The ciphertext has been removed: it was a Fernet token over `SECRET_KEY`, "
            "readable only by the release being replaced, and leaving it would leave a "
            "credential at rest under a deployment-wide key - which is what this change "
            "removes.\n"
            "Each of these sources now has no credential and will refuse to sync. Add "
            "the credential to the organization's Vault - a `gcp_service_account` for "
            "Drive, an `aws_credentials` pair for S3 - and point the source at it.\n"
        )
    # The name the metadata's convention gives it - `alembic check` compares
    # against that, not against whatever this file happens to call it.
    op.create_index("sync_sources_secret_id_idx", "sync_sources", ["secret_id"])
    op.create_foreign_key(
        "sync_sources_secret_id_fkey",
        "sync_sources",
        "organization_secrets",
        ["secret_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("sync_sources_secret_id_fkey", "sync_sources", type_="foreignkey")
    op.drop_index("sync_sources_secret_id_idx", table_name="sync_sources")
    op.drop_column("sync_sources", "secret_id")
    op.alter_column(
        "sync_sources",
        "organization_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
