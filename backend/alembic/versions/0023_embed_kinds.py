"""One kind per embed, and one config column instead of three.

`0022` gave an embed a `hosted` boolean and a second config column beside its
`theme`, so a row carried three columns saying what it was: a flag, a widget
theme it might not use, and a page config it might not use either. The product
that sat on top read as one surface with an option, which is how somebody
looking for the WebSocket and the hosted page found neither - both were behind
"Publish as widget", which is not what either of them is.

So the surface is a `kind` - `widget`, `socket` or `page` - and the half of the
configuration that depends on it is one JSONB column holding a discriminated
union. Three columns encoding what one says once is three places to disagree,
and this is the change that removes two of them.

Two rules that were service-side become constraints, because both are about what
a row *is* rather than about how it was submitted:

- a `page` is `public` (carried over from `0022`, restated in terms of `kind`);
- a `page` has no allowed-origins list, because an allow-list is a rule about
  other people's sites and this one is ours. A list on a page is either dead
  configuration or somebody's belief that it is what protects the link.

Existing rows convert without a decision to make: a `hosted` row becomes a
`page`, everything else a `widget`, and a page's origin list is emptied, since
`0022` never let one be admitted by it. No row can become a `socket` - nothing
before this revision could express one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0023_embed_kinds"
down_revision: str | Sequence[str] | None = "0022_hosted_embeds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_embeds", sa.Column("kind", sa.String(length=16), nullable=True))
    op.add_column("agent_embeds", sa.Column("config", JSONB(), nullable=True))

    # A hosted row was a widget that also served a page; it becomes the page,
    # because that is the integration its owner went looking for. Its theme is
    # dropped rather than merged - a launcher label and a corner to sit in have
    # no meaning on a full page, and `hosted_config` already holds what does.
    op.execute(
        """
        UPDATE agent_embeds
           SET kind = 'page',
               config = jsonb_build_object('kind', 'page') || COALESCE(hosted_config, '{}'::jsonb),
               allowed_origins = '[]'::jsonb
         WHERE hosted
        """
    )
    op.execute(
        """
        UPDATE agent_embeds
           SET kind = 'widget',
               config = jsonb_build_object('kind', 'widget') || COALESCE(theme, '{}'::jsonb)
         WHERE NOT hosted
        """
    )

    op.alter_column("agent_embeds", "kind", nullable=False)
    op.alter_column("agent_embeds", "config", nullable=False)

    op.drop_constraint("ck_embed_hosted_is_public", "agent_embeds", type_="check")
    op.drop_column("agent_embeds", "hosted")
    op.drop_column("agent_embeds", "hosted_config")
    op.drop_column("agent_embeds", "theme")

    op.create_check_constraint(
        "ck_embed_kind", "agent_embeds", "kind IN ('widget', 'socket', 'page')"
    )
    op.create_check_constraint(
        "ck_embed_page_is_public", "agent_embeds", "kind <> 'page' OR auth_mode = 'public'"
    )
    op.create_check_constraint(
        "ck_embed_page_has_no_origins",
        "agent_embeds",
        "kind <> 'page' OR allowed_origins = '[]'::jsonb",
    )


def downgrade() -> None:
    op.drop_constraint("ck_embed_page_has_no_origins", "agent_embeds", type_="check")
    op.drop_constraint("ck_embed_page_is_public", "agent_embeds", type_="check")
    op.drop_constraint("ck_embed_kind", "agent_embeds", type_="check")

    op.add_column(
        "agent_embeds",
        sa.Column("hosted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_embeds",
        sa.Column("theme", JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "agent_embeds",
        sa.Column("hosted_config", JSONB(), nullable=False, server_default="{}"),
    )

    # A `socket` has no shape on the old schema, so it goes back as the widget it
    # would have been - an unhosted embed with an empty theme. Nothing is lost
    # that the old schema could have held.
    op.execute(
        """
        UPDATE agent_embeds
           SET hosted = TRUE,
               hosted_config = config - 'kind'
         WHERE kind = 'page'
        """
    )
    op.execute(
        """
        UPDATE agent_embeds
           SET theme = config - 'kind'
         WHERE kind <> 'page'
        """
    )

    op.create_check_constraint(
        "ck_embed_hosted_is_public", "agent_embeds", "NOT hosted OR auth_mode = 'public'"
    )
    op.drop_column("agent_embeds", "config")
    op.drop_column("agent_embeds", "kind")
