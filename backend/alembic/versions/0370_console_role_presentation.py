"""Add optional console presentation policy without changing permissions.

Null preserves existing navigation and product prompts. Per-role organization
choices and personal preferences are presentation only.

Revision ID: 0370_console_role_presentation
Revises: 0369_chat_cost_visibility
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0370_console_role_presentation"
down_revision: str | None = "0369_chat_cost_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column("console_availability", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("console_role_defaults", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("console_notices", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column(
        "organization_members",
        sa.Column("console_preferences", postgresql.JSONB(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organization_members", "console_preferences")
    op.drop_column("organizations", "console_notices")
    op.drop_column("organizations", "console_role_defaults")
    op.drop_column("deployment_settings", "console_availability")
