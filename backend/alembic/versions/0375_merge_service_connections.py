"""Join the service-connection and conversation-privacy release histories.

Both branches preserve their already-published revision identities. Their schema
changes are independent; joining them requires no data rewrite.
"""

from collections.abc import Sequence

revision: str = "0375_merge_service_connections"
down_revision: tuple[str, str] = (
    "0374_case_from_conversation",
    "0367_embedding_probe_spend",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
