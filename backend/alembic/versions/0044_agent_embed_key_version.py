"""An embed records which master-key version sealed its signing secret.

`agent_embeds.jwt_secret_encrypted` was sealed by the vault but the row kept no
`key_version`, so the verifier unsealed at an implicit v1. That is a latent bug:
the day a master-key rotation runs `rewrap` over the vault, every `jwt` widget's
secret moves to v2 and can never be opened again - `EmbedDenied("token
rejected")` for every visitor, with no column to bump (#552).

Every existing envelope was sealed at v1, so the column backfills to 1 with a
server default; the default is then dropped, because the model carries no
server default - a new row's version comes from the code that seals it.

Revision ID: 0044_agent_embed_key_version
Revises: 0043_rag_document_source_path
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044_agent_embed_key_version"
down_revision: str | None = "0043_rag_document_source_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_embeds",
        sa.Column("secret_key_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("agent_embeds", "secret_key_version", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_embeds", "secret_key_version")
