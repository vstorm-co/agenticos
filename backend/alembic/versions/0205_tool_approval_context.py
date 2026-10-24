"""The names a parked tool call's ids stand for, for the person deciding it.

An approval stores the tool's arguments, and for a tool that takes ids those are
all a person sees: `share_view` asks to share `view_id: 6f1c…`, a table write
names `table_id` and `record_id`. `tool_approvals.context` holds those ids as
names - `{"view": "Closed tickets", "table": "Support"}` - resolved by the
tool's describer as the run's person when the call was parked, so the chat card
and the queue can put the request into a sentence above the arguments.

Stored rather than resolved when the queue is read: the queue is read by an
approver, who is not the person the run acts for, and resolving there would
either show names through the approver's access or need the run's person
rebuilt per row. Resolving once at park time, as the person, answers both.

Nullable JSONB with no default: null is "the tool has no describer, or
describing it failed", and the arguments stay the record either way. No
backfill - a row parked before this has nothing that resolved its ids, and
resolving them now would name things as they are today rather than as they
were asked about.

Revision ID: 0205_tool_approval_context
Revises: 0204_artifact_restored_from
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0205_tool_approval_context"
down_revision: str | None = "0204_artifact_restored_from"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_approvals",
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_approvals", "context")
