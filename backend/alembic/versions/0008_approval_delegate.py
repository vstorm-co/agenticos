"""Which delegate an approval belongs to

Revision ID: 0008_approval_delegate
Revises: 0007_delegated_runs
Create Date: 2026-08-05

A delegate whose tool needs a person reaches the *parent's* approval channel -
that is what makes a gated tool inside a delegate usable at all, because the
delegation holds the parent's tool call and there is a person already waiting.
The row that channel writes therefore names the tool correctly (`send_email`,
with its arguments, written by the delegate's own gate) and says nothing about
who is sending it. `agent_id` on the row is the agent whose *run* it is - what
the queue is scoped by, and what a budget alert names - so it cannot answer
"who is acting" as well.

Two columns, and the split between them is not redundancy. `subagent_name` is
what a reviewer reads and is set for every delegated ask, including an inline
specialist's: a specialist is defined inside its parent's spec, is not
versioned, and nothing outside that spec can reference it, so it has no agent id
to record. `subagent_agent_id` is set only for a published delegate, and is what
a queue links to.

Both nullable, and null is the common case: an approval raised by the agent
whose run it is - every approval on a run that did not delegate - carries
neither. Backfill would be guesswork; rows written before this could have come
from either side, and marking them all as the run's own agent would assert
something nobody checked.

`ON DELETE SET NULL` on the delegate, not CASCADE. Deleting the delegate must
not delete the record of what somebody authorised it to do; the decision, its
arguments and who made it are the audit trail.

No index. The queue is read by `(organization_id, status)`, which
`ix_tool_approvals_org_status` already serves, and "what has this delegate been
asked to do" is a question nobody has yet - one answered by a scan of a
single organization's approvals if it arrives.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_approval_delegate"
down_revision = "0007_delegated_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_approvals", sa.Column("subagent_name", sa.String(length=64), nullable=True))
    op.add_column(
        "tool_approvals",
        sa.Column("subagent_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("tool_approvals_subagent_agent_id_fkey"),
        "tool_approvals",
        "agents",
        ["subagent_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("tool_approvals_subagent_agent_id_fkey"), "tool_approvals", type_="foreignkey"
    )
    op.drop_column("tool_approvals", "subagent_agent_id")
    op.drop_column("tool_approvals", "subagent_name")
