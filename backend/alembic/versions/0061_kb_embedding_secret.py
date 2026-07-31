"""A collection can embed on the organization's own key

Revision ID: 0061_kb_embedding_secret
Revises: 0060_agent_environments
Create Date: 2026-07-30

The embedding model was already per collection - recorded with its width at
creation. The credential was not: every collection embedded on the deployment's
`OPENROUTER_API_KEY`. This column lets a collection name one of the
organization's vault keys instead; NULL keeps the deployment key, which is what
every existing collection has always used, so there is nothing to backfill.

SET NULL on delete: losing a key must degrade billing to the deployment's key,
never take document search down.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0061_kb_embedding_secret"
down_revision = "0060_agent_environments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "embedding_secret_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "organization_secrets.id",
                ondelete="SET NULL",
                name="knowledge_bases_embedding_secret_id_fkey",
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "embedding_secret_id")
