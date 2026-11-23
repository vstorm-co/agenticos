"""Keep negotiated token prices on each model profile.

Null preserves automatic pricing for every existing profile. The override is a
complete, validated document rather than model settings sent to the provider.
Historical run and message costs are already persisted and are not rewritten.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0352_model_profile_pricing"
down_revision: str = "0351_merge_context_onboarding"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "model_profiles",
        sa.Column("custom_pricing", postgresql.JSONB(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_profiles", "custom_pricing")
