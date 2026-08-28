"""Organization, OrganizationMember and Invitation models (PostgreSQL async)."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text

from app.core.permissions import OrgRoleName
from app.db.base import Base, TimestampMixin

# Roles live in the permission catalog, which is what actually decides what a
# role can do; re-declaring them here would let the two lists drift.
OrgRole = OrgRoleName


class InvitationStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Organization(Base, TimestampMixin):
    """Organization - the primary multi-tenant unit. Every user gets a Personal org on signup."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    is_personal: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Default-avatar colour slot 1..10 (`--avatar-*` ramp); null = auto from the id.
    avatar_color: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # The ceiling on everything this organization's agents spend in a calendar
    # month. `None` is no ceiling. A new organization starts at the deployment's
    # `DEFAULT_ORG_MONTHLY_BUDGET_USD` ($100 unless configured otherwise), so it
    # is not one runaway agent away from a surprise bill; a deployment that would
    # rather start uncapped sets that default to nothing, and any organization
    # can be cleared back to `None` afterwards.
    #
    # Numeric to the same scale as `agent_runs.cost_usd`: the cap is compared
    # against a sum of those, and a float would drift against the total the
    # Activity page shows.
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)

    # Whether a chat session may grant standing consent to this agent's gated
    # tools - `ApprovalMode.APPROVE_ALL` (#925). Off by default, and the default is
    # the point: without a ceiling a Builder's deliberate gate on `send_email` is
    # one click from nothing in every conversation, which makes the whole per-tool
    # approval model advisory. An organization decides once that waiving is
    # allowed at all; who may then do it is `approvals:decide`, which is a
    # separate question and already answered.
    #
    # Only ever *widens* nothing: switching it off does not tighten an existing
    # spec, it removes an override. So an upgrade changes nobody's behaviour until
    # somebody turns it on deliberately.
    chat_may_waive_approvals: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    invitations: Mapped[list["Invitation"]] = relationship(
        "Invitation",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Zero is not a tighter cap, it is an organization whose agents can never
        # answer - and it is one keystroke away from the number somebody meant to
        # type. The same constraint guards `agent_exposures`.
        CheckConstraint(
            "monthly_budget_usd IS NULL OR monthly_budget_usd > 0",
            name="ck_organization_budget_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, slug={self.slug}, personal={self.is_personal})>"


class OrganizationMember(Base):
    """Membership of a User in an Organization with a role."""

    __tablename__ = "organization_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=OrgRole.MEMBER.value)
    # SET NULL, not the default NO ACTION: who invited a member is audit context
    # that should outlive the inviter, and a NO-ACTION reference blocked deleting
    # anyone who had ever invited another member (#1110). Matches how the
    # secret/KB attribution FKs already null on the referenced user's deletion.
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_org_member_org_role", "organization_id", "role"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationMember(org={self.organization_id}, user={self.user_id}, role={self.role})>"


class Invitation(Base):
    """Email invitation to join an Organization."""

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null makes this a *link* rather than an email invitation: one row that
    # anybody holding the token can accept, which is how a team gets onboarded
    # from a Slack message instead of twenty individual sends. Everything else
    # about it - role, expiry, revocation, the accept path - is identical, which
    # is exactly why it is the same table and not a second one.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=OrgRole.MEMBER.value)
    # How many people a link admits. Null is unlimited; an email invitation
    # ignores it, because an address is its own limit of one.
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The addresses that registered through this link and have not joined yet, so
    # its remaining capacity is `max_uses - (used_count + len(reserved_emails))`.
    # Acceptance needs a session and registration does not, so counting only
    # `used_count` let one `max_uses=1` link admit an unbounded number of
    # registrations on an `invite_only` deployment. Accepting moves an address from
    # here into the count, which conserves the capacity somebody registering spent.
    reserved_emails: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Optional guard on a link: only addresses at this domain may accept. A link
    # posted in a channel is a link that can be forwarded, and "anyone with the
    # URL" is a different risk from "anyone at our company".
    email_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Nullable and SET NULL: the inviter is audit context that outlives them, and
    # a NOT NULL / NO-ACTION reference made an invitation authored by a user an
    # absolute bar on deleting that user (#1110). Set on every create, null only
    # once the inviter is gone.
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InvitationStatus.PENDING.value,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="invitations"
    )

    __table_args__ = (
        Index(
            "uq_pending_invitation",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        # A link invitation (no email) admits `max_uses` people, and zero admits
        # nobody - a link that looks issued and refuses everyone who opens it. Null
        # stays unlimited. Only links are constrained: an email invitation is for
        # one person and carries no cap at all.
        #
        # This lived only in the migration chain until the chain was collapsed, so
        # a schema built from the models would have dropped it - which is what the
        # schema diff in `0001_baseline` was for.
        CheckConstraint(
            "email IS NOT NULL OR max_uses IS NULL OR max_uses > 0",
            name="ck_invitation_max_uses_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<Invitation(org={self.organization_id}, email={self.email}, status={self.status})>"
