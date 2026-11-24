"""Organizational links, never grants or copies of a resource's versioned spec."""

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ProjectResourceKind(StrEnum):
    AGENT = "agent"
    WORKFLOW = "workflow"
    APP = "app"
    TABLE = "table"


class ProjectResource(Base, TimestampMixin):
    """One reference to a resource, with real cascading foreign keys on both ends."""

    __tablename__ = "project_resources"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    app_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("virtual_tables.id", ondelete="CASCADE"), index=True
    )
    is_entrypoint: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(agent_id, workflow_id, app_id, table_id) = 1",
            name="ck_project_resource_one_target",
        ),
        CheckConstraint(
            "NOT is_entrypoint OR workflow_id IS NOT NULL",
            name="ck_project_resource_workflow_entrypoint",
        ),
        UniqueConstraint("project_id", "agent_id", name="uq_project_resource_agent"),
        UniqueConstraint("project_id", "workflow_id", name="uq_project_resource_workflow"),
        UniqueConstraint("project_id", "app_id", name="uq_project_resource_app"),
        UniqueConstraint("project_id", "table_id", name="uq_project_resource_table"),
        Index(
            "uq_project_resource_entrypoint",
            "project_id",
            unique=True,
            postgresql_where=text("is_entrypoint"),
        ),
    )

    def __repr__(self) -> str:
        return f"<ProjectResource(id={self.id}, project_id={self.project_id})>"
