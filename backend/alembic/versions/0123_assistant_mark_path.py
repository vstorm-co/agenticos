"""Remember which picture is the Architect's shipped mark (#2063).

`organization_assistants.mark_path` holds where the mark the assistant was
installed wearing is stored, so the console can tell it from a picture an
organization uploaded and draw the mark in the theme's colours instead. Every
installed assistant is taken to still wear it: no deployment has given one a
picture of its own yet, and one that has will show the mark again until the
picture is uploaded once more.

Revision ID: 0123_assistant_mark_path
Revises: 0122_queue_while_working
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0123_assistant_mark_path"
down_revision: str | None = "0122_queue_while_working"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_assistants", sa.Column("mark_path", sa.String(length=500), nullable=True)
    )
    op.execute(
        "UPDATE organization_assistants SET mark_path = agents.avatar_url "
        "FROM agents WHERE agents.id = organization_assistants.agent_id"
    )


def downgrade() -> None:
    op.drop_column("organization_assistants", "mark_path")
