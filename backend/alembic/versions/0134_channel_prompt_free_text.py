"""Remember which channel questions take a typed answer.

A question that allows a free-form answer - and one that offers no options at
all - was offered in a chat as buttons only, so the person could skip it and
nothing else. The flag lets their next message in that chat answer it.

Revision ID: 0134_channel_prompt_free_text
Revises: 0133_agent_run_key_scopes
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0134_channel_prompt_free_text"
down_revision: str | None = "0133_agent_run_key_scopes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_prompts",
        sa.Column("allow_custom", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("channel_prompts", "allow_custom")
