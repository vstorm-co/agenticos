"""Retain the unreleased core release checkpoint without replaying published DDL.

The canonical published room-thread revision already includes the upstream and
provider-account histories. Only the unreleased draft lineage was reconciled;
every published migration and its parents remain unchanged.
"""

revision: str = "0336_merge_core_v1761"
down_revision: str = "0331_merge_core_accounts"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
