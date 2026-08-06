"""A parked tool call has three endings, not four

Revision ID: 0011_drop_expired_approval
Revises: 0010_message_run_id
Create Date: 2026-08-06

`ApprovalStatus.EXPIRED` was defined and permitted by `ck_tool_approval_status`,
and nothing in the application ever assigned it. Those two lines were its only
occurrences. So the schema promised a ceiling on the approvals queue that did not
exist: a call nobody decides stays `pending` indefinitely, its run stays parked in
`awaiting_approval`, and nothing escalates or settles either of them.

Removed rather than implemented. Expiry is a designed feature, not a missing line
- what should happen to a parked run whose approval lapses (fail it, cancel it,
re-ask the person) is a product decision nobody has made, and inventing one in
order to retire an enum value would be the worse of the two mistakes. The Activity
page surfaces the *age* of the oldest wait instead, which is the honest answer
while there is no ceiling.

No data migration, and the constraint is what makes that safe to assert rather
than assume: `'expired'` has been permitted since the baseline and assigned by
nothing, so no row can hold it. The narrowed CHECK would fail loudly on this
migration if one did, which is the correct outcome - a silent `UPDATE ... SET
status = 'rejected'` would rewrite somebody's audit trail to make a schema change
go through.

Postgres cannot narrow a CHECK in place, so it is dropped and recreated. The
`downgrade` restores the four-value version exactly, because a fork that ran the
old chain has rows validated against it.
"""

from alembic import op

revision = "0011_drop_expired_approval"
down_revision = "0010_message_run_id"
branch_labels = None
depends_on = None

# The name the metadata's `ck` convention produced, which is what is actually in
# the database - not the bare `ck_tool_approval_status` the model declares.
_CONSTRAINT = "tool_approvals_ck_tool_approval_status_check"


def upgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "tool_approvals", type_="check")
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "tool_approvals",
        "status IN ('pending', 'approved', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "tool_approvals", type_="check")
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "tool_approvals",
        "status IN ('pending', 'approved', 'rejected', 'expired')",
    )
