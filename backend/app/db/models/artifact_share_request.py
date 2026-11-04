"""A request to share a page, or to confirm a version of it (#1974).

A page that reads live data reaches only its owner and the roles that open every page
until its owner shares it, so somebody who may not decide that asks. One table holds the
three kinds of asking:

- `audience`: an editor who is not the owner tried to widen who opens a bound page
  (a wider visibility, a new grant); the request carries what they wanted.
- `access`: a member of the organization who cannot open the page asked to.
- `version`: another editor's republish changed the page queries, and the owner has to
  confirm what the new version reads before its audience is served it.

A request is pending until somebody decides it, and it is voided when what it asked
about no longer stands: a page query that changed, a new owner, an archived page, a
newer request of the same kind replacing it.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

MAX_NOTE_LENGTH = 500


class ShareRequestKind(StrEnum):
    AUDIENCE = "audience"
    ACCESS = "access"
    VERSION = "version"


class ShareRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    VOIDED = "voided"


class VoidReason(StrEnum):
    """Why a pending request stopped being one without anybody deciding it."""

    REPLACED = "replaced"
    """The same person asked again, or a newer version's request took its place."""
    PAGE_CHANGED = "page_changed"
    """The page's queries changed, so what was asked about is not what is served."""
    OWNER_CHANGED = "owner_changed"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"
    """A newer version was published that nobody has to confirm."""


class ArtifactShareRequest(Base, TimestampMixin):
    """One request about one page."""

    __tablename__ = "artifact_share_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The membership they asked under, as a number rather than a key: re-inviting
    # someone makes a new one, and what they asked before is not theirs to stand on.
    requester_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # The version the request was made against, and the one a `version` request is
    # about. Deleted with it when pruning drops the version.
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("artifact_versions.id", ondelete="CASCADE"), nullable=True
    )
    # The digest of the page queries when it was made; null for a page without any.
    query_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_visibility: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # `{"people": [{"user_id", "level"}], "groups": [{"group_id", "level"}]}`.
    requested_subjects: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ShareRequestStatus.PENDING.value,
        server_default=ShareRequestStatus.PENDING.value,
    )
    void_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('audience', 'access', 'version')", name="ck_share_request_kind"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'voided')",
            name="ck_share_request_status",
        ),
        CheckConstraint(
            "requested_visibility IS NULL OR requested_visibility IN ('team', 'org')",
            name="ck_share_request_visibility",
        ),
        CheckConstraint(
            f"note IS NULL OR char_length(note) <= {MAX_NOTE_LENGTH}",
            name="ck_share_request_note",
        ),
        # One pending request per person and kind of a page, and one pending
        # `version` request per page whoever made it: a newer one replaces the older.
        Index(
            "uq_artifact_share_request_pending",
            "artifact_id",
            "requester_user_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'pending' AND kind <> 'version'"),
        ),
        Index(
            "uq_artifact_share_request_pending_version",
            "artifact_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND kind = 'version'"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ArtifactShareRequest(artifact={self.artifact_id}, kind={self.kind}, "
            f"status={self.status})>"
        )
