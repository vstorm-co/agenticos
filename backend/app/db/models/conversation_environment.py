"""Owned live environments, retained for cleanup when their parent is deleted."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ConversationEnvironment(Base, TimestampMixin):
    __tablename__ = "conversation_environments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_conversation_environment_tenant",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "organization_id IS NULL OR organization_id = vault_organization_id", name="vault_scope"
        ),
        CheckConstraint("execution_target IN ('agent', 'project')", name="execution_target"),
        CheckConstraint("session_lifetime IN ('run', 'conversation')", name="session_lifetime"),
        CheckConstraint("idle_seconds BETWEEN 60 AND 86400", name="idle_seconds"),
        CheckConstraint("kind IN ('browser', 'desktop')", name="kind"),
        CheckConstraint("state IN ('starting', 'ready', 'failed', 'expired')", name="state"),
        CheckConstraint("revision >= 1 AND provisioning_attempt >= 0", name="revision"),
        CheckConstraint(
            "(resource_ciphertext IS NULL) = (resource_key_version IS NULL)", name="resource_key"
        ),
        Index(
            "conversation_environments_active_owner_idx",
            "organization_id",
            "user_id",
            "conversation_id",
            "agent_id",
            "kind",
            unique=True,
            postgresql_where=text("state IN ('starting', 'ready')"),
        ),
        Index("conversation_environments_expiry_idx", "expires_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    vault_organization_id: Mapped[UUID] = mapped_column()
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    conversation_id: Mapped[UUID | None] = mapped_column()
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    agent_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL")
    )
    source_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16))
    execution_target: Mapped[str] = mapped_column(String(16))
    session_lifetime: Mapped[str] = mapped_column(String(16))
    idle_seconds: Mapped[int] = mapped_column(Integer)
    last_maintained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), default="starting")
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    provisioning_attempt: Mapped[int] = mapped_column(Integer, default=0)
    resource_key: Mapped[str | None] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resource_ciphertext: Mapped[str | None] = mapped_column(Text)
    resource_key_version: Mapped[int | None] = mapped_column(Integer)
    refusal_code: Mapped[str | None] = mapped_column(String(64))

    def __repr__(self) -> str:
        return f"ConversationEnvironment(id={self.id}, kind={self.kind!r}, state={self.state!r})"


class ConversationEnvironmentDriver(Base, TimestampMixin):
    """One GUI driver even when several private views share a physical desktop."""

    __tablename__ = "conversation_environment_drivers"
    __table_args__ = (
        CheckConstraint("control IN ('human', 'agent')", name="control"),
        Index("conversation_environment_drivers_expiry_idx", "lease_until"),
    )

    resource_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    control: Mapped[str] = mapped_column(String(16))
    lease_token: Mapped[UUID] = mapped_column()
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
