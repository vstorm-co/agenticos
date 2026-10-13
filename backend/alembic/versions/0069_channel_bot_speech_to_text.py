"""Which model a channel bot transcribes voice notes with.

A voice message is the one attachment an agent cannot be handed as a file: it
reads a PDF and looks at a screenshot, and an `audio/ogg` blob is a byte count.
So a bot that receives one can ignore it, say it cannot listen, or transcribe it -
and transcribing needs somebody to have chosen a model.

A **pair**, not one string. The provider decides where the request goes and the
model decides what answers, and `ImageGenerationConfig` is the worked example of
getting that wrong: it carried the SDK prefix and the model in one enumerated
field, and taking them apart later needed a migration plus a `normalize_legacy`
reader for every spec published before it.

Two columns rather than a key in `access_policy`, which already holds JSONB.
Partly because this is not a policy - nothing here is a refusal - and partly
because a JSONB field is where a value goes when nobody wants to write a
migration, which is how a rule ends up narrowed on a column that already holds
rows breaking it.

**Nullable, defaulting to off.** Transcription spends the organization's provider
credit on every voice note that arrives, so it is opted into rather than out of. A
non-null default would also have to name a provider, and a deployment whose
providers all want service accounts can offer none - the nullable pair says "not
configured" where a default would say "configured with something that cannot run".

Revision ID: 0069_channel_bot_stt

The id is shorter than the file name because `alembic_version.version_num` is
`varchar(32)`, and the descriptive form is 34.
Revises: 0068_reread_channel_threads
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0069_channel_bot_stt"
down_revision: str | None = "0068_reread_channel_threads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_bots", sa.Column("speech_to_text_provider", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "channel_bots", sa.Column("speech_to_text_model", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("channel_bots", "speech_to_text_model")
    op.drop_column("channel_bots", "speech_to_text_provider")
