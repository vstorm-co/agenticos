"""Join the T3 room history with the pinned v1.76.1 migration head.

The release branch already joins the coding-task history, while the deployed
T3 head is the earlier room merge. This revision adds no schema changes; it
keeps both upgrade paths reachable without renumbering an applied revision.
"""

revision: str = "0331_merge_t3_rooms_and_v1761"
down_revision: tuple[str, str] = (
    "0330_linear_trigger",
    "0325_merge_t3_rooms_v173",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
