"""Keep principal-scoped solution receipts in the resources' own transaction.

An installation either commits all private drafts and this receipt, or neither.
The manifest is not retained: only its hash and resulting resource identities.
Organization and account deletion cascade the receipts. Downgrade removes the
receipts, not resources users may have edited since installation.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0343_solution_installations"
down_revision: str = "0342_criterion_verdicts"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "solution_installations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("installation_key", sa.String(48), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("resources", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", "installation_key"),
    )


def downgrade() -> None:
    op.drop_table("solution_installations")
