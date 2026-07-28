"""A skill can carry a category

Revision ID: 0056_skill_category
Revises: 0055_one_key_store
Create Date: 2026-07-28

Skills accumulate: refund policy next to deploy checklist next to house style.
The listing needed something to group and filter them by, and the body is the
one part of a skill people do not reread to find out what shelf it belongs on.

One nullable column. A skill without a category is simply uncategorized - that
was true of every skill before this revision, so existing rows need no
backfill and the column needs no default. The label is for people, not the
model: nothing in the agent path reads it.
"""

import sqlalchemy as sa

from alembic import op

revision = "0056_skill_category"
down_revision = "0055_one_key_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("category", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("skills", "category")
