"""Remember a person's explicitly scoped tool approval."""

import sqlalchemy as sa

from alembic import op

revision: str = "0295_tool_approval_consent"
down_revision: str = "0294_tool_presentation"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("tool_approvals", sa.Column("remember_scope", sa.String(16), nullable=True))
    op.create_index(
        "ix_tool_approval_consent",
        "tool_approvals",
        ["organization_id", "decided_by_user_id", "tool_id"],
        postgresql_where=sa.text("remember_scope IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_tool_approval_consent",
        "tool_approvals",
        "remember_scope IS NULL OR (remember_scope IN ('conversation', 'agent') AND status = 'approved' AND decided_via = 'click')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tool_approval_consent", "tool_approvals", type_="check")
    op.drop_index("ix_tool_approval_consent", "tool_approvals")
    op.drop_column("tool_approvals", "remember_scope")
