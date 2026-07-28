"""OrganizationMember repository (PostgreSQL async)."""

from typing import NamedTuple
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
) -> OrganizationMember | None:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
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
) -> list[str]:
    """Addresses of the members holding one of `roles`.

    Emails rather than users because the only caller is notification: what it
    needs is somewhere to send, and loading whole users to read one column
    invites a second caller that starts making decisions on the rest.
    """
    result = await db.execute(
        select(User.email)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role.in_(roles),
            User.is_active.is_(True),
        )
    )
    return [row[0] for row in result.all()]


async def count_for_org(db: AsyncSession, organization_id: UUID) -> int:
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id
        )
    )
    return result.scalar() or 0


async def count_billable_for_org(db: AsyncSession, organization_id: UUID) -> int:
    """Count billable members (Owner + Admin + Member; Viewer excluded)."""
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role != OrgRole.VIEWER.value,
        )
    )
    return result.scalar() or 0


async def has_owner(db: AsyncSession, organization_id: UUID) -> bool:
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == OrgRole.OWNER.value,
        )
    )
    return (result.scalar() or 0) > 0


async def list_orgs_for_user(db: AsyncSession, user_id: UUID) -> list[OrganizationMember]:
    result = await db.execute(
        select(OrganizationMember).where(OrganizationMember.user_id == user_id)
    )
    return list(result.scalars().all())


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
