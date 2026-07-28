"""ResourceGrant — per-row sharing, on top of role scopes."""

import enum
import uuid
from typing import Literal

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Visibility(enum.StrEnum):
    """How widely a resource is exposed inside its organization."""

    PRIVATE = "private"
    TEAM = "team"
    ORG = "org"


class GrantLevel(enum.StrEnum):
    """What a grant lets the subject do with one resource.

    Ordered ``READ < USE < EDIT``: *read* sees the configuration, *use* also
    runs or attaches it, *edit* also changes it.
    """

    READ = "read"
    USE = "use"
    EDIT = "edit"


GrantLevelLiteral = Literal["read", "use", "edit"]
"""The stored levels, as a type the API schemas can also be written in.

Declared here rather than in :mod:`app.schemas.resource_grant` because this is
the module that makes it true: ``ck_resource_grant_level`` below is what stops a
fourth value reaching the column, and a response model promising three of them
should be typed from the same place. Without it the ORM column is a plain
``str``, and handing one to a schema field that says ``Literal`` type-checks
nowhere and raises at response time.
"""


GRANT_ORDER: dict[GrantLevel, int] = {
    GrantLevel.READ: 0,
    GrantLevel.USE: 1,
    GrantLevel.EDIT: 2,
}


class ResourceGrant(Base, TimestampMixin):
    """One share of one resource with one member.

    Deliberately generic (``resource_type`` + ``resource_id``, no foreign key
    to the target): agents, collections and skills all share the same sharing
    UI and rules, and the alternative is a near-identical grant table per
    resource type. The trade-off is that the database cannot cascade-delete a
    grant when its target goes away, so services delete grants alongside the
    resource.
    """

    __tablename__ = "resource_grants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    level: Mapped[GrantLevelLiteral] = mapped_column(
        String(16), nullable=False, default=GrantLevel.READ.value
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "subject_user_id",
            name="uq_resource_grant_subject",
        ),
        CheckConstraint("level IN ('read', 'use', 'edit')", name="ck_resource_grant_level"),
    )

    def __repr__(self) -> str:
        return (
            f"<ResourceGrant({self.resource_type}:{self.resource_id} "
            f"-> {self.subject_user_id} = {self.level})>"
        )
