"""Next steps as buttons in a chat (#2301).

An answer that ends with `suggest_next_steps` is offered in Slack, Telegram,
Mattermost and Teams as a message with a button per step, kept as a
`channel_prompts` row of the new kind `follow_up`. A press is replayed as the
presser's next message, which needs the kind of chat it was offered in - the
press does not carry it - so the row records it in `chat_type`. No existing row
is a follow-up, so nothing is backfilled.

Revision ID: 0164_channel_next_steps
Revises: 0163_proactivity
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0164_channel_next_steps"
down_revision: str | None = "0163_proactivity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "(kind = 'approval' AND approval_id IS NOT NULL)"
    " OR (kind = 'question' AND tool_call_id IS NOT NULL AND question_index IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column("channel_prompts", sa.Column("chat_type", sa.String(length=16), nullable=True))
    op.drop_constraint("ck_channel_prompts_kind", "channel_prompts", type_="check")
    op.create_check_constraint(
        "ck_channel_prompts_kind",
        "channel_prompts",
        f"{_KINDS} OR (kind = 'follow_up' AND chat_type IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM channel_prompts WHERE kind = 'follow_up'")
    op.drop_constraint("ck_channel_prompts_kind", "channel_prompts", type_="check")
    op.create_check_constraint("ck_channel_prompts_kind", "channel_prompts", _KINDS)
    op.drop_column("channel_prompts", "chat_type")
