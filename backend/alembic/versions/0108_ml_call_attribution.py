"""Who a transcription was for, and how long the recording was (#1797).

`ml_service_calls` recorded that a recording was transcribed and how many
characters came back, and nothing else: not which provider heard it, not the
agent or the channel bot it was for, and not its length. Speech to text is now
reached from three surfaces - the ML API, dictation in `/chat` and a channel
bot's voice notes - and the questions an organization asks of it are "how many
minutes" and "for which agent". So a transcription row carries its provider and
model, the vault key it was sent with, the surface it arrived on, the agent and
bot it served, and the audio's length in milliseconds (the `duration_ms`
convention, rather than a Numeric). The key is `secret_id`, as on `agent_runs`,
so "which key costs most" reads the same for speech as for chat.

Every column is nullable and nothing is backfilled: a row written before this
revision did not know any of it, and inventing an agent or a length for one
would be a usage figure nobody can reconcile. Every foreign key is SET NULL,
like the requester's: deleting an agent, a bot or a key does not unmake what
was transcribed for it.

The summary reads one organization's rows over a window, which
`ix_ml_service_calls_org_created` already serves. The key alone is indexed, as
on `agent_runs`: deleting a secret sets it null on every row that names it, and
without an index that is a scan of the whole log.

Revision ID: 0108_ml_call_attribution
Revises: 0107_bot_transcription_switch
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0108_ml_call_attribution"
down_revision: str | None = "0107_bot_transcription_switch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ml_service_calls", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("ml_service_calls", sa.Column("model", sa.String(length=255), nullable=True))
    op.add_column("ml_service_calls", sa.Column("surface", sa.String(length=16), nullable=True))
    op.add_column(
        "ml_service_calls", sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "ml_service_calls",
        sa.Column("channel_bot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("ml_service_calls", sa.Column("audio_ms", sa.Integer(), nullable=True))
    op.add_column(
        "ml_service_calls", sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        op.f("ml_service_calls_secret_id_idx"), "ml_service_calls", ["secret_id"], unique=False
    )
    op.create_foreign_key(
        op.f("ml_service_calls_secret_id_fkey"),
        "ml_service_calls",
        "organization_secrets",
        ["secret_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("ml_service_calls_agent_id_fkey"),
        "ml_service_calls",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("ml_service_calls_channel_bot_id_fkey"),
        "ml_service_calls",
        "channel_bots",
        ["channel_bot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ml_service_calls_secret_id_fkey"), "ml_service_calls", type_="foreignkey"
    )
    op.drop_index(op.f("ml_service_calls_secret_id_idx"), table_name="ml_service_calls")
    op.drop_column("ml_service_calls", "secret_id")
    op.drop_constraint(
        op.f("ml_service_calls_channel_bot_id_fkey"), "ml_service_calls", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("ml_service_calls_agent_id_fkey"), "ml_service_calls", type_="foreignkey"
    )
    op.drop_column("ml_service_calls", "audio_ms")
    op.drop_column("ml_service_calls", "channel_bot_id")
    op.drop_column("ml_service_calls", "agent_id")
    op.drop_column("ml_service_calls", "surface")
    op.drop_column("ml_service_calls", "model")
    op.drop_column("ml_service_calls", "provider")
