"""A hosted page's microphone becomes `dictation: off | browser | server` (#1797).

`PageConfig.allow_voice` was a yes/no for the browser's own speech recognition.
Server dictation adds a third answer, and the widget gains the same setting, so
the boolean is withdrawn in favour of `dictation`: `true` was the browser's
recogniser and becomes `browser`, `false` becomes `off`.

A data migration rather than only a validator, and the reason is that a missed
row fails **silently**, not with a 500. The config schema does not forbid extra
keys, so a stored `allow_voice` would simply be ignored - the page would lose its
microphone with nothing said - and the next time the config is re-dumped (a logo
upload rewrites it) the old key would be gone and the setting with it. The
`mode="before"` validator on `PageConfig` reads the old key too, for anything
that reaches the model without passing through here; the two agree, and the
`UPDATE` is idempotent because it skips a row that already names `dictation`.

Widgets need nothing: they had no voice, and a missing key takes the default
`off`. The JSONB key test is spelled `config->'allow_voice' IS NOT NULL` rather
than with `?`, which some drivers read as a bind marker.

Revision ID: 0109_embed_dictation
Revises: 0108_ml_call_attribution
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0109_embed_dictation"
down_revision: str | None = "0108_ml_call_attribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE agent_embeds
           SET config = (config - 'allow_voice') || jsonb_build_object(
                 'dictation',
                 CASE WHEN config->>'allow_voice' = 'true' THEN 'browser' ELSE 'off' END
               )
         WHERE config->'allow_voice' IS NOT NULL
           AND config->'dictation' IS NULL
        """
    )
    # A row that somehow holds both keeps the newer one, and loses the old.
    op.execute(
        """
        UPDATE agent_embeds
           SET config = config - 'allow_voice'
         WHERE config->'allow_voice' IS NOT NULL
        """
    )


def downgrade() -> None:
    # The old schema can say "the browser's recogniser" and "nothing", so a page
    # on `server` goes back to no microphone rather than to a vendor nobody chose
    # for it. A widget had no voice before this revision and just loses the key.
    op.execute(
        """
        UPDATE agent_embeds
           SET config = config || jsonb_build_object(
                 'allow_voice', config->>'dictation' = 'browser'
               )
         WHERE kind = 'page'
        """
    )
    op.execute(
        """
        UPDATE agent_embeds
           SET config = config - 'dictation'
         WHERE config->'dictation' IS NOT NULL
        """
    )
