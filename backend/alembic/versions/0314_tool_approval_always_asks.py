"""Record on each tool approval whether only a person's answer could let it run.

A constant default on a new column is a catalog change in PostgreSQL 11 and
later: existing rows are not rewritten, so the column itself is instant on any
size of `tool_approvals`. A call parked before this revision is still waiting
and never expires, so the pending ones that always ask are marked too: every
`share_memory` call, and a `correct_memory` call naming an organization or
project fact. Both updates start from pending rows, through the status index;
the claim id is the model's own argument, so one that is not a UUID matches
nothing rather than failing the cast.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0314_tool_approval_always_asks"
down_revision: str = "0306_shared_page_attribution"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "tool_approvals",
        sa.Column("always_asks", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE tool_approvals SET always_asks = true "
        "WHERE status = 'pending' AND capability_tool_id = 'share_memory'"
    )
    op.execute(
        "UPDATE tool_approvals AS approval SET always_asks = true "
        "FROM memory_claims AS claim "
        "WHERE approval.status = 'pending' "
        "AND approval.capability_tool_id = 'correct_memory' "
        "AND claim.id = CASE WHEN approval.tool_args->>'claim_id' ~* "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
        "THEN (approval.tool_args->>'claim_id')::uuid END "
        "AND claim.organization_id = approval.organization_id "
        "AND (claim.scope_key LIKE 'org:%' OR claim.scope_key LIKE 'project:%')"
    )


def downgrade() -> None:
    op.drop_column("tool_approvals", "always_asks")
