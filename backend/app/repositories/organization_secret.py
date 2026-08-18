"""Organization secret repository (PostgreSQL async).

`organization_id` is a required keyword on every function here. A secret is
the last thing that should leak across tenants, and a forgotten filter must not
look like an ordinary call (see tests/test_org_scope_regression.py).
"""

from uuid import UUID

from sqlalchemy import bindparam, false, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility


async def get(
    db: AsyncSession, secret_id: UUID, *, organization_id: UUID
) -> OrganizationSecret | None:
    result = await db.execute(
        select(OrganizationSecret).where(
            OrganizationSecret.id == secret_id,
            OrganizationSecret.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(
    db: AsyncSession, name: str, *, organization_id: UUID
) -> OrganizationSecret | None:
    result = await db.execute(
        select(OrganizationSecret).where(
            OrganizationSecret.name == name,
            OrganizationSecret.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_kind(
    db: AsyncSession, *, organization_id: UUID, kind: str
) -> OrganizationSecret | None:
    """The organization's secret of a given kind, or None.

    For a kind an organization stores exactly one of and wants the credential
    itself rather than a picker - its GitHub OAuth App, read server-side to run a
    token exchange. Ordered by name so the choice is stable if more than one is
    ever stored; `list_secrets` remains the path for a chooser that shows them all.
    """
    result = await db.execute(
        select(OrganizationSecret)
        .where(
            OrganizationSecret.organization_id == organization_id,
            OrganizationSecret.kind == kind,
        )
        .order_by(OrganizationSecret.name.asc())
    )
    return result.scalars().first()


async def get_many(
    db: AsyncSession, secret_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, OrganizationSecret]:
    """Fetch several secrets at once - one query per run, not one per binding."""
    if not secret_ids:
        return {}
    result = await db.execute(
        select(OrganizationSecret).where(
            OrganizationSecret.id.in_(secret_ids),
            OrganizationSecret.organization_id == organization_id,
        )
    )
    return {secret.id: secret for secret in result.scalars().all()}


async def list_secrets(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None = None,
    see_all: bool = True,
    shared_ids: list[UUID] | None = None,
    purposes: list[str] | None = None,
) -> list[OrganizationSecret]:
    """Every secret in one organization, before access is resolved.

    `see_all` is the caller's role reaching the whole organization; when it is
    false only the caller's own keys, the organization-wide ones and those in
    `shared_ids` come back.

    `purposes` narrows to the keys a particular slot can use - the Tavily keys
    for a web-search binding, the OpenRouter ones for a model picker. Filtering
    here rather than in the caller keeps "which keys exist for X" one query
    instead of a list comprehension over the whole vault.
    """
    query = select(OrganizationSecret).where(OrganizationSecret.organization_id == organization_id)
    if purposes:
        query = query.where(OrganizationSecret.purpose.in_(purposes))
    if not see_all:
        # The same predicate every shared resource here uses: mine, the
        # organization's, or one explicitly shared with me. A team-visible key
        # nobody granted is deliberately invisible - "team" means named
        # members, not everybody.
        query = query.where(
            or_(
                OrganizationSecret.owner_user_id == user_id,
                OrganizationSecret.visibility == Visibility.ORG.value,
                OrganizationSecret.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    result = await db.execute(query.order_by(OrganizationSecret.name.asc()))
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    name: str,
    description: str | None,
    kind: str,
    purpose: str,
    visibility: str,
    owner_user_id: UUID | None,
    sealed_secret: str,
    hint: str,
    key_version: int,
    created_by_user_id: UUID | None,
) -> OrganizationSecret:
    secret = OrganizationSecret(
        organization_id=organization_id,
        name=name,
        description=description,
        kind=kind,
        purpose=purpose,
        visibility=visibility,
        owner_user_id=owner_user_id,
        sealed_secret=sealed_secret,
        hint=hint,
        key_version=key_version,
        created_by_user_id=created_by_user_id,
    )
    db.add(secret)
    await db.flush()
    await db.refresh(secret)
    return secret


async def update(
    db: AsyncSession, *, secret: OrganizationSecret, update_data: dict[str, object]
) -> OrganizationSecret:
    for field, value in update_data.items():
        setattr(secret, field, value)
    db.add(secret)
    await db.flush()
    await db.refresh(secret)
    return secret


async def delete(db: AsyncSession, secret_id: UUID, *, organization_id: UUID) -> bool:
    secret = await get(db, secret_id, organization_id=organization_id)
    if secret is None:
        return False
    await db.delete(secret)
    await db.flush()
    return True


async def agents_using(
    db: AsyncSession, *, organization_id: UUID, secret_id: UUID
) -> list[tuple[UUID, str]]:
    """Agents whose draft spec binds this secret to a capability.

    A JSONB containment check rather than a column, because a binding lives
    inside the spec - which is the right place for it: the spec is what gets
    versioned, exported and reviewed. The draft is queried rather than the
    published version because the question this answers is "what breaks if I
    delete this key", and an agent that is *about* to be published with it
    breaks just as thoroughly.
    """
    query = text(
        """
        SELECT id, name FROM agents
        WHERE organization_id = :organization_id
          AND draft_spec -> 'capabilities' @> :binding
        ORDER BY name
        """
    ).bindparams(
        bindparam("organization_id", type_=PG_UUID(as_uuid=True)),
        bindparam("binding", type_=JSONB),
    )
    result = await db.execute(
        query,
        {
            "organization_id": organization_id,
            "binding": [{"secret_id": str(secret_id)}],
        },
    )
    return [(row[0], row[1]) for row in result.all()]
