"""Retain the unreleased core checkpoint after the canonical published threads.

Published room threads already descend from the coding-account and upstream
branches. The remaining draft features therefore form one chain. This empty
checkpoint retains the identity used by the pending feature branch.
"""

from collections.abc import Sequence

revision: str = "0331_merge_core_accounts"
down_revision: str = "0330_role_navigation"
branch_labels: None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
