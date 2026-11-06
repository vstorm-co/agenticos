"""Join proactivity and connected-account upgrades without rewriting either history."""

revision: str = "0292_merge_connected_accounts"
down_revision: tuple[str, str] = ("0291_chat_waiver_default", "0257_connected_accounts")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
