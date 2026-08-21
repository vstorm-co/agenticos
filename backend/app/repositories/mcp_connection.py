"""Data access for MCP server connections (PostgreSQL async).

Two owners share one table, so nearly every query here filters on `scope` as
well as on the id that identifies the owner. The filter is not belt-and-braces:
a personal query that matched an organization row would hand a member a shared
credential to edit, and an organization query that matched a personal one would
put somebody's private token inside a published agent.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from app.db.models.mcp_connection import McpConnection


async def get_by_id(db: AsyncSession, connection_id: UUID) -> McpConnection | None:
    result = await db.execute(select(McpConnection).where(McpConnection.id == connection_id))
    return result.scalar_one_or_none()


async def get_by_id_for_update(db: AsyncSession, connection_id: UUID) -> McpConnection | None:
    """Fetch a connection and lock the row (`SELECT ... FOR UPDATE`).

    Used before spending an OAuth refresh token, so two concurrent chat turns
    can't both redeem it. `lazyload` drops the model's eager join on `users`
    (PostgreSQL refuses `FOR UPDATE` on the nullable side of an outer join),
    and `populate_existing` re-reads the columns so the caller sees what the
    other transaction committed rather than the stale identity-map copy.
    """
    result = await db.execute(
        select(McpConnection)
        .where(McpConnection.id == connection_id)
        .options(lazyload(McpConnection.user))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_org_scoped_by_id(
    db: AsyncSession, *, connection_id: UUID, organization_id: UUID
) -> McpConnection | None:
    """One organization-scoped connection, looked up inside one organization.

    Both filters carry weight. `organization_id` stops an agent spec from
    another tenant reaching this row, and `scope` stops a member's personal
    connection being bound to a published agent even though it belongs to the
    same organization - a shared agent must not run on somebody's private token.
    """
    result = await db.execute(
        select(McpConnection).where(
            McpConnection.id == connection_id,
            McpConnection.organization_id == organization_id,
            McpConnection.scope == "org",
        )
    )
    return result.scalar_one_or_none()


async def list_org_scoped(
    db: AsyncSession, *, organization_id: UUID
) -> tuple[list[McpConnection], int]:
    """Every organization-scoped connection in one organization.

    Ordered like :func:`list_for_user` - by creation - because a run that needs
    to lock several rows takes them in list order, and two lists that disagree
    on the order are two ways to deadlock.
    """
    stmt = (
        select(McpConnection)
        .where(
            McpConnection.organization_id == organization_id,
            McpConnection.scope == "org",
        )
        .order_by(McpConnection.created_at.asc())
    )
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    items = list((await db.execute(stmt)).scalars())
    return items, total


async def get_by_name(db: AsyncSession, *, user_id: UUID, name: str) -> McpConnection | None:
    result = await db.execute(
        select(McpConnection).where(
            McpConnection.user_id == user_id,
            McpConnection.name == name,
            McpConnection.scope == "user",
        )
    )
    return result.scalar_one_or_none()


async def get_org_scoped_by_name(
    db: AsyncSession, *, organization_id: UUID, name: str
) -> McpConnection | None:
    """The organization connection called *name*, if there is one.

    Names are how a person tells two servers apart in the Builder and they
    become the agent's tool prefix, so a duplicate is not a cosmetic problem.
    """
    result = await db.execute(
        select(McpConnection).where(
            McpConnection.organization_id == organization_id,
            McpConnection.name == name,
            McpConnection.scope == "org",
        )
    )
    return result.scalar_one_or_none()


async def get_org_scoped_by_catalog_key(
    db: AsyncSession, *, organization_id: UUID, catalog_key: str
) -> McpConnection | None:
    """The organization's connection for this catalog entry, whatever it is named.

    The catalog key is the identity the frontend joins a trigger portal to its
    connection by, so a flow that must find "the GitHub connection" looks here
    rather than at the name - a name is the person's label and may be anything.
    `first()` rather than `one`: nothing constrains an organization to a single
    row per catalog entry, and for an upgrade the oldest is the one agents were
    bound to.
    """
    result = await db.execute(
        select(McpConnection)
        .where(
            McpConnection.organization_id == organization_id,
            McpConnection.catalog_key == catalog_key,
            McpConnection.scope == "org",
        )
        .order_by(McpConnection.created_at.asc())
    )
    return result.scalars().first()


async def list_oauth_connections(db: AsyncSession) -> list[McpConnection]:
    """Every OAuth connection on the deployment, for the scheduled sweep.

    Deliberately unscoped: the sweep is about the deployment's health, not about
    a tenant, and it reads nothing a tenant could see - only whether a token
    still refreshes. Anything serving a member goes through
    :func:`list_for_user` or :func:`list_org_scoped`. Grep for this function
    when auditing cross-tenant reads.
    """
    result = await db.execute(
        select(McpConnection).where(
            McpConnection.auth_type == "oauth",
            McpConnection.oauth_payload.is_not(None),
        )
    )
    return list(result.scalars().all())


async def get_by_oauth_state(db: AsyncSession, state: str) -> McpConnection | None:
    """Find the connection awaiting this OAuth callback (state is the CSRF token)."""
    result = await db.execute(select(McpConnection).where(McpConnection.oauth_state == state))
    return result.scalar_one_or_none()


async def list_for_user(
    db: AsyncSession, *, user_id: UUID, enabled_only: bool = False
) -> tuple[list[McpConnection], int]:
    stmt = (
        select(McpConnection)
        .where(McpConnection.user_id == user_id, McpConnection.scope == "user")
        .order_by(McpConnection.created_at.asc())
    )
    if enabled_only:
        stmt = stmt.where(McpConnection.is_enabled.is_(True))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    items = list((await db.execute(stmt)).scalars())
    return items, total


async def create(
    db: AsyncSession,
    *,
    user_id: UUID,
    name: str,
    url: str,
    auth_token: str | None,
    secret_key_version: int,
    allowed_tools: list[str] | None,
    is_enabled: bool = True,
    auth_type: str = "bearer",
    oauth_state: str | None = None,
    oauth_payload: str | None = None,
    oauth_pending_payload: str | None = None,
) -> McpConnection:
    connection = McpConnection(
        user_id=user_id,
        name=name,
        url=url,
        auth_token=auth_token,
        secret_key_version=secret_key_version,
        allowed_tools=allowed_tools,
        is_enabled=is_enabled,
        auth_type=auth_type,
        oauth_state=oauth_state,
        oauth_payload=oauth_payload,
        oauth_pending_payload=oauth_pending_payload,
    )
    db.add(connection)
    await db.flush()
    await db.refresh(connection)
    return connection


async def create_org_scoped(
    db: AsyncSession,
    *,
    organization_id: UUID,
    created_by_user_id: UUID,
    name: str,
    url: str,
    sealed_token: str | None,
    secret_key_version: int,
    allowed_tools: list[str] | None,
    catalog_key: str | None,
    is_enabled: bool = True,
    auth_type: str = "bearer",
    oauth_state: str | None = None,
    oauth_pending_payload: str | None = None,
) -> McpConnection:
    """Store a connection the organization owns.

    Separate from :func:`create` rather than a flag on it, because the two
    differ in the fields that matter: no `user_id` (the check constraint
    refuses one), a `created_by_user_id` that records rather than authorizes,
    and a catalog key. A single function taking both shapes would make the wrong
    combination expressible.
    """
    connection = McpConnection(
        organization_id=organization_id,
        created_by_user_id=created_by_user_id,
        scope="org",
        name=name,
        url=url,
        auth_token=sealed_token,
        secret_key_version=secret_key_version,
        allowed_tools=allowed_tools,
        catalog_key=catalog_key,
        is_enabled=is_enabled,
        auth_type=auth_type,
        oauth_state=oauth_state,
        oauth_pending_payload=oauth_pending_payload,
    )
    db.add(connection)
    await db.flush()
    await db.refresh(connection)
    return connection


async def update(
    db: AsyncSession,
    *,
    db_connection: McpConnection,
    update_data: dict[str, Any],
) -> McpConnection:
    for field, value in update_data.items():
        setattr(db_connection, field, value)
    await db.flush()
    await db.refresh(db_connection)
    return db_connection


async def delete(db: AsyncSession, *, db_connection: McpConnection) -> None:
    await db.delete(db_connection)
    await db.flush()
