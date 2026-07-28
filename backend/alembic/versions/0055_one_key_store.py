"""One key store: the vault. The `credentials` table goes

Revision ID: 0055_one_key_store
Revises: 0054_no_default_model
Create Date: 2026-07-28

There were two places a provider key could live. `credentials` came first: a
sealed key with a label, a provider and an optional base URL, created from a
form in the vault. Then keys moved into `organization_secrets`, which everything
else already used — capabilities, web search, channels — and a model profile
grew a `secret_id` beside its `credential_id`.

Two stores for one thing is two of everything: two forms, two rotations, two
sets of tenant checks, and a model profile that could point at either. The vault
won, because it is the one with sharing, purposes, visibility and rotation. The
UI stopped creating credentials some time ago; this removes what was left.

Three changes:

- `model_profiles.credential_id` goes. A profile names a vault secret. Any
  profile still keyed the old way is left with no key and says so in the
  Builder, which is the honest outcome — the key itself is in the dropped table
  and cannot be carried across, because a credential has no `purpose` and the
  vault refuses a secret without one.
- `agent_runs.credential_id` becomes `agent_runs.secret_id`, pointing at the
  vault. Spend per key is the reason that column exists, and the ids in it are
  about to name rows that no longer exist, so the values are cleared rather than
  carried: attributing history to a key that was deleted is exactly what the
  left join already handles.
- `credentials` is dropped.

Not reversible in the sense that matters. The downgrade rebuilds the tables, and
nothing refills them — the sealed keys are gone with the rows.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0055_one_key_store"
down_revision = "0054_no_default_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("model_profiles_credential_id_fkey", "model_profiles", type_="foreignkey")
    op.drop_column("model_profiles", "credential_id")

    op.drop_constraint("agent_runs_credential_id_fkey", "agent_runs", type_="foreignkey")
    op.alter_column("agent_runs", "credential_id", new_column_name="secret_id")
    # The ids named credentials; the column now names vault secrets. Cleared so
    # nothing joins a run to whichever secret happens to share a UUID — which
    # will not happen, but "will not happen" is not a foreign key.
    op.execute("UPDATE agent_runs SET secret_id = NULL")
    op.create_foreign_key(
        "agent_runs_secret_id_fkey",
        "agent_runs",
        "organization_secrets",
        ["secret_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_table("credentials")


def downgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("sealed_secret", sa.Text(), nullable=True),
        sa.Column("hint", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "label", name="uq_credential_org_label"),
    )

    op.drop_constraint("agent_runs_secret_id_fkey", "agent_runs", type_="foreignkey")
    op.alter_column("agent_runs", "secret_id", new_column_name="credential_id")
    op.create_foreign_key(
        "agent_runs_credential_id_fkey",
        "agent_runs",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "model_profiles",
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "model_profiles_credential_id_fkey",
        "model_profiles",
        "credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )
