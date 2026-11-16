"""Keep pending corrections of shared memory waiting for a person.

0314 is already deployed. Apply the additional data repair in a new revision;
malformed model-supplied claim ids match nothing rather than failing the cast.
"""

from alembic import op

revision: str = "0318_wide_memory_approvals"
down_revision: str = "0317_opensandbox_connections"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
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
    # Keep the stricter consent on a parked call; its origin is not recorded.
    pass
