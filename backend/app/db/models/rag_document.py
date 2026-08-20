"""RAGDocument model - tracks documents ingested into RAG collections."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DocumentStatus(enum.StrEnum):
    """Where a tracked document is in its ingestion.

    Three values, and the column holds nothing else: a row is created
    `PROCESSING` by the upload, and the pipeline moves it to `DONE` or `ERROR`.
    It is an enum because it was not one - the listing's `indexed` count
    filtered on a fourth value, `"completed"`, that nothing has ever written, so
    every knowledge base in the product reported `indexed_count: 0` however many
    documents had finished (#148).
    """

    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class RAGDocument(TimestampMixin, Base):
    """Tracks ingested documents with processing status."""

    __tablename__ = "rag_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filesize: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filetype: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Which file this row tracks, as the ingest addressed it: `gdrive://<id>`,
    # `s3://bucket/key`, an absolute path for a local sync, and the filename
    # itself for an upload, which has no address of its own.
    #
    # Indexed because it is how a row is found again. Without it a row could only
    # be matched by `filename`, and two keys of one basename in a bucket are
    # indistinguishable that way - so retiring "the previous row for this file"
    # deleted the other file's (#996), which is the collision #990 removed on the
    # vector side. Nullable for every row written before this column existed.
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentStatus.PROCESSING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    vector_document_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # A collection's configuration changes; a document does not get re-parsed
    # when it does. Without these columns "why is this one chunked differently"
    # has no answer, and a per-upload override would be invisible the moment the
    # request that carried it finished.
    #
    # `ingestion_config` is the *resolved* configuration - the collection's,
    # with the upload's override already applied. `ingestion_override` is what
    # the uploader asked to differ, and is null when they asked for nothing.
    ingestion_config: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    ingestion_override: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    # The model that described the images in this document, as `provider:model`.
    # Null means none did - either the configuration had image description off,
    # or the document predates this column. Stored resolved rather than as the
    # profile id, because a profile can be edited or deleted and what read this
    # document must not change when it is.
    image_description_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The embedding model this document's vectors were produced by, copied from
    # the collection at ingestion.
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
