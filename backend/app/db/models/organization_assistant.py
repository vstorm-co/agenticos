"""Each organization's AI Architect - which agent it is, and how it greets people (#2063).

The assistant is an ordinary agent, installed and published for the
organization the first time anybody opens the console. This row is what makes
it *the* assistant: the widget finds it here rather than by guessing from a
slug in a paged list, and the run check reads it to refuse an assistant an
administrator switched off.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy import true as sql_true
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class OrganizationAssistant(Base, TimestampMixin):
    __tablename__ = "organization_assistants"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    instructions_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Hash of the last shipped instructions installed or explicitly refreshed."""

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sql_true())
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    mark_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    """The legacy shipped picture's path, retained as provenance.

    New installations use generated avatars. The avatar backfill only clears a
    picture matching this path, preserving uploaded replacements and explicit
    clears. Retaining it does not restore or delete a stored file.
    """

    def __repr__(self) -> str:
        return (
            f"<OrganizationAssistant(organization={self.organization_id}, "
            f"agent={self.agent_id}, enabled={self.enabled})>"
        )
