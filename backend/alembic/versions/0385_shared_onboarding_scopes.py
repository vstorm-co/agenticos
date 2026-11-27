"""Separate deployment and organization setup from each member's personal start.

All existing installations and organizations receive unfinished shared stages.
Previously completed personal starts and snoozes are preserved unchanged. A nullable
completion timestamp is the sole source of completion truth; visiting a screen is
not evidence of saved configuration. Downgrade removes only shared setup progress.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0385_shared_onboarding_scopes"
down_revision: str = "0384_environment_layout_driver"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    for table in ("deployment_settings", "organizations"):
        op.add_column(
            table, sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(table, sa.Column("onboarding_current_step", sa.String(64), nullable=True))
        op.add_column(
            table, sa.Column("onboarding_updated_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_check_constraint(
        op.f("deployment_settings_onboarding_step_check"),
        "deployment_settings",
        "onboarding_current_step IS NULL OR onboarding_current_step = 'admin.deployment'",
    )
    op.create_check_constraint(
        op.f("organizations_onboarding_step_check"),
        "organizations",
        "onboarding_current_step IS NULL OR onboarding_current_step IN ('admin.workspace', 'admin.identity', 'admin.models', 'admin.tools', 'admin.team', 'admin.organization')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("organizations_onboarding_step_check"), "organizations", type_="check")
    op.drop_constraint(
        op.f("deployment_settings_onboarding_step_check"), "deployment_settings", type_="check"
    )
    for table in ("organizations", "deployment_settings"):
        for column in (
            "onboarding_updated_at",
            "onboarding_current_step",
            "onboarding_completed_at",
        ):
            op.drop_column(table, column)
