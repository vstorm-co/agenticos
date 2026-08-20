"""SyncSource model - stores RAG sync source configurations."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SyncSource(TimestampMixin, Base):
    """Configurable connector source for RAG document synchronization.

    Belongs to an organization - and now says so in the column as well as here.
    It was nullable, and the CLI created rows without one, which is what kept
    this table's credentials out of the vault: an envelope is derived from its
    owner's id, so a row with no owner has nothing to bind a ciphertext to
    (#937). `collection_name` stays nullable - a source without a collection is
    an org-level "integration template" not yet assigned to a knowledge base.

    **The credential is a vault secret referenced by id, not a value in
    `config`.** `config` holds what a connector needs to *find* the documents -
    a folder id, a bucket, a prefix - and nothing that has to be kept. The
    service account JSON and the AWS key pair used to sit in this JSONB column
    encrypted by `app/core/crypto.py`, one deployment-wide Fernet key for every
    tenant, which is the weakness the vault exists to remove; and being per
    source rather than per organization, one Drive credential feeding five
    collections was the same secret pasted five times and rotated in five
    places.
    """

    __tablename__ = "sync_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(20), nullable=False)
    collection_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Nullable, and `SET NULL` rather than `RESTRICT`, for the same reason
    # `KnowledgeBase.embedding_secret_id` is: deleting a credential from the
    # vault must not be blocked by a row somewhere that points at it. What
    # follows is a sync that refuses with "this source has no credential"
    # instead of one that runs on a stale copy - the connectors have no
    # deployment-wide fallback and must not grow one.
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sync_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="new_only")
    schedule_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
