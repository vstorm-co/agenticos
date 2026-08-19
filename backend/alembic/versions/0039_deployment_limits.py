"""How many organizations one account may own, and how many agents one may hold.

Both null by default, and null means no ceiling rather than "not configured" -
an installation that has never opened the page is uncapped, which is what a
self-hosted deployment for one company wants. A deployment open to sign-ups
wants a number, where one account can otherwise mint tenants without bound.

Nothing is backfilled for the same reason every other column on this table is
nullable: an operator who has never set a limit has not asked for one.

Revision ID: 0039_deployment_limits
Revises: 0038_run_manifest
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039_deployment_limits"
down_revision: str | None = "0038_run_manifest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column("max_organizations_per_user", sa.Integer(), nullable=True),
    )
    op.add_column(
        "deployment_settings",
        sa.Column("max_agents_per_organization", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deployment_settings", "max_agents_per_organization")
    op.drop_column("deployment_settings", "max_organizations_per_user")
