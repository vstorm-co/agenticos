"""KnowledgeBase model — scoped RAG collections (personal / org / app)."""

import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class KBScope(enum.StrEnum):
    PERSONAL = "personal"
    ORG = "org"
    APP = "app"


class KnowledgeBase(TimestampMixin, Base):
    """Named, scoped wrapper around a vector-store collection."""

    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default=KBScope.PERSONAL.value, index=True
    )
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # How documents put into this collection are parsed, chunked and described.
    # Validated as `app.services.ingestion_config.IngestionConfig`; stored as
    # JSON so a new option does not cost a migration. Changing it affects only
    # documents ingested afterwards.
    ingestion_config: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # The embedding model this collection's vectors were produced by, and the
    # width of the column they live in. Recorded rather than configured, and
    # immutable: `PgVectorStore` writes `embedding vector(N)` once, at creation,
    # so a second model's vectors either cannot be written or are compared
    # against the first model's as though they meant the same thing. Without
    # these two columns the only record was a deployment environment variable,
    # and changing it broke every existing collection silently.
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    # How widely the collection is exposed inside its org; combines with the
    # member's role scope and any explicit grant (app.services.access).
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.id}, name={self.name!r}, scope={self.scope})>"

    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'team', 'org')", name="ck_knowledge_bases_visibility"
        ),
        CheckConstraint(
            "scope <> 'org' OR organization_id IS NOT NULL",
            name="ck_knowledge_bases_org_scope_has_org",
        ),
    )
