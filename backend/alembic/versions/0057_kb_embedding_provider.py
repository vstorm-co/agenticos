"""Which provider serves a collection's embedding model.

The model was a choice frozen at creation, and has to be: the vector column is
created at that model's width, so a second model's vectors either cannot be
written or are compared against the first's as though they meant the same thing.

Whose endpoint answers was frozen too, by accident. `EmbeddingService` sent every
request to `https://openrouter.ai/api/v1` and the only per-collection choice was
which vault key paid - so an organization holding an OpenAI key could not use it,
a key moved to another account meant recreating the collection and re-ingesting
every document, and nothing stopped one vendor's credential going to another
vendor's address.

`embedding_provider` records the answer per collection, and unlike the model it can
be changed afterwards: the same model at the same width produces vectors in the
same space wherever it is served from, so re-pointing the address and the
credential leaves everything already stored valid.

Existing rows are backfilled with `openrouter` through the server default, because
that is where their vectors were produced - the address was the only one there was.

Revision ID: 0057_kb_embedding_provider
Revises: 0056_conversation_plan
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0057_kb_embedding_provider"
down_revision: str | None = "0056_conversation_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "embedding_provider",
            sa.String(length=32),
            nullable=False,
            server_default="openrouter",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "embedding_provider")
