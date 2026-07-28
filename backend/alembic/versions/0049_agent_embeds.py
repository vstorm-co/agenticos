"""Agent embeds — one agent published as a widget for somebody else's site

Revision ID: 0049_agent_embeds
Revises: 0048_mattermost
Create Date: 2026-07-28

The constraints are the interesting part, and each one closes a failure that is
silent rather than loud:

`ck_embed_jwt_needs_secret` — an embed in `jwt` mode with no secret cannot
verify a token. The dangerous reading is not "everything is rejected", it is a
later refactor treating a missing secret as "no check required".

`ck_embed_rate_limit_positive` — a limit of zero is not a stricter limit, it is
a widget that can never answer, and somebody would reach it by clearing a field
rather than by deciding to.

`public_key` is unique and indexed because it is the only thing a request from
the public internet carries; it is looked up on every message.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0049_agent_embeds"
down_revision = "0048_mattermost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_embeds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("auth_mode", sa.String(length=16), nullable=False, server_default="public"),
        sa.Column("jwt_secret_encrypted", sa.String(length=1000), nullable=True),
        sa.Column(
            "allowed_origins", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("theme", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "rate_limit_per_minute", sa.Integer(), nullable=False, server_default=sa.text("10")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("auth_mode IN ('public', 'jwt')", name="ck_embed_auth_mode"),
        sa.CheckConstraint("rate_limit_per_minute > 0", name="ck_embed_rate_limit_positive"),
        sa.CheckConstraint(
            "auth_mode <> 'jwt' OR jwt_secret_encrypted IS NOT NULL",
            name="ck_embed_jwt_needs_secret",
        ),
    )
    op.create_index("ix_agent_embeds_organization_id", "agent_embeds", ["organization_id"])
    op.create_index("ix_agent_embeds_agent_id", "agent_embeds", ["agent_id"])
    op.create_index("ix_agent_embeds_public_key", "agent_embeds", ["public_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_agent_embeds_public_key", table_name="agent_embeds")
    op.drop_index("ix_agent_embeds_agent_id", table_name="agent_embeds")
    op.drop_index("ix_agent_embeds_organization_id", table_name="agent_embeds")
    op.drop_table("agent_embeds")
