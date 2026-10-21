"""Which eval suites guard an environment, and each promotion made past them.

An environment that names guards takes a version only once every guard has
passed on that exact version, over the dataset version it reads now and under
the threshold it holds now. A member allowed to may promote past a guard that
did not pass, with a reason; that is an override, kept here beside the audit
entry so the version's history shows it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentGuard(Base):
    """One eval suite an environment requires to pass before it takes a version."""

    __tablename__ = "agent_environment_guards"

    environment_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # RESTRICT: deleting a suite that guards an environment would unguard it
    # without anybody deciding to, so the delete is refused until it is removed.
    suite_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<EnvironmentGuard(environment={self.environment_id}, suite={self.suite_id})>"


class PromotionOverride(Base):
    """A version promoted onto a guarded environment whose guards had not all passed."""

    __tablename__ = "agent_promotion_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Kept by name too: the record outlives the environment it was made on.
    environment_name: Mapped[str] = mapped_column(String(64), nullable=False)
    replaced_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Each guard as it stood when it was overridden: suite, result and status.
    gate: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint("length(reason) >= 10", name="ck_promotion_override_reason"),)

    def __repr__(self) -> str:
        return (
            f"<PromotionOverride(id={self.id}, version={self.version_id}, "
            f"environment={self.environment_name})>"
        )
