"""Join the T3 and upstream v1.73.0 migration histories.

The merge adds no schema; both independent histories remain in place.
"""

revision: str = "0324_merge_t3_upstream_v173"
down_revision: tuple[str, str] = (
    "0323_coding_revert_admission",
    "0303_virtual_table_row_policy",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
