"""Add nullable model-profile regions without changing existing profiles."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0254_model_profile_region"
down_revision: str | None = "0253_background_topics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_profiles", sa.Column("region", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_model_profile_region", "model_profiles", "region IN ('eu', 'eea', 'global')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_model_profile_region", "model_profiles", type_="check")
    op.drop_column("model_profiles", "region")
