"""Join the T3 provider-account history with the pinned v1.76.1 migration head.

The release branch already joins the coding-task history, while the deployed
T3 head adds provider-account pools after the earlier room merge. This revision
adds no schema changes; it keeps both upgrade paths reachable without renumbering
an applied revision.
"""

revision: str = "0331_merge_t3_rooms_and_v1761"
down_revision: tuple[str, str] = (
    "0330_linear_trigger",
    "0326_provider_account_pools",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
