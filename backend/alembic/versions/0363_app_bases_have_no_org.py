"""An app-scoped knowledge base belongs to no organization.

Clear the organization id an app-scoped row still carries, then forbid one with a
check beside the one requiring it on an org-scoped row. Downgrade drops the check
only: which organization each row named is not recorded anywhere to restore.
"""

from alembic import op

revision: str = "0363_app_bases_have_no_org"
down_revision: str = "0362_merge_native_release"
branch_labels: None = None
depends_on: None = None

CHECK = "knowledge_bases_ck_knowledge_bases_app_scope_has_no_org_check"


def upgrade() -> None:
    op.execute(
        "UPDATE knowledge_bases SET organization_id = NULL "
        "WHERE scope = 'app' AND organization_id IS NOT NULL"
    )
    op.create_check_constraint(
        op.f(CHECK), "knowledge_bases", "scope <> 'app' OR organization_id IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(CHECK), "knowledge_bases", type_="check")
