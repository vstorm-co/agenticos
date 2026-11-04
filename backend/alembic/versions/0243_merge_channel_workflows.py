"""Join released channel/Architect updates with workflow schema changes.

Neither branch rewrites the other's applied history. Upgrading an existing workflow
installation applies the released channel migrations before recording this merge.

Revision ID: 0243_merge_channel_workflows
Revises: 0242_workflow_entry_triggers, 0183_channel_prompt_defaults
"""

from collections.abc import Sequence

revision: str = "0243_merge_channel_workflows"
down_revision: str | Sequence[str] | None = (
    "0242_workflow_entry_triggers",
    "0183_channel_prompt_defaults",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
