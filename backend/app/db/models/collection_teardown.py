"""A collection name reserved while its vector table is being torn down."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CollectionTeardown(Base):
    """A tombstone that reserves a collection name until its deferred drop runs.

    The teardown arc drops a collection's `rag_<name>` table only after the request
    that removed its knowledge-base rows commits (#1347/#1349), so between the commit
    and the drop the name is free of any row but the table still exists, populated.
    A concurrent `POST /rag/collections/{name}` for the same name would then have
    `PgVectorStore._ensure_collection`'s `CREATE TABLE IF NOT EXISTS` **adopt** that
    lingering table and read another tenant's chunks (#1362) - the advisory lock
    (#1355) only serializes the claim against the drop, it does not stop the claim
    winning the race.

    A row here, inserted in the same transaction as the delete, closes the window:
    `CollectionAccessService.claim` refuses a name that carries a tombstone, and the
    durable cleanup drops the table and only then releases the row. The name is
    deployment-global - the vector namespace has no tenant dimension - so the name
    itself is the key, and a teardown of a name already tombstoned is idempotent.
    A default knowledge base kept on the name blocks reuse by its own row and needs
    no tombstone; this is only for a name no row references after the teardown.
    """

    __tablename__ = "collection_teardowns"

    collection_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<CollectionTeardown(collection_name={self.collection_name})>"
