"""Make ownerless org knowledge bases org-visible before visibility is enforced

Revision ID: 0063_kb_org_visibility
Revises: 0062_two_budget_levels
Create Date: 2026-07-30

Until now the `/kb` read and write paths reduced to "is the caller a member of
the row's organization" - the `visibility` column existed, was settable through
the sharing routes, and was never consulted. That is fixed in the same change
as this migration: org-scoped rows now resolve through
`app.services.access.resolve_access`, exactly as agents, skills and secrets do.

Enforcing a rule on rows written under the old one changes what those rows
mean. Every org-scoped knowledge base created so far is ownerless (the service
set `owner_user_id` only for personal scope) and carries the column default
`'private'` - a combination the new rule reads as "reachable only by roles
whose `collections:view` spans the organization". A Member would lose the
default knowledge base their workspace was bootstrapped with, and nobody chose
that: private was the default, not a decision, and there is no owner whose
choice it could have been.

So ownerless private org rows become `'org'`, which is precisely the reach
they actually had. Rows with an explicit `'team'` visibility are left alone,
and rows that gain owners are only created after this change, so the
owner-null predicate cleanly separates "written under the old rule" from
"written under the new one".

Irreversible in the meaningful sense: the old state carried no information
(every such row was `'private'`), so downgrade restores the literal value.
"""

from alembic import op

revision = "0063_kb_org_visibility"
down_revision = "0062_two_budget_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE knowledge_bases SET visibility = 'org' "
        "WHERE scope = 'org' AND owner_user_id IS NULL AND visibility = 'private'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE knowledge_bases SET visibility = 'private' "
        "WHERE scope = 'org' AND owner_user_id IS NULL AND visibility = 'org'"
    )
