"""Keep named personal coding containers tied to their account and source.

The nullable account association leaves existing workspaces unchanged. Tenant
foreign keys prevent binding another organization's credential; the check keeps
personal files out of project, agent and shared-channel workspaces. Account and
conversation removal can now find retained remote sessions before cascading rows.
Only metadata is stored here; credentials remain in the user-scoped vault.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0342_personal_coding_sessions"
down_revision: str = "0343_solution_installations"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_coding_account_org_id", "coding_accounts", ["organization_id", "id"]
    )
    op.add_column("agent_workspaces", sa.Column("coding_account_id", sa.UUID(), nullable=True))
    op.add_column(
        "agent_workspaces", sa.Column("coding_source_revision", sa.String(64), nullable=True)
    )
    op.create_index(
        "agent_workspaces_coding_account_id_idx", "agent_workspaces", ["coding_account_id"]
    )
    op.create_foreign_key(
        "fk_agent_workspace_coding_account_tenant",
        "agent_workspaces",
        "coding_accounts",
        ["organization_id", "coding_account_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_agent_workspace_personal_coding_private",
        "agent_workspaces",
        "coding_account_id IS NULL OR (scope = 'user' AND backend = 'service' "
        "AND owner_ref IS NOT NULL AND conversation_id IS NOT NULL AND project_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("agent_workspaces_ck_agent_workspace_personal_coding_private_check"),
        "agent_workspaces",
        type_="check",
    )
    op.drop_constraint(
        "fk_agent_workspace_coding_account_tenant", "agent_workspaces", type_="foreignkey"
    )
    op.drop_index("agent_workspaces_coding_account_id_idx", table_name="agent_workspaces")
    op.drop_column("agent_workspaces", "coding_source_revision")
    op.drop_column("agent_workspaces", "coding_account_id")
    op.drop_constraint("uq_coding_account_org_id", "coding_accounts", type_="unique")
