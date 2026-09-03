"""Agent memory facts — the pgvector half of the memory capability (#788).

The `facts` shape: short things an agent chose to remember, recalled
semantically in a later run. This is the first pgvector migration in the repo,
so it does by hand what the RAG store does at runtime, and for the same reasons.

The scope columns are ordinary Alembic-managed columns, matching
`AgentMemoryFact`, so an operator has a table to list, read and clear facts
from. The vector is not: there is no pgvector SQLAlchemy type here, and the
width is the deployment's frozen embedding dimension (`EMBEDDING_MODEL`), so the
`embedding` column and its HNSW index are raw SQL. The model omits the column
and `alembic/env.py` excludes it from autogenerate, so `alembic check` does not
read the omission as drift.

Two things mirror `app/services/rag/vectorstore.py` exactly, because getting
either wrong fails only on a real database:

- `CREATE EXTENSION IF NOT EXISTS vector` on upgrade; downgrade drops the table
  but **not** the extension, which the RAG store shares.
- pgvector's HNSW index takes a `vector` column only up to 2000 dimensions. The
  shipped default `text-embedding-3-large` is 3072, so past 2000 the column is
  indexed as `halfvec` (`halfvec_cosine_ops`), the same width-dependent choice
  the RAG store makes. The width is frozen here at table creation; a deployment
  that later changes `EMBEDDING_MODEL` gets a dimension-mismatch at embed time,
  which is the documented cost of one fixed-width table.

Revision ID: 0072_agent_memory_facts
Revises: 0071_agent_memory_files
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.config import settings

revision: str = "0072_agent_memory_facts"
down_revision: str | None = "0071_agent_memory_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# pgvector's HNSW index supports a `vector` column up to this width; past it the
# column must be indexed as `halfvec`. Mirrors `_HNSW_MAX_VECTOR_DIM` in the RAG
# vector store, which makes the same choice for the same reason.
_HNSW_MAX_VECTOR_DIM = 2000


def upgrade() -> None:
    op.create_table(
        "agent_memory_facts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("end_user_scope_key", sa.String(length=128), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_memory_facts_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_memory_facts_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_memory_facts_pkey")),
    )
    op.create_index(
        op.f("agent_memory_facts_organization_id_idx"),
        "agent_memory_facts",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("agent_memory_facts_agent_id_idx"),
        "agent_memory_facts",
        ["agent_id"],
        unique=False,
    )

    dim = settings.rag.embeddings_config.dim
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"ALTER TABLE agent_memory_facts ADD COLUMN embedding vector({dim}) NOT NULL")
    if dim > _HNSW_MAX_VECTOR_DIM:
        op.execute(
            "CREATE INDEX agent_memory_facts_embedding_idx ON agent_memory_facts "
            f"USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops)"
        )
    else:
        op.execute(
            "CREATE INDEX agent_memory_facts_embedding_idx ON agent_memory_facts "
            "USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    # Dropping the table takes the embedding column and the HNSW index with it.
    # The `vector` extension is deliberately left in place: the RAG store shares
    # it, so dropping it here would break search on any deployment using both.
    op.drop_index(op.f("agent_memory_facts_agent_id_idx"), table_name="agent_memory_facts")
    op.drop_index(op.f("agent_memory_facts_organization_id_idx"), table_name="agent_memory_facts")
    op.drop_table("agent_memory_facts")
