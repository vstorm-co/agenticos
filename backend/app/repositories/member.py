"""OrganizationMember repository (PostgreSQL async)."""

from typing import Literal, NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import OrganizationMember, OrgRole
from app.db.models.user import User


async def get(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> OrganizationMember | None:
    """The membership, optionally locked for the rest of the transaction.

    `for_update` takes a row lock, so a caller that decides something from the
    role it reads and then writes it back cannot be overtaken by a concurrent
    change to that same row - the classic read-check-write race under
    `READ COMMITTED`. Left off by default: a lock costs a caller that only reads.
    """
    query = select(OrganizationMember).where(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_active(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> OrganizationMember | None:
    """The membership, but only while the account behind it can still sign in.

    Deactivating a user leaves their membership row exactly where it was, so
    anything reading a role off `get` alone answers with the authority of an account
    that is refused everywhere a person signs in. That is only a difference on the
    paths where nobody is signed in: `access.publisher_context`, the reason this
    exists, and the channel router's `_membership_context`, which reads a linked
    sender's own role off a chat account that stays linked after the deactivation.

    Joined rather than a second read: it is answered on every turn a public surface
    takes, and two round trips for one decision is one of them that can be true
    while the other is stale.
    """
    result = await db.execute(
        select(OrganizationMember)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            User.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_for_org(
    db: AsyncSession,
    organization_id: UUID,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[tuple[OrganizationMember, str, str | None, str | None, int | None]]:
    """Return (member, email, full_name, avatar_url, avatar_color) tuples by join date.

    `id` breaks the tie, and it is what makes paging through this safe. Two people
    invited in one request share a `joined_at`, Postgres is free to return tied
    rows in either order, and a page boundary falling inside a tie then shows one
    member twice and another never - the same defect the sessions listing has its
    own tie-breaker for. `useMembers` reads every page to fill the conversation
    share picker, so an unstable order there is a colleague who cannot be shared
    with (#931).
    """
    result = await db.execute(
        select(
            OrganizationMember,
            User.email,
            User.full_name,
            User.avatar_url,
            User.avatar_color,
        )
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.joined_at.asc(), OrganizationMember.id)
        .offset(skip)
        .limit(limit)
    )
    return [(row[0], row[1], row[2], row[3], row[4]) for row in result.all()]


class MemberIdentity(NamedTuple):
    """What a listing shows about a person: their address and their face."""

    email: str | None
    avatar_url: str | None


async def get_identities_for_users(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_ids: list[UUID],
) -> dict[UUID, MemberIdentity]:
    """Map user id -> email and avatar for members of one organization.

    The same tenant restriction as `get_emails_for_users`, and for the same
    reason: a grant list must not become a way to resolve people outside it.
    Separate from that function rather than replacing it because most callers
    want a name and would carry an avatar they never render.
    """
    if not user_ids:
        return {}
    result = await db.execute(
        select(OrganizationMember.user_id, User.email, User.avatar_url)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id.in_(user_ids),
        )
    )
    return {
        user_id: MemberIdentity(email=email, avatar_url=avatar_url)
        for user_id, email, avatar_url in result.all()
    }


async def get_emails_for_users(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_ids: list[UUID],
) -> dict[UUID, str | None]:
    """Map user id -> email for members of one organization.

    Restricted to members so a grant list cannot be used to resolve the email of
    someone outside the tenant.
    """
    if not user_ids:
        return {}
    result = await db.execute(
        select(OrganizationMember.user_id, User.email)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id.in_(user_ids),
        )
    )
    return {row[0]: row[1] for row in result.all()}


async def list_member_ids_for(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_ids: list[UUID],
) -> set[UUID]:
    """Which of `user_ids` are active members of this organization.

    The membership join is the security property, not an optimisation. These
    ids come from an agent's spec - `AlertSpec.user_ids`, written by whoever
    may edit the agent - so without the join an author could name a user id
    from another organization and have them notified of the agent's name,
    their organization's name and what a run spent. `get_emails_for_users`
    above carries the same restriction for the same reason, but this is
    identity-only (#1598): a channel's preference is applied afterward, per
    recipient, not folded into who is a candidate at all.

    Also filters on `is_active`: a deactivated member contributes nothing
    rather than raising - a spec naming one person who has left must not
    silence the rest of the audience.
    """
    if not user_ids:
        return set()
    result = await db.execute(
        select(User.id)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id.in_(user_ids),
            User.is_active.is_(True),
        )
    )
    return {row[0] for row in result.all()}


async def list_member_ids_by_role(
    db: AsyncSession,
    *,
    organization_id: UUID,
    roles: list[str],
) -> list[UUID]:
    """User ids of the members holding one of `roles`.

    Identity only, no preference filter (#1598): a notification write happens
    once per resolved *person*, and a channel's preference is applied
    afterward, per recipient - never folded into who is a candidate at all.
    """
    result = await db.execute(
        select(User.id)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role.in_(roles),
            User.is_active.is_(True),
        )
    )
    return [row[0] for row in result.all()]


async def list_app_admin_ids(db: AsyncSession) -> list[UUID]:
    """User ids of the deployment's app admins.

    Identity only, no preference filter, for the same reason
    `list_member_ids_by_role` is (#1598).
    """
    result = await db.execute(
        select(User.id).where(User.is_app_admin.is_(True), User.is_active.is_(True))
    )
    return [row[0] for row in result.all()]


async def has_membership_in_any(
    db: AsyncSession,
    *,
    user_id: UUID,
    organization_ids: list[UUID],
    roles: list[str] | None = None,
) -> bool:
    """Whether `user_id` currently belongs to any of `organization_ids`.

    `roles`, when given, narrows to holding one of them - an announcement's
    audience can be narrowed to owners and admins (Decision 5), and a member
    demoted out of every named role no longer qualifies even though their
    plain membership survives.
    """
    conditions = [
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id.in_(organization_ids),
    ]
    if roles is not None:
        conditions.append(OrganizationMember.role.in_(roles))
    return (await db.scalar(select(OrganizationMember.id).where(*conditions).limit(1))) is not None


async def has_any_membership(
    db: AsyncSession,
    *,
    user_id: UUID,
    roles: list[str] | None = None,
) -> bool:
    """Whether `user_id` currently belongs to any organization at all.

    The "all organizations" half of an announcement's audience (Decision 5):
    reaching everybody means everybody who is currently a member of something,
    not a hardcoded list of organizations that existed when it was sent.
    """
    conditions = [OrganizationMember.user_id == user_id]
    if roles is not None:
        conditions.append(OrganizationMember.role.in_(roles))
    return (await db.scalar(select(OrganizationMember.id).where(*conditions).limit(1))) is not None


async def list_member_ids_for_audience(
    db: AsyncSession,
    *,
    organization_ids: list[UUID] | Literal["all"],
    roles: list[str] | None = None,
) -> set[UUID]:
    """Every active member currently matching an announcement's audience
    spec (#1598, Decision 5) - resolved fresh at send time, the same
    membership `has_any_membership`/`has_membership_in_any` re-check at read
    time. `"all organizations"` means everybody who is currently a member of
    something, not a snapshot of who belonged when it was sent; a
    role-narrowed spec matches only those roles, in any of the named
    organizations (or in any organization at all, for `"all"`). `roles` is a
    set of names rather than one, because an `"admin"` audience means owners
    too - `announcement_audience_roles` is the single place that widening is
    decided, read by the read-time gate as well, so the two ends of a send
    cannot disagree about who was in the audience.

    Identity only, no preference filter - the same split every other
    audience resolver in this feature draws (Decision 4): a channel's
    preference is applied afterward, per recipient, never folded into who is
    a candidate at all.
    """
    if organization_ids != "all" and not organization_ids:
        return set()
    conditions = [User.is_active.is_(True)]
    if organization_ids != "all":
        conditions.append(OrganizationMember.organization_id.in_(organization_ids))
    if roles is not None:
        conditions.append(OrganizationMember.role.in_(roles))
    result = await db.execute(
        select(User.id)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(*conditions)
        .distinct()
    )
    return {row[0] for row in result.all()}


async def count_for_org(db: AsyncSession, organization_id: UUID) -> int:
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id
        )
    )
    return result.scalar() or 0


async def first_owner_id(db: AsyncSession, *, organization_id: UUID) -> UUID | None:
    """The earliest-joined owner - who system-made rows are attributed to."""
    return await db.scalar(
        select(OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == OrgRole.OWNER.value,
        )
        .order_by(OrganizationMember.joined_at.asc())
        .limit(1)
    )


async def other_owner_id(
    db: AsyncSession, *, organization_id: UUID, exclude_user_id: UUID
) -> UUID | None:
    """The earliest-joined owner who is not this user - who a shared org is handed
    to when its creator's account is deleted (#9)."""
    return await db.scalar(
        select(OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == OrgRole.OWNER.value,
            OrganizationMember.user_id != exclude_user_id,
        )
        .order_by(OrganizationMember.joined_at.asc())
        .limit(1)
    )


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str = OrgRole.MEMBER.value,
    invited_by_user_id: UUID | None = None,
) -> OrganizationMember:
    member = OrganizationMember(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        invited_by_user_id=invited_by_user_id,
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return member


async def update_role(
    db: AsyncSession,
    member: OrganizationMember,
    *,
    role: str,
) -> OrganizationMember:
    member.role = role
    await db.flush()
    await db.refresh(member)
    return member


async def delete(db: AsyncSession, member: OrganizationMember) -> None:
    await db.delete(member)
    await db.flush()
