"""Add opt-in organization text-to-speech defaults without changing stored agents.

Revision ID: 0339_organization_text_to_speech
Revises: 0338_personal_model_keys
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0339_organization_text_to_speech"
down_revision: str = "0338_personal_model_keys"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("text_to_speech", postgresql.JSONB(), nullable=True))
    op.add_column(
        "agent_runs", sa.Column("text_to_speech_defaults", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "text_to_speech_defaults")
    op.drop_column("organizations", "text_to_speech")
