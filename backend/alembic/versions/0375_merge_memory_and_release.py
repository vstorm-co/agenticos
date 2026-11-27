"""Join the memory ledger and the main release schema."""

revision: str = "0375_merge_memory_and_release"
down_revision: tuple[str, str] = (
    "0369_memory_inbox_and_objects",
    "0374_case_from_conversation",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
