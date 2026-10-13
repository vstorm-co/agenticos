"""Organization speech-to-text settings for /chat dictation (#1797).

Five typed columns rather than a JSONB document, because the rules span them and
the database can hold them: the engine is one of three values, the provider and
model are a pair from the speech-to-text catalog (both or neither), and the
longest recording is bounded. A CHECK on each means a half-written setup is a
constraint violation rather than a composer that fails on its first recording.

Every existing organization gets `browser`, which is what its microphone already
does - the Web Speech API - so nobody's audio moves to a new vendor on upgrade.
The provider credential is not a column: it is the organization's model profile
for that provider, resolved per recording, the same way channel bots transcribe.

Revision ID: 0106_org_speech_settings
Revises: 0105_workspace_directories
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0106_org_speech_settings"
down_revision: str | None = "0105_workspace_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("chat_dictation", sa.String(16), nullable=False, server_default="browser"),
    )
    op.add_column(
        "organizations", sa.Column("speech_to_text_provider", sa.String(32), nullable=True)
    )
    op.add_column("organizations", sa.Column("speech_to_text_model", sa.String(255), nullable=True))
    op.add_column(
        "organizations", sa.Column("speech_to_text_language", sa.String(8), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column("dictation_max_seconds", sa.Integer(), nullable=False, server_default="300"),
    )
    op.create_check_constraint(
        op.f("organizations_ck_organization_chat_dictation_check"),
        "organizations",
        "chat_dictation IN ('off', 'browser', 'server')",
    )
    op.create_check_constraint(
        op.f("organizations_ck_organization_speech_pair_check"),
        "organizations",
        "(speech_to_text_provider IS NULL) = (speech_to_text_model IS NULL)",
    )
    op.create_check_constraint(
        op.f("organizations_ck_organization_dictation_max_seconds_check"),
        "organizations",
        "dictation_max_seconds BETWEEN 10 AND 600",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("organizations_ck_organization_dictation_max_seconds_check"),
        "organizations",
        type_="check",
    )
    op.drop_constraint(
        op.f("organizations_ck_organization_speech_pair_check"), "organizations", type_="check"
    )
    op.drop_constraint(
        op.f("organizations_ck_organization_chat_dictation_check"), "organizations", type_="check"
    )
    for column in (
        "dictation_max_seconds",
        "speech_to_text_language",
        "speech_to_text_model",
        "speech_to_text_provider",
        "chat_dictation",
    ):
        op.drop_column("organizations", column)
