"""Dictation is raw PCM unless the deployment accepts compressed audio (#1797).

`deployment_settings.dictation_compressed_audio`, off. A dictation's cost is
bounded by its length, and only raw PCM states its length by its size: a WebM,
Ogg or MP4 file says how long it is in a header, and one built by hand can say
less than it holds. So the dictation routes accept 16 kHz mono 16-bit PCM WAV
alone until the deployment's administrator turns this on, accepting that risk
for every organization at once.

A column on the singleton rather than a setting in the environment: the
administrator decides it on Admin -> Deployment, where the warning is, and the
change is audited like every other field of that row. `NOT NULL` with a server
default, so the one row a deployment may already hold reads as off. That does
change an upgraded deployment: it stops accepting WebM. Nothing breaks for it,
because every client records in the format the server advertises, and the
advertised format becomes WAV in the same release.

Revision ID: 0142_dictation_compressed_audio
Revises: 0141_embed_dictation
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0142_dictation_compressed_audio"
down_revision: str | None = "0141_embed_dictation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column(
            "dictation_compressed_audio",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("deployment_settings", "dictation_compressed_audio")
