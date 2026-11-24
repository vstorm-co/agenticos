"""Join coding-account pools without rewriting the published upstream merge.

Keeping the earlier merge unchanged lets a database already at revision 0331
still apply the provider-account pool schema before reaching the combined head.
Both the existing T3 pool history and the upstream history remain reachable.
"""

revision: str = "0332_merge_t3_pools_v1761"
down_revision: tuple[str, str] = (
    "0331_merge_t3_rooms_and_v1761",
    "0326_provider_account_pools",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
