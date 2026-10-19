"""Let a channel question collect several choices before it is answered.

An `ask_user_question` asking for several options was offered in Slack,
Telegram and Mattermost as one-press buttons, so the first press answered it
and every later one was refused. `multi_select` keeps such a prompt open while
presses toggle choices into `answer`, until its Done button answers it.

Revision ID: 0130_channel_prompt_multi
Revises: 0129_message_attachment_context
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0130_channel_prompt_multi"
down_revision: str | None = "0129_message_attachment_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_prompts",
        sa.Column("multi_select", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("channel_prompts", "multi_select")
