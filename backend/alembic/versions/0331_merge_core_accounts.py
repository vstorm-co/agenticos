"""Join the recovered core features and the published coding-account branch.

Both parents retain their original revision ids and own their schema changes.
This revision only joins the histories; neither branch is renamed or replayed.
"""

from collections.abc import Sequence

revision: str = "0331_merge_core_accounts"
down_revision: tuple[str, str] = (
    "0326_provider_account_pools",
    "0330_role_navigation",
)
branch_labels: None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
