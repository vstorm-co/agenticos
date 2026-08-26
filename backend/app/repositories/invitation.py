"""Invitation repository (PostgreSQL async)."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Text, and_, case, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.organization import Invitation, InvitationStatus, OrgRole

_INVITE_TTL_DAYS = 7


async def get_by_token(
    db: AsyncSession, token: str, *, for_update: bool = False
) -> Invitation | None:
    """Read an invitation by its token; with `for_update`, lock the row.

    `accept` reads `used_count`, checks it against `max_uses` in Python, and then
    increments it - a check-then-act that, unlocked, admits two people through a
    one-use link posted in a channel and clicked at once. Locking the row in
    `accept` serializes the second caller behind the first, which then re-reads
    the bumped count and is refused.
    """
    query = select(Invitation).where(Invitation.token == token)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, invitation_id: UUID) -> Invitation | None:
    return await db.get(Invitation, invitation_id)


async def get_pending_for_org_email(
    db: AsyncSession, *, organization_id: UUID, email: str
) -> Invitation | None:
    result = await db.execute(
        select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email == email.lower(),
            Invitation.status == InvitationStatus.PENDING.value,
        )
    )
    return result.scalar_one_or_none()


async def first_pending_admitting(db: AsyncSession, *, email: str) -> Invitation | None:
    """A live invitation, in any organization, that admits this address.

    Asked by the signup policy when this deployment is `invite_only`: an invited
    person has no account yet and `InvitationService.accept` requires one, so
    without this the invitation flow would be exactly what closing registration
    broke.

    Cross-tenant by construction, and it has to be - registration happens before
    any organization is chosen, so there is no tenant to scope to. What keeps that
    safe is where the answer goes: the *caller* turns this into a boolean refusal,
    so a stranger probing the sign-up form learns that somebody invited this
    address and never which organization did.

    Two shapes admit, and one deliberately does not:

    - an **email invitation** for exactly this address;
    - a **link scoped to a domain**, where the address is at that domain.

    A link with neither an address nor a domain does not, even though anyone
    holding it may join once they have an account: the request would carry no proof
    of possession, so honouring one would mean a single open link anywhere in the
    deployment turning `invite_only` back into `open` for the whole internet. A
    registration that *does* carry the token is admitted by `admits` instead
    (#916), which is what possession buys.

    The row rather than a boolean because a link with a `max_uses` has to have a
    use **reserved** against it before the account is created - see
    :func:`reserve_use`. `used_count + reserved_emails` is what "used up" means, and
    both are compared here so an exhausted link stops admitting registrations as
    well as acceptances.
    """
    normalized = email.strip().lower()
    domain = normalized.rpartition("@")[2]
    result = await db.execute(
        select(Invitation)
        .where(
            Invitation.status == InvitationStatus.PENDING.value,
            Invitation.expires_at > datetime.now(UTC),
            or_(
                Invitation.email == normalized,
                and_(
                    Invitation.email.is_(None),
                    Invitation.email_domain == domain,
                    _has_capacity_for(normalized),
                ),
            ),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


def _spent() -> ColumnElement[int]:
    """How much of a link's capacity is gone: acceptances plus reservations."""
    return Invitation.used_count + func.jsonb_array_length(Invitation.reserved_emails)


def _holds(email: str) -> ColumnElement[bool]:
    """Whether this address already has a use reserved on the row.

    `jsonb_exists` rather than the `?` operator it spells: the function form
    compiles with a plain text bind, which is what lets the predicate be read as
    SQL in a test and keeps the operator out of a driver's paramstyle.
    """
    return func.jsonb_exists(Invitation.reserved_emails, email)


def _has_capacity_for(email: str) -> ColumnElement[bool]:
    """Whether this link still admits `email` - already reserved counts as yes.

    Idempotent on purpose: a registration retried after a network error must not be
    refused by the reservation its first attempt already made.
    """
    return or_(
        _holds(email),
        Invitation.max_uses.is_(None),
        _spent() < Invitation.max_uses,
    )


async def reserve_use(db: AsyncSession, *, invitation_id: UUID, email: str) -> bool:
    """Hold one of a link's uses for an address that is about to register.

    The defect this closes: `used_count` counts *acceptances*, and acceptance needs
    a session, so a one-use link admitted an unbounded number of registrations on
    an `invite_only` deployment - each one checking a count nothing had yet
    incremented. One link posted in a channel, and closing sign-up was closed to
    nobody.

    Atomic, and it has to be: two registrations racing on the last use would both
    read the same count. A single conditional `UPDATE` takes the row lock, and
    Postgres re-evaluates the `WHERE` against the version it locked - so the second
    one sees the first one's reservation and is refused. A count read in Python and
    written back would not be.

    Answers whether the address may proceed. `True` for a link with no `max_uses`,
    which reserves nothing because it bounds nothing, and for an address already
    holding a reservation.

    A reservation nobody accepts stays spent, which is the intended reading:
    `max_uses` is how many people a link admits, and somebody who created an
    account with it was admitted. It dies with the invitation, since an expired or
    revoked row admits nobody.

    Being a bulk `UPDATE` it **expires** any instance of the row this session holds,
    so a caller reading the invitation afterwards reloads it first. No path does
    both: reserving happens while registering, and releasing happens in the request
    that accepts, which is a session later.
    """
    normalized = email.strip().lower()
    result = await db.execute(
        update(Invitation)
        .where(Invitation.id == invitation_id, _has_capacity_for(normalized))
        .values(
            reserved_emails=case(
                (_holds(normalized), Invitation.reserved_emails),
                # `jsonb_array || jsonb_string` appends one element, which is what
                # `to_jsonb` of a text value produces.
                else_=Invitation.reserved_emails.concat(func.to_jsonb(cast(normalized, Text))),
            )
        )
    )
    await db.flush()
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement returns `CursorResult`, which does.
    return bool(result.rowcount)  # ty: ignore[unresolved-attribute]


async def list_for_org(
    db: AsyncSession,
    organization_id: UUID,
    *,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[Invitation]:
    query = select(Invitation).where(Invitation.organization_id == organization_id)
    if status:
        query = query.where(Invitation.status == status)
    query = query.order_by(Invitation.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    email: str | None,
    role: str = OrgRole.MEMBER.value,
    invited_by_user_id: UUID,
    ttl_days: int = _INVITE_TTL_DAYS,
    max_uses: int | None = None,
    email_domain: str | None = None,
) -> Invitation:
    invite = Invitation(
        organization_id=organization_id,
        # Null means a link: one row anybody holding the token may accept.
        email=email.lower() if email else None,
        role=role,
        max_uses=max_uses,
        email_domain=email_domain.lower() if email_domain else None,
        invited_by_user_id=invited_by_user_id,
        token=secrets.token_urlsafe(32),
        status=InvitationStatus.PENDING.value,
        expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
    )
    db.add(invite)
    await db.flush()
    await db.refresh(invite)
    return invite


async def accept(
    db: AsyncSession,
    invite: Invitation,
    *,
    accepted_by_user_id: UUID,
) -> Invitation:
    invite.status = InvitationStatus.ACCEPTED.value
    invite.accepted_at = datetime.now(UTC)
    invite.accepted_by_user_id = accepted_by_user_id
    await db.flush()
    await db.refresh(invite)
    return invite


async def revoke(db: AsyncSession, invite: Invitation) -> Invitation:
    invite.status = InvitationStatus.REVOKED.value
    await db.flush()
    await db.refresh(invite)
    return invite


async def expire(db: AsyncSession, invite: Invitation) -> Invitation:
    invite.status = InvitationStatus.EXPIRED.value
    await db.flush()
    await db.refresh(invite)
    return invite


async def expire_stale(db: AsyncSession) -> int:
    """Mark all PENDING invitations past their expiry as EXPIRED. Returns count updated."""
    result = await db.execute(
        update(Invitation)
        .where(
            Invitation.status == InvitationStatus.PENDING.value,
            Invitation.expires_at < datetime.now(UTC),
        )
        .values(status=InvitationStatus.EXPIRED.value)
    )
    await db.flush()
    return result.rowcount  # ty: ignore[unresolved-attribute]


async def record_use(
    db: AsyncSession, invite: Invitation, *, email: str | None = None
) -> Invitation:
    """One more person came in through a link.

    A link stays pending until it is exhausted or revoked - that is what makes
    it a link. An email invitation is marked accepted instead, by `accept`,
    because an address is its own limit of one.

    `email` releases the reservation that address made when it registered, in the
    same step that counts the acceptance - so the capacity a registration held is
    moved into `used_count` rather than spent twice. Without it a one-use link
    would admit the registration and then refuse the acceptance it exists for.
    """
    invite.used_count += 1
    if email is not None:
        invite.reserved_emails = [
            held for held in invite.reserved_emails if held != email.strip().lower()
        ]
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        invite.status = InvitationStatus.ACCEPTED.value
    await db.flush()
    await db.refresh(invite)
    return invite
