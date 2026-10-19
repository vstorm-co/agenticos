"""OAuth 2.1 for the platform's MCP server (#2059).

Registered clients, pending consents, grants, single-use authorization codes and
rotating refresh tokens. An access token is an `api_keys` row, which gains the
grant it was issued under.

Revision ID: 0108_oauth_for_mcp
Revises: 0107_api_keys
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0108_oauth_for_mcp"
down_revision: str | None = "0107_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("info", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("client_id", name=op.f("oauth_clients_pkey")),
    )
    op.create_table(
        "oauth_authorization_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("oauth_authorization_requests_client_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("oauth_authorization_requests_pkey")),
    )
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.client_id"],
            name=op.f("oauth_grants_client_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("oauth_grants_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("oauth_grants_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("oauth_grants_pkey")),
    )
    op.create_index(op.f("oauth_grants_client_id_idx"), "oauth_grants", ["client_id"], unique=False)
    op.create_index(
        op.f("oauth_grants_organization_id_idx"), "oauth_grants", ["organization_id"], unique=False
    )
    op.create_index(op.f("oauth_grants_user_id_idx"), "oauth_grants", ["user_id"], unique=False)
    op.create_table(
        "oauth_authorization_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grants.id"],
            name=op.f("oauth_authorization_codes_grant_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("code_hash", name=op.f("oauth_authorization_codes_pkey")),
    )
    op.create_index(
        op.f("oauth_authorization_codes_grant_id_idx"),
        "oauth_authorization_codes",
        ["grant_id"],
        unique=False,
    )
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.UUID(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grants.id"],
            name=op.f("oauth_refresh_tokens_grant_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("oauth_refresh_tokens_pkey")),
    )
    op.create_index(
        op.f("oauth_refresh_tokens_grant_id_idx"),
        "oauth_refresh_tokens",
        ["grant_id"],
        unique=False,
    )
    op.add_column("api_keys", sa.Column("oauth_grant_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("api_keys_oauth_grant_id_idx"), "api_keys", ["oauth_grant_id"], unique=False
    )
    op.create_foreign_key(
        op.f("api_keys_oauth_grant_id_fkey"),
        "api_keys",
        "oauth_grants",
        ["oauth_grant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("api_keys_oauth_grant_id_fkey"), "api_keys", type_="foreignkey")
    op.drop_index(op.f("api_keys_oauth_grant_id_idx"), table_name="api_keys")
    op.drop_column("api_keys", "oauth_grant_id")
    op.drop_index(op.f("oauth_refresh_tokens_grant_id_idx"), table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_index(
        op.f("oauth_authorization_codes_grant_id_idx"), table_name="oauth_authorization_codes"
    )
    op.drop_table("oauth_authorization_codes")
    op.drop_index(op.f("oauth_grants_user_id_idx"), table_name="oauth_grants")
    op.drop_index(op.f("oauth_grants_organization_id_idx"), table_name="oauth_grants")
    op.drop_index(op.f("oauth_grants_client_id_idx"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_authorization_requests")
    op.drop_table("oauth_clients")
