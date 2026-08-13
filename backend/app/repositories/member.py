"""OrganizationMember repository (PostgreSQL async)."""

from typing import NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import OrganizationMember, OrgRole
from app.db.models.user import NotificationPreference, User


async def get(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> OrganizationMember | None:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
    )
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
    paths where nobody is signed in - see `access.publisher_context`, which is the
    one caller and the reason this exists.

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
) -> list[tuple[OrganizationMember, str, str | None, str | None]]:
    """Return (member, email, full_name, avatar_url) tuples ordered by join date."""
    result = await db.execute(
        select(OrganizationMember, User.email, User.full_name, User.avatar_url)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.joined_at.asc())
        .offset(skip)
        .limit(limit)
    )
    return [(row[0], row[1], row[2], row[3]) for row in result.all()]


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


async def list_emails_by_role(
    db: AsyncSession,
    *,
    organization_id: UUID,
    roles: list[str],
    preference: NotificationPreference | None = None,
) -> list[str]:
    """Addresses of the members holding one of `roles`.

    Emails rather than users because the only caller is notification: what it
    needs is somewhere to send, and loading whole users to read one column
    invites a second caller that starts making decisions on the rest.

    `preference` names the notification opt-out to honour: a member who has
    switched that column off is left out of the result, so the caller never
    holds an address it is not allowed to mail.
    """
    conditions = [
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.role.in_(roles),
        User.is_active.is_(True),
    ]
    if preference is not None:
        conditions.append(getattr(User, preference).is_(True))
    result = await db.execute(
        select(User.email)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(*conditions)
    )
    return [row[0] for row in result.all()]


async def list_emails_for_members(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_ids: list[UUID],
    preference: NotificationPreference | None = None,
) -> list[str]:
    """Addresses of named people, but only those who are members of this organization.

    The membership join is the security property, not an optimisation. These ids
    come from an agent's spec - `AlertSpec.user_ids`, written by whoever may edit
    the agent - so without the join an author could name a user id from another
    organization and have them mailed the agent's name, their organization's name
    and what a run spent. `get_emails_for_users` above carries the same
    restriction for the same reason.

    Differs from that one by also filtering on `is_active` and on the opt-out
    column, because the caller is notification: it must never hold an address it
    is not allowed to mail. A user who left, was deactivated, or switched this
    kind of mail off contributes nothing rather than raising - a spec naming one
    person who is gone must not silence the rest of the audience.
    """
    if not user_ids:
        return []
    conditions = [
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id.in_(user_ids),
        User.is_active.is_(True),
    ]
    if preference is not None:
        conditions.append(getattr(User, preference).is_(True))
    result = await db.execute(
        select(User.email)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(*conditions)
    )
    return [row[0] for row in result.all()]


async def list_app_admin_emails(
    db: AsyncSession,
    *,
    preference: NotificationPreference | None = None,
) -> list[str]:
    """Addresses of the deployment's app admins, whatever organization they are in.

    Deliberately not joined to `organization_members`. An app admin administers
    the deployment and reaches every organization in it without holding a
    membership row - `get_auth_context` admits them to an organization they are
    not a member of - so a query scoped by membership would silently omit exactly
    the person who is supposed to hear when something runs out of money.

    In the same module as the role query rather than in `user`, because the two
    answer one question between them - "who are the administrators here" - and a
    caller that found one and not the other would mail half of them.
    """
    conditions = [User.is_app_admin.is_(True), User.is_active.is_(True)]
    if preference is not None:
        conditions.append(getattr(User, preference).is_(True))
    result = await db.execute(select(User.email).where(*conditions))
    return [row[0] for row in result.all()]


async def count_for_org(db: AsyncSession, organization_id: UUID) -> int:
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id
        )
    )
    return result.scalar() or 0


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
