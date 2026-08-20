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

**A row holding an encrypted credential stops this migration rather than being
guessed at.** Decrypting inside Alembic would mean importing the application's
crypto into a schema migration and writing a vault envelope from it, and a
half-moved credential is worse than a refused upgrade: the operator would have a
row pointing at a secret nobody can open and no way to tell which. The refusal
names the sources, and the fix is to re-add their credential through the vault -
which is one screen, and the last time anyone has to paste it. The same applies
to a row with no organization: there is nothing to bind its credential to and
nothing to migrate it into.

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
        _refuse(
            [(row[0], row[1]) for row in encrypted],
            "hold a credential encrypted in `config`",
            "Re-add each one's credential in the Vault and point the source at it, "
            "then re-run this migration. The old value is a Fernet token over "
            "`SECRET_KEY` and is not readable from here.",
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
