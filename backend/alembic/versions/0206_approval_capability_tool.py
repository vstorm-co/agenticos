"""The stable id of a parked call's tool, beside the name the model called.

`tool_approvals.tool_id` holds the tool's *effective* name - what the model
called, which a binding's `tool_overrides` may have renamed. The card and the
queue word a parked call by tool, from `0205_tool_approval_context.py`'s
`context`, and looked that wording up by the name: a renamed `share_view` lost
its sentence. `capability_tool_id` is the id the capability declares the tool
under, which no rename touches.

A column of its own rather than a key inside `context`: `context` is the
arguments' ids as names, read by a person, and a tool id is neither. Renaming
`tool_id` instead would change what every existing row, client and audit entry
means by it.

Nullable with no default: null is a tool no capability owns - an MCP server's,
gated under `ApprovalMode.ASK_ALL` - and every row parked before this. No
backfill: the binding that named a parked call may have been republished since,
so the id read off today's spec could name a different tool.

Revision ID: 0206_approval_capability_tool
Revises: 0205_tool_approval_context
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0206_approval_capability_tool"
down_revision: str | None = "0205_tool_approval_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_approvals",
        sa.Column("capability_tool_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_approvals", "capability_tool_id")
