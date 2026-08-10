"""A binding can add to what the agent was told.

The same published agent answers in a dashboard, on a website widget and in a
Mattermost channel, and those want different things of it: how to lay a message
out, whether headings render, how to give a link, how long an answer should be.
None of that is a different agent, and editing the spec to suit one surface
changes it on every other.

Nullable, and appended to the spec's instructions at run time rather than
substituted for them - what the agent is *for* belongs to the version somebody
published, and a binding that could replace it would be a way to repurpose an
approved agent without approving anything.

Revision ID: 0015_exposure_prompt
Revises: 0014_channel_link_requests
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_exposure_prompt"
down_revision: str | Sequence[str] | None = "0014_channel_link_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_exposures", sa.Column("prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_exposures", "prompt")
