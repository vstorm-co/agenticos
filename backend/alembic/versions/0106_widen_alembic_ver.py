"""Widen alembic_version.version_num for revision ids > 32 chars.

Revision ID: 0106_widen_alembic_ver
Revises: 0106_minerp_tenant_id
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0106_widen_alembic_ver"
down_revision: str | None = "0106_minerp_tenant_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
