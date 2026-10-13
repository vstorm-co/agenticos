"""A channel bot's own switch for transcribing voice notes (#1797).

Until now a bot's `speech_to_text_provider` / `speech_to_text_model` pair meant
two things at once: which engine, and - when null - "do not transcribe". The
agent and the organization can now name an engine too, so a bot with no pair of
its own needs to *inherit* one, and null cannot mean both. The off state moves
to `transcribe_voice_notes`, and null is left meaning "inherit".

**The backfill is what keeps the upgrade quiet.** A new bot inherits by default,
but every bot that had no pair before this revision was a bot that did not
transcribe, and turning it on underneath its operator would start spending the
organization's provider credit on voice notes nobody asked to have transcribed.
So the column arrives `true` and is then set `false` for each of them; a bot
with a pair keeps transcribing on it exactly as before.

A half pair - a provider with no model, or the reverse - could not transcribe
either (the router asked for both), so it is cleared to neither and switched
off with the rest, before the CHECK that from now on refuses one.

Revision ID: 0107_bot_transcription_switch
Revises: 0106_org_speech_settings
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0107_bot_transcription_switch"
down_revision: str | None = "0106_org_speech_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column("transcribe_voice_notes", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(
        "UPDATE channel_bots SET speech_to_text_provider = NULL, speech_to_text_model = NULL "
        "WHERE (speech_to_text_provider IS NULL) <> (speech_to_text_model IS NULL)"
    )
    op.execute(
        "UPDATE channel_bots SET transcribe_voice_notes = false "
        "WHERE speech_to_text_provider IS NULL"
    )
    op.create_check_constraint(
        op.f("channel_bots_ck_channel_bot_speech_pair_check"),
        "channel_bots",
        "(speech_to_text_provider IS NULL) = (speech_to_text_model IS NULL)",
    )


def downgrade() -> None:
    # A bot that inherited loses its engine on the way down, because the old
    # schema has no way to say "inherit": it goes back to the null pair, which
    # there means off. One switched off with a pair of its own keeps the pair
    # and would transcribe again, so its pair is cleared to keep it off.
    op.execute(
        "UPDATE channel_bots SET speech_to_text_provider = NULL, speech_to_text_model = NULL "
        "WHERE transcribe_voice_notes = false"
    )
    op.drop_constraint(
        op.f("channel_bots_ck_channel_bot_speech_pair_check"), "channel_bots", type_="check"
    )
    op.drop_column("channel_bots", "transcribe_voice_notes")
