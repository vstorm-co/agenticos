"""An agent names its model; there is no organization-wide default

Revision ID: 0054_no_default_model
Revises: 0053_model_secret
Create Date: 2026-07-28

`is_default` was a pointer: an agent could leave `model_profile_id` empty and
run on whatever profile happened to hold the flag. That made the model an agent
runs on something another page could change — the same published spec answering
on a different model, at a different price, with nothing in the agent's own
history to explain it.

It also produced the row this migration is really about. Bootstrap created a
default profile whether or not it had a key to put in one, because *something*
had to be the default; the result was `openai default · no key` sitting in every
picker, an option whose only effect was to make an agent fail at its first
message. Nothing repoints such a profile — models are keyed from the vault now —
so it could not even be repaired.

Publish validation refuses a spec with no model instead. Existing published
agents already name one, because publishing has always resolved it; drafts that
do not are refused at publish, which is where that belongs.

The partial unique index goes with the column — it existed only to keep two
concurrent writes from both claiming the flag.
"""

import sqlalchemy as sa
from alembic import op

revision = "0054_no_default_model"
down_revision = "0053_model_secret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_model_profile_one_default", table_name="model_profiles")
    op.drop_column("model_profiles", "is_default")


def downgrade() -> None:
    op.add_column(
        "model_profiles",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "uq_model_profile_one_default",
        "model_profiles",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
