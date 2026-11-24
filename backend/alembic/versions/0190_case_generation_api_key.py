"""Retain the API key authority used to queue case generation.

The worker revalidates this identity and its scopes before reading material.
There is deliberately no foreign key: deleting a key must leave its identity
on queued generations so they fail closed rather than run with console access.
Existing console generations keep NULL.

Revision ID: 0190_case_generation_api_key
Revises: 0189_console_milestones_merge
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0190_case_generation_api_key"
down_revision: str | None = "0189_console_milestones_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("case_generations", sa.Column("created_by_api_key_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("case_generations", "created_by_api_key_id")
