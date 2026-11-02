"""Store where a model profile's requests may run.

A nullable column with a check constraint, like `api`. Null for every existing
profile, which is right: no provider took a region before this.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0251_model_profile_region"
down_revision: str | None = "0250_discord_channel"
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
