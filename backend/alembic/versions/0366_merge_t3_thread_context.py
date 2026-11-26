"""Join upstream v1930 with the independently prepared room thread context chain.

Both histories extend `0356_trigger_webhook_receipts`; this no-op revision keeps
the upstream v1930 merge and `0358_room_thread_context` reachable without
rewriting either revision.
"""

revision: str = "0366_merge_t3_thread_context"
down_revision: tuple[str, str] = (
    "0365_merge_t3_v1930",
    "0358_room_thread_context",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
