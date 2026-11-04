"""Projects - a shared workspace, standing instructions and the chats held in them.

A project is somewhere a group of people work on one thing with whichever agents
they need: every chat started in it runs in the project's own container, so a file
one conversation wrote is there for the next, whoever asked and whichever agent
answered; and the project's instructions reach every agent that answers in it.

It is a shared resource like an agent or a context file - an owner, a visibility
and grants. Its chats are its members': whoever may see the project reads them,
and whoever may work in it continues them.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class Project(Base, TimestampMixin):
    """One project: its container, its instructions, and who may work in it."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """Told to every agent that answers in the project, after its own instructions."""

    default_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The agent a new chat in the project starts with; any other may be chosen."""

    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="service")
    """`service` - a container on a sandbox connection, with a shell - or `state`,
    files stored by the platform, for a deployment that runs no sandbox service."""
    sandbox_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sandbox_connections.id", ondelete="SET NULL"),
        nullable=True,
        # Deleting a connection, and refusing to while a project is on it, look
        # projects up by this column.
        index=True,
    )
    """Which connection the container runs on; `None` takes the organization's default."""
    workspace_generation: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    """Null retains the legacy key. A transfer activates its own isolated generation."""
    workspace_move_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("background_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    runtime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """Which environment the container runs; `None` takes the connection's default."""

    __table_args__ = (
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_project_visibility"),
        CheckConstraint("backend IN ('state', 'service')", name="ck_project_backend"),
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name!r})>"
