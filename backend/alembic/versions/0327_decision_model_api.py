"""Allow explicitly selected decision APIs without moving existing model profiles."""

from alembic import op

revision: str = "0327_decision_model_api"
down_revision: str = "0326_channel_observation"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint("ck_model_profile_api", "model_profiles", type_="check")
    op.create_check_constraint(
        "ck_model_profile_api", "model_profiles", "api IN ('chat', 'responses', 'decisions')"
    )


def downgrade() -> None:
    # Do not turn decision endpoints into chat profiles or silently discard them.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM model_profiles WHERE api = 'decisions') THEN RAISE EXCEPTION 'Remove decision API model profiles before downgrading'; END IF; END $$"
    )
    op.drop_constraint("ck_model_profile_api", "model_profiles", type_="check")
    op.create_check_constraint(
        "ck_model_profile_api", "model_profiles", "api IN ('chat', 'responses')"
    )
