"""An embed can also be a page we serve, and a visitor can come back to it.

The hosted chat page (#517) is not a second kind of object. It is an embed -
same public key, same auth mode, same rate bucket, budget and pause switch -
rendered as a page of ours instead of a bubble in the corner of somebody else's
site. So this revision adds a flag and a branding blob to `agent_embeds` rather
than a table beside it: a second table would be a second place for "who may
reach this agent" to be answered, and two answers drifting apart is what #39 was
about.

**`ck_embed_hosted_is_public` is the half a refactor cannot argue with.** A
hosted page's link travels in browser history, in `Referer` headers and in every
chat client somebody pastes it into, so `jwt` mode would mean a visitor token
travelling through all three. The service refuses the combination at enable time
with a message a person can act on; the constraint is what holds when a future
call site forgets to ask.

`embed_visitors` is the continuity `agent_embeds` cannot carry, and it is shaped
after `channel_sessions` for the same reason: "which conversation does this
person come back to" is a question about a surface's identity model, and putting
it on `conversations` would put one surface's answer on the table every surface
writes to. `conversation_id` is `SET NULL` rather than `CASCADE` - a conversation
removed by a retention sweep must leave the visitor able to start a new one, not
delete the visitor.

No backfill. `hosted` arrives false for every existing row, `hosted_config`
arrives empty and `HostedConfig` fills its own defaults, and the new `url_safe`
flag on a declared variable is an *added* JSONB key rather than a narrowed rule -
a stored variable without it validates to `False`, which is the safe answer. The
one rule that is new (`required` implies `url_safe`) applies only where hosting
is on, and nothing is hosted yet.

Revision ID: 0022_hosted_embeds
Revises: 0021_drop_channel_tools_bindings
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_hosted_embeds"
down_revision: str | Sequence[str] | None = "0021_drop_channel_tools_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_embeds",
        sa.Column("hosted", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "agent_embeds",
        sa.Column(
            "hosted_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("agent_embeds_ck_embed_hosted_is_public_check"),
        "agent_embeds",
        "NOT hosted OR auth_mode = 'public'",
    )

    op.create_table(
        "embed_visitors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("embed_id", sa.UUID(), nullable=False),
        sa.Column("visitor_key", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("embed_visitors_conversation_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["embed_id"],
            ["agent_embeds.id"],
            name=op.f("embed_visitors_embed_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("embed_visitors_pkey")),
        sa.UniqueConstraint("embed_id", "visitor_key", name="uq_embed_visitor_key"),
    )
    op.create_index(
        op.f("embed_visitors_conversation_id_idx"),
        "embed_visitors",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("embed_visitors_embed_id_idx"), "embed_visitors", ["embed_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("embed_visitors_embed_id_idx"), table_name="embed_visitors")
    op.drop_index(op.f("embed_visitors_conversation_id_idx"), table_name="embed_visitors")
    op.drop_table("embed_visitors")
    op.drop_constraint(
        op.f("agent_embeds_ck_embed_hosted_is_public_check"), "agent_embeds", type_="check"
    )
    op.drop_column("agent_embeds", "hosted_config")
    op.drop_column("agent_embeds", "hosted")
