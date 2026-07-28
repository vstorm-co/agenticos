"""Drop the conversation demo flag along with the gallery that read it

Revision ID: 0047_drop_is_demo
Revises: 0046_ocr_tesseract
Create Date: 2026-07-28

`is_demo` existed for a public showcase the template shipped: an admin flagged a
conversation and `GET /demos` served it to anonymous visitors. This product
never built the page, so the flag had exactly one writer (an admin endpoint) and
one reader (a router nothing reached). Both are gone, and a boolean nothing
consults is worse than no column: it survives long enough that somebody assumes
it means something.

Removing it is safe in the direction that matters — no code reads the value —
and the downgrade restores the column with its index and default, so a rollback
lands on a schema the previous revision's models can still write. The flags
themselves are not recoverable, which is the honest cost of dropping a column;
they marked conversations for a gallery that never rendered.
"""

import sqlalchemy as sa

from alembic import op

revision = "0047_drop_is_demo"
down_revision = "0046_ocr_tesseract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_conversations_is_demo", table_name="conversations")
    op.drop_column("conversations", "is_demo")


def downgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "is_demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_conversations_is_demo", "conversations", ["is_demo"])
