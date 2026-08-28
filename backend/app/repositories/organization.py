"""Organization repository (PostgreSQL async)."""

import re
import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import OrgRoleName
from app.db.models.agent import Agent
from app.db.models.organization import Organization, OrganizationMember, OrgRole
from app.db.models.user import User
from app.repositories._search import contains_ci


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


async def list_created_by(db: AsyncSession, user_id: UUID) -> list[Organization]:
    """Every organization this user created - the rows that block their deletion.

    `organizations.created_by_user_id` is `ON DELETE RESTRICT`, so each of these
    has to be handed on or removed before the user row can go (#9).
    """
    result = await db.execute(
        select(Organization)
        .where(Organization.created_by_user_id == user_id)
        .order_by(Organization.is_personal.desc(), Organization.created_at.asc())
    )
    return list(result.scalars().all())


async def reassign_creator(
    db: AsyncSession, *, org: Organization, new_creator_id: UUID
) -> Organization:
    org.created_by_user_id = new_creator_id
    await db.flush()
    await db.refresh(org)
    return org


async def list_for_user(db: AsyncSession, user_id: UUID) -> list[tuple[Organization, str]]:
    """Each organization the user belongs to, with the role their membership carries.

    The role comes off the same membership row the join already filters on, so a
    caller needs no second per-organization lookup to learn it (#953).
    """
    result = await db.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.is_personal.desc(), Organization.created_at.asc())
    )
    return [(org, role) for org, role in result.all()]


async def member_counts_for(db: AsyncSession, org_ids: list[UUID]) -> dict[UUID, int]:
    """How many members each of the named organizations has, in one grouped query.

    One read for a whole page of organizations rather than a `count(*)` per row
    (#953). An organization absent from the result has no members; every id the
    caller passes for a listing has at least the caller, so in practice each is
    present.
    """
    if not org_ids:
        return {}
    result = await db.execute(
        select(OrganizationMember.organization_id, func.count(OrganizationMember.id))
        .where(OrganizationMember.organization_id.in_(org_ids))
        .group_by(OrganizationMember.organization_id)
    )
    return dict(result.all())


async def list_owned_by(db: AsyncSession, user_id: UUID) -> list[Organization]:
    """Non-personal organizations where the user holds an Owner membership.

    Distinct from `list_created_by`: ownership moves without the creator FK
    moving, so a user can be the sole Owner of an org they did not create - one
    `list_created_by` never returns, whose only owner would otherwise cascade
    away on the user's deletion and leave it ownerless (#1117).
    """
    result = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.role == OrgRoleName.OWNER.value,
            Organization.is_personal.is_(False),
        )
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


async def set_avatar_color(
    db: AsyncSession, org: Organization, *, color: int | None
) -> Organization:
    """Set or clear the organization's default-avatar colour.

    Its own function for the same reason as :func:`set_monthly_budget`:
    :func:`update` skips a `None` argument, so it cannot express "reset to auto".
    """
    org.avatar_color = color
    await db.flush()
    await db.refresh(org)
    return org


async def set_chat_approval_waiver(
    db: AsyncSession, org: Organization, *, allowed: bool
) -> Organization:
    """Allow or forbid chat sessions here granting standing consent (#925).

    Its own function rather than a field on :func:`update`, which skips a `None`
    argument and so cannot express a boolean somebody deliberately set to false.
    """
    org.chat_may_waive_approvals = allowed
    await db.flush()
    await db.refresh(org)
    return org


async def delete(db: AsyncSession, org: Organization) -> None:
    await db.delete(org)
    await db.flush()


async def count_owned_by(db: AsyncSession, user_id: UUID) -> int:
    """How many organizations this account owns, personal one included.

    Owned rather than joined: being invited into ten organizations is somebody
    else's decision, and a ceiling one person cannot control is a ceiling that
    locks them out of creating their own.
    """
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.role == OrgRoleName.OWNER.value,
        )
    )
    return result.scalar() or 0


async def count_members(db: AsyncSession, org_id: UUID) -> int:
    result = await db.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == org_id
        )
    )
    return result.scalar() or 0


type AdminOrganizationRow = tuple[Organization, int, int, UUID | None, str | None, str | None]


async def admin_list_with_counts(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    kind: str = "all",
) -> tuple[list[AdminOrganizationRow], int]:
    """Every organization on the deployment, with its size and who answers for it.

    Deliberately cross-tenant, and only ever reached behind the `is_app_admin`
    gate: this is the one surface that answers "what tenants exist" at all.

    Narrowing, ordering and paging all happen here rather than in the page,
    which is the whole point - a client sort over one server page claims a
    whole-collection order that fifty rows cannot deliver, so the admin's list
    had no sort at all until this (#921).

    The owner is the earliest of them, because an organization can hold several
    and the founder is the one a deployment admin means; `DISTINCT ON` picks it
    in the same pass rather than in a query per row. Every owner field is
    nullable: an organization whose last owner left has none, which is a state
    the deployment admin is the one person able to fix.
    """
    member_counts = (
        select(
            OrganizationMember.organization_id,
            func.count(OrganizationMember.user_id).label("member_count"),
        )
        .group_by(OrganizationMember.organization_id)
        .subquery()
    )
    agent_counts = (
        select(Agent.organization_id, func.count(Agent.id).label("agent_count"))
        .group_by(Agent.organization_id)
        .subquery()
    )
    owners = (
        select(
            OrganizationMember.organization_id,
            User.id.label("owner_user_id"),
            User.email.label("owner_email"),
            User.full_name.label("owner_name"),
        )
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.role == OrgRole.OWNER.value)
        .distinct(OrganizationMember.organization_id)
        .order_by(OrganizationMember.organization_id, OrganizationMember.joined_at)
        .subquery()
    )
    member_count = func.coalesce(member_counts.c.member_count, 0).label("member_count")
    agent_count = func.coalesce(agent_counts.c.agent_count, 0).label("agent_count")

    def joined[T: tuple](stmt: Select[T]) -> Select[T]:
        # The count query carries the same joins as the page query because the
        # search reaches the owner's address through one of them. None of the
        # three can multiply a row: each yields at most one per organization.
        return (
            stmt.outerjoin(member_counts, member_counts.c.organization_id == Organization.id)
            .outerjoin(agent_counts, agent_counts.c.organization_id == Organization.id)
            .outerjoin(owners, owners.c.organization_id == Organization.id)
        )

    query = joined(
        select(
            Organization,
            member_count,
            agent_count,
            owners.c.owner_user_id,
            owners.c.owner_email,
            owners.c.owner_name,
        )
    )
    count_query = joined(select(func.count()).select_from(Organization))

    conditions: list[ColumnElement[bool]] = []
    if search:
        # The three things a deployment admin has to go on: what the tenant is
        # called, what it is called in a URL, and who to ask about it.
        conditions.append(
            contains_ci(Organization.name, search)
            | contains_ci(Organization.slug, search)
            | contains_ci(owners.c.owner_email, search)
        )
    if kind == "personal":
        conditions.append(Organization.is_personal.is_(True))
    elif kind == "team":
        conditions.append(Organization.is_personal.is_(False))
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    sort_columns = {
        "name": Organization.name,
        "slug": Organization.slug,
        "members": member_count,
        "agents": agent_count,
        "created_at": Organization.created_at,
    }
    column = sort_columns.get(sort_by, Organization.created_at)
    ordered = column.desc() if sort_dir == "desc" else column.asc()
    # The id breaks the tie, so paging is stable: two organizations sharing a
    # name or a member count would otherwise be ordered by whatever the planner
    # returned, and a row could appear on two pages or on neither.
    query = query.order_by(ordered, Organization.id).offset(skip).limit(limit)

    total = await db.scalar(count_query) or 0
    rows = (await db.execute(query)).all()
    return [
        (organization, int(members), int(agents), owner_id, owner_email, owner_name)
        for organization, members, agents, owner_id, owner_email, owner_name in rows
    ], total
