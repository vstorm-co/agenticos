"""Join the recovered core and published v1.76.1 histories without replaying DDL.

The original core, room, provider-account and upstream revisions retain their
parents. Each database applies only the branch it has not already recorded.
"""

revision: str = "0336_merge_core_v1761"
down_revision: tuple[str, str] = (
    "0331_merge_core_accounts",
    "0332_merge_t3_pools_v1761",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
