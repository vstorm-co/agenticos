"""Fence remote-agent source reviews against credential replacement.

Revision ID: 0281_secret_auth_generation
Revises: 0280_phone_cases
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0281_secret_auth_generation"
down_revision: str | None = "0280_phone_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_secrets",
        sa.Column(
            "authorization_generation",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.alter_column("organization_secrets", "authorization_generation", server_default=None)


def downgrade() -> None:
    op.drop_column("organization_secrets", "authorization_generation")
