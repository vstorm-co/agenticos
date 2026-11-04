"""Join main's deployment diagnostics and the workflow conversation chain."""

from collections.abc import Sequence

revision: str = "0247_merge_deployment_workflows"
down_revision: tuple[str, str] = ("0184_diagnostics_identity", "0246_workflow_agent_chats")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
