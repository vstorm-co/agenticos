"""Distinguish edited complete channel instructions from legacy additions.

Existing prompts keep their additive meaning. New edits may replace presentation
instructions without copying the deployment defaults into every stored binding.
Run identity, authorization and trusted environment context remain server-owned.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0325_channel_prompt_override"
down_revision: str = "0324_screened_message_replay"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "agent_exposures",
        sa.Column(
            "prompt_replaces_defaults",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_exposures", "prompt_replaces_defaults")
