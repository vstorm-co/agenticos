"""Allow deployments to require provider sign-in without changing existing access.

Local passwords and email recovery remain enabled for every existing deployment.
The operator can disable them after configuring a provider; an environment-only
recovery override restores local admission when the identity provider is down.

Revision ID: 0368_password_sign_in_policy
Revises: 0367_portability_operations
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0368_password_sign_in_policy"
down_revision: str | None = "0367_portability_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column(
            "password_sign_in_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("deployment_settings", "password_sign_in_enabled")
