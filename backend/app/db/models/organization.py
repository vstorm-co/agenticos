"""Organization, OrganizationMember and Invitation models (PostgreSQL async)."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

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
    Text,
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


class MembershipSource(enum.StrEnum):
    """Who maintains a membership: an administrator, or the directory sync.

    The directory sync only ever rewrites or removes rows it created itself. A
    membership an administrator made - by invitation, or by changing a role the
    sync had set - is theirs, and a later sign-in leaves it alone (#1773).
    """

    MANUAL = "manual"
    DIRECTORY = "directory"


MembershipSourceLiteral = Literal["manual", "directory"]
# When the nightly look runs: at a fixed hour, or before the person's working hours (#2301).
ProactiveTiming = Literal["fixed", "before_work"]
"""The stored sources, as a type a schema can be written in.

Declared beside the CHECK constraints that make it true, the way
`GrantLevelLiteral` is, so a response model promising two values is typed from
the same place the database enforces them.
"""


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

    # What the platform may spend on each person in a calendar month on work it
    # does on its own initiative - noticing a repeated request, writing their
    # first messages (#2301). Per person, so one busy member cannot use up
    # everybody's. Zero switches that work off; it is inside `monthly_budget_usd`,
    # never beside it.
    proactive_limit_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("1"), server_default=text("1")
    )
    # Whether that work happens at all. Off until an organization turns it on:
    # it spends money nobody asked for in the moment, so it is a decision, made
    # with the model it runs on and when it runs beside it.
    proactive_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # The model it runs on - chosen, never defaulted: turning it on without one
    # is refused, and a profile deleted later switches it off in effect.
    proactive_model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # When each person's nightly look runs, in their own time zone: on these ISO
    # weekdays, at `proactive_hour`, or - `before_work` - an hour before the
    # working hours their profile states, falling back to `proactive_hour`.
    proactive_days: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=lambda: [1, 2, 3, 4, 5], server_default=text("'[1,2,3,4,5]'")
    )
    proactive_hour: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=5, server_default=text("5")
    )
    proactive_timing: Mapped[ProactiveTiming] = mapped_column(
        String(16), nullable=False, default="fixed", server_default=text("'fixed'")
    )
    # Whether people may point the look at their own connections (`Watch`), and
    # how often a watch may be read at most. It runs on the same model and limit as
    # the nightly look.
    proactive_watches_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    proactive_watch_min_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60")
    )
    # A new member's direct message in the organization's chat apps, and the
    # words it says - null for the built-in greeting in their language.
    welcome_dm_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    welcome_dm_text: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    # A pair from the speech-to-text catalog, both or neither, and the default an
    # agent or a channel bot inherits (#1797). Whether `/chat` dictation uses it
    # is each agent's switch; without one the browser transcribes.
    speech_to_text_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    speech_to_text_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The vault key the pair above is sent with: an org-visible `api_key` whose
    # purpose is the provider, because the platform spends it for everybody.
    # Named, never looked up - with two keys for one provider, guessing which
    # one pays is a bill nobody chose. SET NULL on delete, so a deleted key
    # reads as "choose a key" rather than taking the organization with it.
    # `use_alter`, because `organization_secrets` points back at this table:
    # `create_all` and `drop_all` cannot order a cycle and add this constraint
    # after both tables exist instead.
    speech_to_text_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    # ISO-639-1, or NULL to let the engine detect it.
    speech_to_text_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # The composer stops a recording here; the server's byte cap derives from it.
    dictation_max_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default="300"
    )

    # How long this organization's data lives, per class, in days. `None` on the
    # column means it has never had an opinion and takes the deployment's
    # defaults; a class absent from the mapping means the same for that class
    # alone, and a class present with `null` means "keep for ever" deliberately -
    # which is why this is a mapping with holes rather than six columns (#1420).
    #
    # The number here is what the organization *asked for*. What actually sweeps
    # is `app/core/retention.py`'s resolution of it against the deployment's
    # defaults, its ceiling and the audit floor, and no other place resolves it.
    retention_days: Mapped[dict[str, int | None] | None] = mapped_column(JSONB, nullable=True)

    members: Mapped[list[OrganizationMember]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    invitations: Mapped[list[Invitation]] = relationship(
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
        CheckConstraint("proactive_limit_usd >= 0", name="ck_organization_proactive_limit"),
        CheckConstraint("proactive_hour BETWEEN 0 AND 23", name="ck_organization_proactive_hour"),
        CheckConstraint(
            "proactive_watch_min_minutes >= 15", name="ck_organization_watch_min_minutes"
        ),
        CheckConstraint(
            "proactive_timing IN ('fixed', 'before_work')",
            name="ck_organization_proactive_timing",
        ),
        CheckConstraint(
            "(speech_to_text_provider IS NULL) = (speech_to_text_model IS NULL)",
            name="ck_organization_speech_pair",
        ),
        CheckConstraint(
            "dictation_max_seconds BETWEEN 10 AND 600",
            name="ck_organization_dictation_max_seconds",
        ),
        # A key belongs to the pair beside it; with no pair it would be a key
        # for nothing, carried over to whichever provider is chosen next.
        CheckConstraint(
            "speech_to_text_secret_id IS NULL OR speech_to_text_provider IS NOT NULL",
            name="ck_organization_speech_key_needs_pair",
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
    source: Mapped[MembershipSourceLiteral] = mapped_column(
        String(16),
        nullable=False,
        default=MembershipSource.MANUAL.value,
        server_default=MembershipSource.MANUAL.value,
    )
    # The first messages an empty chat with the starter agent offers this person
    # here, written in the background from what they did in this organization -
    # so on the membership, never the account, which every organization reads.
    # Null until the first look, which the agent's own starters stand in for.
    personal_starters: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    personal_starters_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="members")

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_org_member_org_role", "organization_id", "role"),
        CheckConstraint("source IN ('manual', 'directory')", name="ck_org_member_source"),
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

    organization: Mapped[Organization] = relationship("Organization", back_populates="invitations")

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
