"""Persist server-owned draft provenance, independent of provider-controlled result text."""

import sqlalchemy as sa

from alembic import op

revision: str = "0294_tool_presentation"
down_revision: str = "0293_connected_account_sources"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("presentation_kind", sa.String(16), nullable=True))
    op.execute("""
        UPDATE tool_calls AS call SET presentation_kind = 'draft'
        FROM messages AS message JOIN agent_versions AS version ON version.id = message.agent_version_id
        WHERE call.message_id = message.id AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(COALESCE(version.spec->'capabilities', '[]'::jsonb)) AS binding
            WHERE binding->>'id' = 'drafts'
            AND COALESCE((binding->>'enabled')::boolean, true)
            AND call.tool_name = COALESCE(binding->'tool_overrides'->'write_draft'->>'name', 'write_draft')
        )
    """)


def downgrade() -> None:
    op.drop_column("tool_calls", "presentation_kind")
