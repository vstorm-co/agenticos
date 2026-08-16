"""Organization repository (PostgreSQL async)."""

import re
import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization, OrganizationMember


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:64] or "org"


async def get_by_id(db: AsyncSession, org_id: UUID) -> Organization | None:
    return await db.get(Organization, org_id)


async def get_by_id_for_update(db: AsyncSession, org_id: UUID) -> Organization | None:
    """Fetch an organization row and acquire a SELECT FOR UPDATE lock."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def list_all(db: AsyncSession) -> list[Organization]:
    """Every organization on the deployment.

    Deliberately unscoped, and only for work that is *about* the deployment
    rather than about a tenant - the skill seed, which installs the same
    bundled library everywhere. Anything serving a member goes through
    :func:`list_for_user`. Grep for this function when auditing cross-tenant
    reads.
    """
    result = await db.execute(select(Organization).order_by(Organization.created_at))
    return list(result.scalars().all())


async def get_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    return result.scalar_one_or_none()


async def get_personal_for_user(db: AsyncSession, user_id: UUID) -> Organization | None:
    result = await db.execute(
        select(Organization).where(
            Organization.created_by_user_id == user_id,
            Organization.is_personal.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_for_user(db: AsyncSession, user_id: UUID) -> list[Organization]:
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.is_personal.desc(), Organization.created_at.asc())
    )
    return list(result.scalars().all())


async def slug_exists(db: AsyncSession, slug: str) -> bool:
    result = await db.execute(select(func.count(Organization.id)).where(Organization.slug == slug))
    return (result.scalar() or 0) > 0


async def generate_unique_slug(db: AsyncSession, base: str) -> str:
    candidate = _slugify(base)
    if not await slug_exists(db, candidate):
        return candidate
    for i in range(2, 100):
        suffixed = f"{candidate}-{i}"
        if not await slug_exists(db, suffixed):
            return suffixed
    return f"{candidate}-{uuid.uuid4().hex[:6]}"


async def create(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    created_by_user_id: UUID,
    is_personal: bool = False,
    avatar_url: str | None = None,
    monthly_budget_usd: Decimal | None = None,
) -> Organization:
    org = Organization(
        name=name,
        slug=slug,
        created_by_user_id=created_by_user_id,
        is_personal=is_personal,
        avatar_url=avatar_url,
        monthly_budget_usd=monthly_budget_usd,
    )
    db.add(org)
    await db.flush()
    await db.refresh(org)
    return org


async def update(
    db: AsyncSession,
    org: Organization,
    *,
    name: str | None = None,
    avatar_url: str | None = None,
) -> Organization:
    if name is not None:
        org.name = name
    if avatar_url is not None:
        org.avatar_url = avatar_url
    await db.flush()
    await db.refresh(org)
    return org


async def set_monthly_budget(
    db: AsyncSession, org: Organization, *, limit_usd: Decimal | None
) -> Organization:
    """Set or remove the organization's monthly spending ceiling.

    Its own function rather than another keyword on :func:`update`, which skips
    any argument that is `None`. That convention cannot express clearing a
    nullable setting: "leave the cap alone" and "remove the cap" would both
    arrive as `None`, and the second is the one that costs money.
    """
    org.monthly_budget_usd = limit_usd
    await db.flush()
    await db.refresh(org)
    return org


async def delete(db: AsyncSession, org: Organization) -> None:
    await db.delete(org)
    await db.flush()


async def count_members(db: AsyncSession, org_id: UUID) -> int:
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == org_id
        )
    )
    return result.scalar() or 0
