"""Organization secret repository (PostgreSQL async).

`organization_id` is a required keyword on every function here. A secret is
the last thing that should leak across tenants, and a forgotten filter must not
look like an ordinary call (see tests/test_org_scope_regression.py).
"""

from uuid import UUID

from sqlalchemy import bindparam, false, or_, select, text
from sqlalchemy import update as sql_update
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


async def list_org_visible_by_kind(
    db: AsyncSession, *, organization_id: UUID, kind: str
) -> list[OrganizationSecret]:
    """The organization-visible secrets of a given kind, ordered by name.

    For a kind whose credential is *spent by the platform* rather than picked by
    a person - the GitHub OAuth App, read server-side to run a token exchange.
    Only `org`-visible rows qualify: a member's private secret of the same kind
    must never be silently spent for the whole organization's connection, which
    is what an unfiltered by-kind lookup did. All matches are returned so the
    caller can refuse ambiguity instead of taking whichever name sorts first;
    `list_secrets` remains the path for a chooser that shows them all.
    """
    result = await db.execute(
        select(OrganizationSecret)
        .where(
            OrganizationSecret.organization_id == organization_id,
            OrganizationSecret.kind == kind,
            OrganizationSecret.visibility == Visibility.ORG.value,
        )
        .order_by(OrganizationSecret.name.asc())
    )
    return list(result.scalars().all())


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


async def promote_owned_private_to_org(db: AsyncSession, *, owner_user_id: UUID) -> int:
    """Make every private secret this user owns org-visible, across all their orgs.

    Deliberately not org-scoped, unlike the rest of this module: it runs when the
    owner's account is deleted, and `owner_user_id` is about to be nulled by the
    `SET NULL` cascade. `ck_secret_private_needs_owner` forbids a private secret
    with no owner, so without this the delete violates the check and 500s (#9).
    Promoting to org visibility is the outcome the column comment names - a
    personal key whose owner leaves "becomes the organization's problem to clean
    up" - and it leaves the row reachable rather than stranded.

    Returns the number of rows promoted.
    """
    result = await db.execute(
        sql_update(OrganizationSecret)
        .where(
            OrganizationSecret.owner_user_id == owner_user_id,
            OrganizationSecret.visibility == Visibility.PRIVATE.value,
        )
        .values(visibility=Visibility.ORG.value)
    )
    await db.flush()
    return result.rowcount  # ty: ignore[unresolved-attribute]


async def agents_using_for_secrets(
    db: AsyncSession, *, organization_id: UUID, secret_ids: list[UUID]
) -> dict[UUID, list[tuple[UUID, str]]]:
    """For each secret, the agents whose draft spec binds it - in one query.

    The vault listing asks this of every secret on the page, so it is answered
    in one grouped read rather than one per secret (#953). A JSONB match rather
    than a column, because a binding lives inside the spec - which is the right
    place for it: the spec is what gets versioned, exported and reviewed. The
    *draft* is queried rather than the published version because "what breaks if
    I delete this key" includes an agent about to be published with it.

    Every requested id is a key in the result, mapping to its agents in name
    order; a secret nothing binds maps to an empty list.
    """
    usage: dict[UUID, list[tuple[UUID, str]]] = {secret_id: [] for secret_id in secret_ids}
    if not secret_ids:
        return usage
    # `jsonb_array_elements` errors on anything that is not an array, so the
    # `CASE` hands it an empty one for an agent whose spec has no `capabilities`
    # list - the same rows the per-secret `@>` containment quietly skipped.
    query = text(
        """
        SELECT DISTINCT a.id, a.name, cap ->> 'secret_id' AS secret_id
        FROM agents a
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(a.draft_spec -> 'capabilities') = 'array'
                THEN a.draft_spec -> 'capabilities'
                ELSE '[]'::jsonb
            END
        ) AS cap
        WHERE a.organization_id = :organization_id
          AND cap ->> 'secret_id' IN :secret_ids
        ORDER BY a.name
        """
    ).bindparams(
        bindparam("organization_id", type_=PG_UUID(as_uuid=True)),
        bindparam("secret_ids", expanding=True),
    )
    result = await db.execute(
        query,
        {"organization_id": organization_id, "secret_ids": [str(s) for s in secret_ids]},
    )
    for agent_id, name, secret_id in result.all():
        usage[UUID(secret_id)].append((agent_id, name))
    return usage
