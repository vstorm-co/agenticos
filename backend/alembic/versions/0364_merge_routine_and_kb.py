"""Join private-chat routine delivery and app-wide knowledge-base isolation."""

revision: str = "0364_merge_routine_and_kb"
down_revision: tuple[str, str] = (
    "0363_trigger_delivery_pending",
    "0363_app_bases_have_no_org",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
