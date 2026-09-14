"""Services on the deployment's own network that a collection may be pointed at.

Two of them today, and both arrived as environment variables: `EMBEDDING_OLLAMA_BASE_URL`
named the one Ollama every collection could embed through, and `LITEPARSE_OCR_SERVER_URL`
the one OCR sidecar every LiteParse parse could send its pages to. One address per
deployment was wrong for the same reason `SANDBOXD_URL` was: a deployment can run
more than one, an organization may run its own, and there was nowhere in the
product to see or change either.

So: a row, named and pointed at a service, owned by an organization or - with no
organization - by the deployment itself, which is how a collection that belongs to
no organization (`scope: app`) reaches one at all. A knowledge base names an
`embedding` service by id where it would otherwise name a vault key; a collection's
ingestion configuration names an `ocr` service the same way. `sandbox_connections`,
`model_profiles` and `mcp_connections` are the same shape.

No credential lives here. Every service of these kinds is reached on the
deployment's own network without one, which is what makes it a *local* service; a
vendor across the internet is a catalog entry with a vault key, not a row here.
"""

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LocalServiceKind(StrEnum):
    """What a local service is for, which decides where a row may be named."""

    EMBEDDING = "embedding"
    OCR = "ocr"


class LocalService(Base, TimestampMixin):
    """One service on the deployment's own network, and who may use it."""

    __tablename__ = "local_services"
    __table_args__ = (
        CheckConstraint("kind IN ('embedding', 'ocr')", name="ck_local_services_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """Whose service this is. Null is the deployment's own, registered by its
    administrator and offered to every organization - and the only kind an
    app-scoped collection, which has no organization, may name."""
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    """For an `embedding` service, the keyless catalog entry that says which models
    it serves and at what width (`ollama`); for an `ocr` service, the parser that
    sends pages to it (`liteparse`). The kind decides what `base_url` means, so a
    collection naming a row does not carry it."""
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Turned off rather than deleted, so a collection naming it keeps its meaning
    and its refusal says the service is paused rather than gone."""
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<LocalService(id={self.id}, kind={self.kind}, name={self.name!r})>"
