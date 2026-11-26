"""Endpoints a collection may be pointed at, and the key that opens one when it has one.

Three kinds today. `embedding`: an OpenAI-compatible embeddings endpoint a knowledge
base embeds through - an Ollama on the deployment's network, or any gateway the
organization registers. `ocr`: the LiteParse OCR sidecar a parse may send its pages
to. `document_parser`: a Docling Serve a collection's documents are parsed by, with an
optional key. The first two began as environment variables (`EMBEDDING_OLLAMA_BASE_URL`,
`LITEPARSE_OCR_SERVER_URL`): one address per deployment was wrong for the same reason
`SANDBOXD_URL` was, since a deployment can run more than one, an organization may run
its own, and there was nowhere in the product to see or change either.

So: a row, named and pointed at an endpoint, owned by an organization or - with no
organization - by the deployment itself, which is how a collection that belongs to no
organization (`scope: app`) reaches one at all. A knowledge base names an `embedding`
connection by id where it would otherwise name a vault key; a collection's ingestion
configuration names an `ocr` or a `document_parser` one the same way. `sandbox_connections`, `model_profiles`
and `mcp_connections` are the same shape.

A connection may carry one credential, and only an organization's may: the vault is
per organization, so a deployment-owned row has nowhere to keep a key, and the
`ck_service_connections_deployment_keyless` constraint says so. `secret_id` names an
`organization_secrets` row; `requires_key` outlives it, so a connection whose key was
deleted reads as missing its key rather than as a keyless endpoint.
"""

import uuid
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ServiceConnectionKind(StrEnum):
    """What a service connection is for, which decides where a row may be named."""

    EMBEDDING = "embedding"
    OCR = "ocr"
    DOCUMENT_PARSER = "document_parser"


class ServiceConnection(Base, TimestampMixin):
    """One endpoint a collection may be pointed at, and who may use it."""

    __tablename__ = "service_connections"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('embedding', 'ocr', 'document_parser')", name="ck_service_connections_kind"
        ),
        CheckConstraint(
            "organization_id IS NOT NULL OR secret_id IS NULL",
            name="ck_service_connections_deployment_keyless",
        ),
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
    """The API style. For an `embedding` connection, the catalog entry reached
    through a connection - `ollama`, or `openai_compatible` for any OpenAI-style
    endpoint; for an `ocr` one, the parser that sends pages to it (`liteparse`). The
    kind decides what `base_url` means, so a collection naming a row does not carry
    it. Immutable after creation."""
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Turned off rather than deleted, so a collection naming it keeps its meaning
    and its refusal says the service is paused rather than gone."""
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The vault key sent to the endpoint, an organization's own. Nulled when the
    secret is deleted, which is why `requires_key` is stored separately."""
    requires_key: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.false()
    )
    """Set once a key has been given and never cleared by the key's deletion: a
    keyed endpoint that lost its key refuses by name instead of being called bare."""
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<ServiceConnection(id={self.id}, kind={self.kind}, name={self.name!r})>"
