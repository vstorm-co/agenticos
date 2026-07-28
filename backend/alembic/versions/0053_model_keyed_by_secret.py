"""A model can be keyed by a vault secret rather than a separate credential

Revision ID: 0053_model_secret
Revises: 0052_secret_scope
Create Date: 2026-07-28

There were two credential stores: `credentials`, which only model profiles
read, and `organization_secrets`, which everything else reads. That split is
why adding an OpenRouter key in the vault did nothing for the model picker -
the picker was looking at the other table.

`model_profiles.secret_id` closes it. A model is now keyed by the same vault
entry a capability would use, so "add an OpenRouter secret" and "run on
OpenRouter models" are one action and its consequence.

`credential_id` stays and still works: existing profiles keep resolving through
it, and the resolver reads whichever of the two is set. Dropping it here would
mean rewriting every stored profile in a migration to point at rows that do not
exist yet.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0053_model_secret"
down_revision = "0052_secret_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_profiles",
        sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "model_profiles_secret_id_fkey",
        "model_profiles",
        "organization_secrets",
        ["secret_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("model_profiles_secret_id_fkey", "model_profiles", type_="foreignkey")
    op.drop_column("model_profiles", "secret_id")
