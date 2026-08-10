"""A widget can declare what the page must tell it.

`agent_embeds.context` is a sentence somebody wrote once, the same for every
visitor - "you are on the pricing page". What it could not say is anything about
*this* visitor, and the integrator is the only one who knows that: which plan
they are on, which locale, which order they are looking at.

So an embed declares variables - a name, whether it is required, and a line
saying what it is for - and the page supplies values at integration time. They
are appended to the agent's instructions as a marked block of data, never as
instructions, because a value that arrives from a browser is a value a visitor
can edit.

An empty list is what every existing embed gets, and it changes nothing.

Revision ID: 0020_embed_context_variables
Revises: 0019_exposure_usage_reporting
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_embed_context_variables"
down_revision: str | Sequence[str] | None = "0019_exposure_usage_reporting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_embeds",
        sa.Column(
            "context_variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_embeds", "context_variables")
