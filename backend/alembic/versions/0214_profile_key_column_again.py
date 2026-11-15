"""Add `model_profiles.runs_without_key` where the chain skipped it.

Revision ID: 0214_profile_key_column_again
Revises: 0213_grading_model
Create Date: 2026-10-27

`0175_profile_runs_without_key` joined this chain as a parent of
`0189_console_milestones_merge`. A database already past 0189 records 0175 as
applied without ever having run it, so it has no column. This adds it there,
with 0175's backfill, and does nothing on a database that ran 0175.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0214_profile_key_column_again"
down_revision: str | None = "0213_grading_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    present = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_attribute "
            "WHERE attrelid = 'model_profiles'::regclass "
            "AND attname = 'runs_without_key' AND NOT attisdropped)"
        )
    )
    if present:
        return
    op.add_column(
        "model_profiles",
        sa.Column("runs_without_key", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE model_profiles SET runs_without_key = true "
        "WHERE secret_id IS NULL AND base_url IS NOT NULL "
        "AND provider IN ('openai', 'ollama', 'litellm')"
    )


def downgrade() -> None:
    """Leave the column: it belongs to 0175, whose own downgrade drops it."""
