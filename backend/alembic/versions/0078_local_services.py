"""Local services: the deployment-network addresses a collection may be pointed at.

`EMBEDDING_OLLAMA_BASE_URL` and `LITEPARSE_OCR_SERVER_URL` were one address each for
the whole deployment, set in the environment where no tenant could see or change
them. They become rows an organization - or the deployment's administrator, for
every organization and for app-scoped collections - registers in the product, and a
knowledge base names its embedding service by id the way it names a vault key
(#1631, #1632).

Revision ID: 0078_local_services
Revises: 0077_drop_allow_byo
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0078_local_services"
down_revision: str | None = "0077_drop_allow_byo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "local_services",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('embedding', 'ocr')", name="ck_local_services_kind"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="local_services_created_by_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="local_services_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="local_services_pkey"),
    )
    op.create_index(
        "local_services_organization_id_idx", "local_services", ["organization_id"], unique=False
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("embedding_endpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "knowledge_bases_embedding_endpoint_id_idx",
        "knowledge_bases",
        ["embedding_endpoint_id"],
        unique=False,
    )
    op.create_foreign_key(
        "knowledge_bases_embedding_endpoint_id_fkey",
        "knowledge_bases",
        "local_services",
        ["embedding_endpoint_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "knowledge_bases_embedding_endpoint_id_fkey", "knowledge_bases", type_="foreignkey"
    )
    op.drop_index("knowledge_bases_embedding_endpoint_id_idx", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "embedding_endpoint_id")
    op.drop_index("local_services_organization_id_idx", table_name="local_services")
    op.drop_table("local_services")
