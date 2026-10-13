"""Folders - a tree of one kind of resource, and an audience for what it holds.

Apps, skills, context files and knowledge bases were flat lists, so an
organization that wanted a `GTM` folder with `Sales` beneath it, the Sales half
visible only to sales, had to share every resource one at a time (#2124).

A folder holds one kind of resource and has an audience the way a resource
does: an owner, a `visibility`, and grants to people and groups. What it holds
is reached by that audience *and* by whoever a resource was shared with
directly - a folder grants access, it never takes a direct share away.

Two invariants keep the access rules where they already are (`resolve_access`):

- **A resource in a folder carries the folder's visibility.** Filing it, and
  every change to the folder's audience, writes the folder's `visibility` onto
  the rows it holds, so the scope predicate every listing already applies is
  the folder's. The folder's grants are read beside the resource's own when a
  grant is looked up.
- **A subfolder can only narrow its parent.** Its visibility is never wider
  and its grants name only subjects the parent names, so reaching a resource
  through its own folder never reaches past an ancestor's audience.
"""

import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class FolderKind(StrEnum):
    """Which resource a folder holds - the grant key of that resource type."""

    ARTIFACT = "artifact"
    SKILL = "skill"
    CONTEXT = "context"
    COLLECTION = "collection"


class Folder(Base, TimestampMixin):
    """One folder of one kind of resource, inside one organization."""

    __tablename__ = "folders"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Restricted: a folder is deleted by moving what it holds first, which the
    # service does, so the database refusing a stray delete is the right answer.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )

    __table_args__ = (
        Index("folders_organization_id_kind_idx", "organization_id", "kind"),
        CheckConstraint(
            "kind IN ('artifact', 'skill', 'context', 'collection')", name="ck_folder_kind"
        ),
        CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_folder_visibility"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_folder_not_own_parent"),
    )

    def __repr__(self) -> str:
        return f"<Folder({self.kind}:{self.name} id={self.id})>"
