"""Alembic migration environment."""
# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base
from app.db.vector_tables import is_runtime_vector_table

# Import all models here to ensure they are registered with metadata
from app.db.models.user import User  # noqa: F401
from app.db.models.conversation import Conversation, Message, ToolCall  # noqa: F401
from app.db.models.message_rating import MessageRating  # noqa: F401
from app.db.models.session import Session  # noqa: F401
from app.db.models.chat_file import ChatFile  # noqa: F401
from app.db.models.rag_document import RAGDocument  # noqa: F401
from app.db.models.sync_log import SyncLog  # noqa: F401
from app.db.models.sync_source import SyncSource  # noqa: F401
from app.db.models.organization import Invitation, Organization, OrganizationMember  # noqa: F401
from app.db.models.audit_log import AppAdminAuditLog  # noqa: F401
from app.db.models.knowledge_base import KnowledgeBase  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


# Ensure SQLite data directory exists before connecting


def get_url() -> str:
    """Get database URL from settings."""
    return settings.DATABASE_URL_SYNC


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Keep the vector store's runtime tables out of the comparison.

    `alembic check` and `--autogenerate` compare the whole database against the
    models, so every `rag_<collection>` table the store created at runtime read as a
    table to drop, and `check` exited non-zero on any database that had ever ingested
    a document. What it is meant to catch is a model change with no migration; what it
    caught was somebody having used the product (#288).

    The test is narrow on purpose - `rag_documents` is a model table, and excluding it
    would silence real drift in the one table this project ingests through.
    `app/db/vector_tables.py` explains why both halves of that test are needed.

    One column is excluded too: `agent_memory_facts.embedding`. There is no
    pgvector SQLAlchemy type in this project and the width is the deployment's
    frozen embedding dimension, so that column and its HNSW index are created in
    the migration as raw SQL and the model deliberately omits it (see
    `AgentMemoryFact`). Without this the model omitting it would read as a column
    to drop, and `alembic check` would fail on every database - the same false
    positive `is_runtime_vector_table` prevents for the RAG tables, one column
    narrower. Only that one column on that one table; every other column stays in
    the comparison.
    """
    if type_ == "table" and name is not None:
        return not is_runtime_vector_table(name, metadata=target_metadata)
    return not (
        type_ == "column"
        and name == "embedding"
        and parent_names.get("table_name") == "agent_memory_facts"
    )


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
