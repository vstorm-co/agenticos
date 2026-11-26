"""Workspace-bound filesystem credentials and independently revocable run leases."""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ProjectFilesystemBinding(Base, TimestampMixin):
    """One sandbox's gateway identity, without authority to any Project by itself."""

    __tablename__ = "project_filesystem_bindings"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_project_filesystem_binding_tenant"),
        UniqueConstraint(
            "organization_id",
            "connection_id",
            "session_name",
            name="uq_project_filesystem_binding_session",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sandbox_connections.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_workspaces.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    session_name: Mapped[str] = mapped_column(String(64), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    secret_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<ProjectFilesystemBinding(id={self.id}, workspace_id={self.workspace_id})>"


class ProjectFilesystemLease(Base, TimestampMixin):
    """An immutable Project/generation path authorized for one admitted run."""

    __tablename__ = "project_filesystem_leases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "binding_id"],
            ["project_filesystem_bindings.organization_id", "project_filesystem_bindings.id"],
            name="fk_project_filesystem_lease_binding_tenant",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    binding_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    workspace_generation: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    authority_json: Mapped[str] = mapped_column(Text, nullable=False)
    """Server-produced admission context, never a credential or model input."""
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<ProjectFilesystemLease(id={self.id}, project_id={self.project_id}, run_id={self.run_id})>"
