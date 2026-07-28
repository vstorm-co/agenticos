"""Enforce organization scope on conversations and knowledge bases

Revision ID: 0027_enforce_org_scope
Revises: 0026_create_mcp_connections
Create Date: 2026-07-26

Every user gets a Personal organization at registration, so a conversation that
belongs to a user always has an owning org - the column being nullable is a
leftover from before teams existed and lets a run escape org scoping.

``organization_id`` cannot simply become NOT NULL: channel conversations
(Slack/Telegram, ``services/channels/router.py``) are created with
``user_id=None`` and have no org until channel bots become org-aware. The CHECK
below states the invariant that actually holds today - a *user-owned*
conversation must carry an organization.

Knowledge bases get the matching rule: ``org``-scoped rows must name an
organization, while ``personal`` and ``app`` scopes legitimately carry none.
Both constraints already hold in the service layer; this makes the database
refuse to store a violation regardless of the code path that writes it.
"""

import sqlalchemy as sa

from alembic import op

revision = "0027_enforce_org_scope"
down_revision = "0026_create_mcp_connections"
branch_labels = None
depends_on = None

CONVERSATION_ORG_CHECK = "ck_conversations_user_rows_have_org"
KB_ORG_CHECK = "ck_knowledge_bases_org_scope_has_org"


def upgrade() -> None:
    conn = op.get_bind()

    # Idempotent - repeats 0006 to cover conversations created between the two
    # migrations by code paths that did not set the org.
    conn.execute(
        sa.text("""
        UPDATE conversations
        SET organization_id = o.id
        FROM organizations o
        WHERE conversations.user_id = o.created_by_user_id
          AND o.is_personal = TRUE
          AND conversations.organization_id IS NULL
    """)
    )

    op.create_check_constraint(
        CONVERSATION_ORG_CHECK,
        "conversations",
        "user_id IS NULL OR organization_id IS NOT NULL",
    )
    op.create_check_constraint(
        KB_ORG_CHECK,
        "knowledge_bases",
        "scope <> 'org' OR organization_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(KB_ORG_CHECK, "knowledge_bases", type_="check")
    op.drop_constraint(CONVERSATION_ORG_CHECK, "conversations", type_="check")
