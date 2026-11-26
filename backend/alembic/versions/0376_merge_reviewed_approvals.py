"""Join service connections and durable platform-call approval provenance."""

from collections.abc import Sequence

revision: str = "0376_merge_reviewed_approvals"
down_revision: tuple[str, ...] = (
    "0375_merge_service_connections",
    "0375_tool_approval_platform_call",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
