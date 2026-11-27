"""Join retained conversation environments with the reviewed release train.

This revision only joins the migration graph. The individual migrations retain
their upgrade and downgrade checks for financial precision and live resources.
"""

revision: str = "0382_merge_live_environments"
down_revision: tuple[str, ...] = (
    "0381_merge_currency_precision",
    "0376_conversation_environments",
)
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
