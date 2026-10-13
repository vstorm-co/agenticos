"""A chat session may waive approvals, and a row says when one did (#925).

`ApprovalMode.APPROVE_ALL` is standing consent for one conversation: every gated
tool call is granted without parking, and each one still writes its row naming
who consented. That is a real waiver of the thing the approval queue exists to
record, so it needs a ceiling somebody set deliberately - without one, a
Builder's gate on `send_email` is one click from nothing in every conversation
and the whole per-tool approval model is advisory.

**Off by default, and the default is the decision.** Switching this on is an
organization saying that waiving is allowed at all; who may then do it is
`approvals:decide`, a separate question already answered. So an upgrade changes
nobody's behaviour: the control does not render until an owner turns it on.

Not a deployment setting: two organizations on one deployment have different
appetites for this, and the rest of an organization's governance - its monthly
cap - is a column on this table for the same reason.

`tool_approvals.decided_via` is the other half. A call granted in advance is
written `approved` like any other, and without a marker a waived run is
indistinguishable from an agent that was never gated - which is the audit trail
`docs/governance.md` describes quietly ceasing to be one. Every existing row is
`click`, because every decision so far was somebody pressing a button.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0062_org_chat_approval_waiver"
down_revision: str | None = "0061_session_last_used_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "chat_may_waive_approvals",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tool_approvals",
        sa.Column(
            "decided_via",
            sa.String(length=16),
            nullable=False,
            server_default="click",
        ),
    )
    op.create_check_constraint(
        "ck_tool_approval_decided_via",
        "tool_approvals",
        "decided_via IN ('click', 'standing')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tool_approval_decided_via", "tool_approvals", type_="check")
    op.drop_column("tool_approvals", "decided_via")
    op.drop_column("organizations", "chat_may_waive_approvals")
