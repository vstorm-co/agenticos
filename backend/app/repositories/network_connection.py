"""Tenant-scoped data access for Tailscale network connections."""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, TypedDict
from uuid import UUID

from sqlalchemy import and_, case, false, func, or_, select
from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.network_connection import NetworkConnection, NetworkPeerPayload
from app.db.models.organization import Organization
from app.schemas.network_connection import (
    NetworkAuthState,
    NetworkCleanupState,
    NetworkDesiredState,
    NetworkErrorCode,
    NetworkRuntimeState,
    NetworkScope,
)


class NetworkConnectionChanges(TypedDict, total=False):
    """Columns the lifecycle service may change without changing row ownership."""

    name: str
    desired_state: NetworkDesiredState
    auth_state: NetworkAuthState
    runtime_state: NetworkRuntimeState
    cleanup_state: NetworkCleanupState
    policy_generation: int
    state_payload: str | None
    login_payload: str | None
    secret_key_version: int
    enrollment_id: UUID | None
    enrollment_user_id: UUID | None
    enrollment_session_id: UUID | None
    enrollment_expires_at: datetime | None
    tailnet_name: str | None
    node_id: str | None
    peers: list[NetworkPeerPayload]
    last_seen_at: datetime | None
    last_error_code: NetworkErrorCode | None
    state_sequence: int


class NetworkConnectionSettlement(TypedDict, total=False):
    """Fail-closed fields allowed after no live runtime lease remains."""

    desired_state: Literal["paused", "revoked"]
    auth_state: Literal["not_connected", "expired", "error"]
    cleanup_state: Literal["manual", "complete"]
    state_payload: None
    tailnet_name: None
    node_id: None
    last_seen_at: None
    last_error_code: NetworkErrorCode | None


NetworkLeaseState = Literal["active", "revoked"]
MAX_LEASE_SECONDS = 15

# These values come only from a live, fenced node process. Control-plane actions
# may still clear encrypted data and set runtime_state="starting" without a lease.
_RUNTIME_FENCED_FIELDS = frozenset(
    {
        "auth_state",
        "last_seen_at",
        "node_id",
        "secret_key_version",
        "state_sequence",
        "tailnet_name",
    }
)
_CHANGE_FIELDS = frozenset(NetworkConnectionChanges.__annotations__)


def _requires_live_lease(changes: NetworkConnectionChanges) -> bool:
    """Whether a mutation writes a runtime observation instead of control state."""
    if _RUNTIME_FENCED_FIELDS.intersection(changes):
        return True
    if changes.get("state_payload") is not None or changes.get("login_payload") is not None:
        return True
    if changes.get("runtime_state") not in (None, "starting"):
        return True
    if changes.get("peers"):
        return True
    return changes.get("last_error_code") is not None


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    scope: NetworkScope,
    name: str,
) -> NetworkConnection:
    """Create one paused connection inside the caller's active organization."""
    if scope == "user" and owner_user_id is None:
        raise ValueError("A personal network connection needs an owner")
    connection = NetworkConnection(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        scope=scope,
        visibility="private" if scope == "user" else "org",
        name=name,
    )
    db.add(connection)
    await db.flush()
    await db.refresh(connection)
    return connection


async def get_by_id(
    db: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    for_update: bool = False,
    fresh: bool = False,
) -> NetworkConnection | None:
    """Fetch a row only inside the organization that owns it."""
    stmt = select(NetworkConnection).where(
        NetworkConnection.organization_id == organization_id,
        NetworkConnection.id == connection_id,
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    else:
        stmt = stmt.execution_options(populate_existing=fresh)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    see_all: bool,
    owner_scope: bool,
    shared_scope: bool,
    team_scope: bool,
    visible_ids: Sequence[UUID],
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[NetworkConnection], int]:
    """List only this person's private rows and organization rows they may see.

    Personal connections are owner-only even for roles whose organization scope
    reaches every resource. Organization rows use the same owner, visibility and
    resource-grant inputs as the shared-resource listings.
    """
    if user_id is None:
        return [], 0
    if skip < 0 or not 1 <= limit <= 100:
        raise ValueError("Network connection pagination is out of range")

    filters = [NetworkConnection.organization_id == organization_id]
    personal = and_(
        NetworkConnection.scope == "user",
        NetworkConnection.owner_user_id == user_id,
    )
    if see_all:
        organization_rows = NetworkConnection.scope == "org"
    else:
        visible_to_role = []
        if owner_scope:
            visible_to_role.append(NetworkConnection.owner_user_id == user_id)
        if shared_scope:
            visible_to_role.append(NetworkConnection.visibility == "org")
        if team_scope:
            visible_to_role.append(NetworkConnection.visibility == "team")
        if visible_ids:
            visible_to_role.append(NetworkConnection.id.in_(visible_ids))
        organization_rows = (
            and_(NetworkConnection.scope == "org", or_(*visible_to_role))
            if visible_to_role
            else false()
        )
    filters.append(or_(personal, organization_rows))

    total = await db.scalar(select(func.count(NetworkConnection.id)).where(*filters))
    rows = await db.execute(
        select(NetworkConnection)
        .where(*filters)
        .order_by(NetworkConnection.created_at.asc(), NetworkConnection.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows.scalars().all()), total or 0


async def update(
    db: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    changes: NetworkConnectionChanges,
    lease_id: UUID | None = None,
    expected_policy_generation: int | None = None,
) -> NetworkConnection | None:
    """Update a whitelisted row projection, fencing observations from node jobs.

    Runtime observations must match the live lease and policy generation. The
    expiry comparison uses PostgreSQL's clock, so a worker cannot save after
    losing its lease because of clock skew on an API or worker host.
    """
    unknown_fields = set(changes) - _CHANGE_FIELDS
    if unknown_fields:
        raise ValueError(f"Unsupported network connection fields: {sorted(unknown_fields)}")

    has_lease_fence = lease_id is not None or expected_policy_generation is not None
    if has_lease_fence and (lease_id is None or expected_policy_generation is None):
        raise ValueError("A network runtime fence needs both lease id and policy generation")
    if _requires_live_lease(changes) and not has_lease_fence:
        return None

    if not changes:
        if not has_lease_fence:
            return await get_by_id(
                db,
                organization_id=organization_id,
                connection_id=connection_id,
                fresh=True,
            )
        result = await db.execute(
            select(NetworkConnection).where(
                NetworkConnection.organization_id == organization_id,
                NetworkConnection.id == connection_id,
                NetworkConnection.lease_id == lease_id,
                NetworkConnection.policy_generation == expected_policy_generation,
                NetworkConnection.lease_expires_at > func.clock_timestamp(),
            )
        )
        return result.scalar_one_or_none()

    filters = [
        NetworkConnection.organization_id == organization_id,
        NetworkConnection.id == connection_id,
    ]
    if has_lease_fence:
        filters.extend(
            [
                NetworkConnection.lease_id == lease_id,
                NetworkConnection.policy_generation == expected_policy_generation,
                NetworkConnection.lease_expires_at > func.clock_timestamp(),
            ]
        )
    result = await db.execute(
        sql_update(NetworkConnection)
        .where(*filters)
        .values(**changes)
        .returning(NetworkConnection.id)
    )
    updated_id = result.scalar_one_or_none()
    if updated_id is None:
        return None
    await db.flush()
    return await get_by_id(
        db,
        organization_id=organization_id,
        connection_id=updated_id,
        fresh=True,
    )


async def claim_lease(
    db: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    lease_id: UUID,
    expected_policy_generation: int,
    desired_state: NetworkLeaseState,
    lease_seconds: int = MAX_LEASE_SECONDS,
) -> NetworkConnection | None:
    """Claim an idle/expired runtime lease if the job's authority is still current."""
    if not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
        raise ValueError("Network connection lease must be 1 to 15 seconds")
    result = await db.execute(
        sql_update(NetworkConnection)
        .where(
            NetworkConnection.organization_id == organization_id,
            NetworkConnection.id == connection_id,
            NetworkConnection.policy_generation == expected_policy_generation,
            NetworkConnection.desired_state == desired_state,
            or_(
                NetworkConnection.lease_id == lease_id,
                NetworkConnection.lease_expires_at.is_(None),
                NetworkConnection.lease_expires_at <= func.clock_timestamp(),
            ),
        )
        .values(
            lease_id=lease_id,
            lease_expires_at=func.clock_timestamp()
            + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds),
        )
        .returning(NetworkConnection.id)
    )
    claimed_id = result.scalar_one_or_none()
    if claimed_id is None:
        return None
    await db.flush()
    return await get_by_id(
        db,
        organization_id=organization_id,
        connection_id=claimed_id,
        fresh=True,
    )


async def renew_lease(
    db: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    lease_id: UUID,
    expected_policy_generation: int,
    desired_state: NetworkLeaseState,
    lease_seconds: int = MAX_LEASE_SECONDS,
) -> bool:
    """Extend an unexpired lease only while its generation and desired state match."""
    if not 1 <= lease_seconds <= MAX_LEASE_SECONDS:
        raise ValueError("Network connection lease must be 1 to 15 seconds")
    result = await db.execute(
        sql_update(NetworkConnection)
        .where(
            NetworkConnection.organization_id == organization_id,
            NetworkConnection.id == connection_id,
            NetworkConnection.lease_id == lease_id,
            NetworkConnection.lease_expires_at > func.clock_timestamp(),
            NetworkConnection.policy_generation == expected_policy_generation,
            NetworkConnection.desired_state == desired_state,
        )
        .values(
            lease_expires_at=func.clock_timestamp()
            + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds)
        )
        .returning(NetworkConnection.id)
    )
    renewed_id = result.scalar_one_or_none()
    await db.flush()
    return renewed_id is not None


async def release_lease(
    db: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    lease_id: UUID,
    expected_policy_generation: int | None = None,
) -> bool:
    """Release this holder without stopping a newer active generation's runtime."""
    runtime_state = (
        "stopped"
        if expected_policy_generation is None
        else case(
            (
                NetworkConnection.policy_generation == expected_policy_generation,
                "stopped",
            ),
            (
                NetworkConnection.desired_state.in_(("paused", "revoked")),
                "stopped",
            ),
            else_=NetworkConnection.runtime_state,
        )
    )
    result = await db.execute(
        sql_update(NetworkConnection)
        .where(
            NetworkConnection.organization_id == organization_id,
            NetworkConnection.id == connection_id,
            NetworkConnection.lease_id == lease_id,
        )
        .values(
            lease_id=None,
            lease_expires_at=None,
            runtime_state=runtime_state,
        )
        .returning(NetworkConnection.id)
    )
    released_id = result.scalar_one_or_none()
    await db.flush()
    return released_id is not None


async def lock_quota(db: AsyncSession, *, organization_id: UUID) -> bool:
    """Serialize quota checks for connection creates inside one organization."""
    result = await db.execute(
        select(Organization.id).where(Organization.id == organization_id).with_for_update()
    )
    return result.scalar_one_or_none() is not None


async def count_for_owner(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
) -> int:
    """Count retained connections against this member's organization quota."""
    if owner_user_id is None:
        return 0
    total = await db.scalar(
        select(func.count(NetworkConnection.id)).where(
            NetworkConnection.organization_id == organization_id,
            NetworkConnection.owner_user_id == owner_user_id,
            NetworkConnection.desired_state != "revoked",
        )
    )
    return total or 0


async def count_pending_enrollments(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None = None,
) -> int:
    """Count live enrollment windows for an organization or initiating user."""
    filters = [
        NetworkConnection.organization_id == organization_id,
        NetworkConnection.desired_state == "active",
        NetworkConnection.enrollment_expires_at > func.clock_timestamp(),
    ]
    if user_id is not None:
        filters.append(NetworkConnection.enrollment_user_id == user_id)
    total = await db.scalar(select(func.count(NetworkConnection.id)).where(*filters))
    return total or 0


async def lock_parent(db: AsyncSession, *, organization_id: UUID) -> bool:
    """Take a non-blocking key-share lock on the tenant parent row."""
    result = await db.execute(
        select(Organization.id)
        .where(Organization.id == organization_id)
        .with_for_update(read=True, key_share=True, nowait=True)
    )
    return result.scalar_one_or_none() is not None


async def has_personal_for_member(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> bool:
    """Cheap, lock-free check for any personal row of one member in one organization."""
    result = await db.execute(
        select(NetworkConnection.id)
        .where(
            NetworkConnection.organization_id == organization_id,
            NetworkConnection.scope == "user",
            NetworkConnection.owner_user_id == user_id,
        )
        .limit(1)
    )
    return result.first() is not None


async def list_personal_for_member(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    for_update: bool = False,
) -> list[NetworkConnection]:
    """List one member's personal rows inside a single organization."""
    stmt = (
        select(NetworkConnection)
        .where(
            NetworkConnection.organization_id == organization_id,
            NetworkConnection.scope == "user",
            NetworkConnection.owner_user_id == user_id,
        )
        .order_by(NetworkConnection.id.asc())
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_personal_for_user(
    db: AsyncSession,
    *,
    user_id: UUID,
    for_update: bool = True,
) -> list[NetworkConnection]:
    """Lock one account's personal rows across organizations before erasure."""
    stmt = (
        select(NetworkConnection)
        .where(
            NetworkConnection.scope == "user",
            NetworkConnection.owner_user_id == user_id,
        )
        .order_by(NetworkConnection.organization_id.asc(), NetworkConnection.id.asc())
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_for_organization(
    db: AsyncSession,
    *,
    organization_id: UUID,
    for_update: bool = True,
) -> list[NetworkConnection]:
    """Lock the tenant's personal and organization rows before organization purge."""
    stmt = (
        select(NetworkConnection)
        .where(NetworkConnection.organization_id == organization_id)
        .order_by(NetworkConnection.id.asc())
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_recovery_candidates(
    db: AsyncSession,
    *,
    now: datetime,
    limit: int = 100,
) -> list[tuple[UUID, UUID]]:
    """Return bounded connection ids for recovery; callers must relock each row.

    Expired active work is left for the lifecycle recovery path to stop and mark
    failed. Cleanup jobs are rediscovered only after their old runtime lease has
    expired, so two brokers never run the same mutable node state.
    """
    if not 1 <= limit <= 100:
        raise ValueError("Network connection recovery batch is out of range")

    active_stale = and_(
        NetworkConnection.desired_state.in_(("active", "paused")),
        NetworkConnection.runtime_state.in_(("starting", "running")),
        or_(
            NetworkConnection.lease_expires_at <= now,
            and_(
                NetworkConnection.lease_id.is_(None),
                or_(
                    NetworkConnection.desired_state == "paused",
                    NetworkConnection.runtime_state == "running",
                    NetworkConnection.enrollment_id.is_(None),
                    NetworkConnection.enrollment_expires_at.is_(None),
                    NetworkConnection.enrollment_expires_at <= now,
                ),
            ),
        ),
    )
    cleanup_ready = and_(
        NetworkConnection.desired_state == "revoked",
        NetworkConnection.cleanup_state == "pending",
        or_(
            NetworkConnection.lease_expires_at.is_(None),
            NetworkConnection.lease_expires_at <= now,
        ),
    )
    result = await db.execute(
        select(NetworkConnection.organization_id, NetworkConnection.id)
        .where(or_(active_stale, cleanup_ready))
        .order_by(
            func.coalesce(
                NetworkConnection.lease_expires_at,
                NetworkConnection.enrollment_expires_at,
                NetworkConnection.created_at,
            ),
            NetworkConnection.organization_id.asc(),
            NetworkConnection.id.asc(),
        )
        .limit(limit)
    )
    return [(organization_id, connection_id) for organization_id, connection_id in result.all()]


async def settle_inactive(
    db: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    expected_policy_generation: int,
    changes: NetworkConnectionSettlement,
) -> NetworkConnection | None:
    """Fail closed after confirming no runtime lease is still live.

    This is the only unleased state transition. It can stop a stale process,
    clear enrollment material and redact identity fields, but it cannot install
    node state, peer identities or active authority.
    """
    allowed_fields = frozenset(NetworkConnectionSettlement.__annotations__)
    unknown_fields = set(changes) - allowed_fields
    if unknown_fields:
        raise ValueError(f"Unsupported inactive settlement fields: {sorted(unknown_fields)}")
    if changes.get("desired_state") not in (None, "paused", "revoked"):
        raise ValueError("Inactive settlement cannot activate a connection")
    if changes.get("auth_state") not in (None, "not_connected", "expired", "error"):
        raise ValueError("Inactive settlement cannot authenticate a connection")
    if changes.get("cleanup_state") not in (None, "manual", "complete"):
        raise ValueError("Inactive settlement cannot start cleanup work")
    for field in ("state_payload", "tailnet_name", "node_id", "last_seen_at"):
        if field in changes and changes[field] is not None:
            raise ValueError(f"Inactive settlement may only clear {field}")

    result = await db.execute(
        sql_update(NetworkConnection)
        .where(
            NetworkConnection.organization_id == organization_id,
            NetworkConnection.id == connection_id,
            NetworkConnection.policy_generation == expected_policy_generation,
            or_(
                NetworkConnection.lease_expires_at.is_(None),
                NetworkConnection.lease_expires_at <= func.clock_timestamp(),
            ),
        )
        .values(
            **changes,
            runtime_state="stopped",
            login_payload=None,
            enrollment_id=None,
            enrollment_user_id=None,
            enrollment_session_id=None,
            enrollment_expires_at=None,
            peers=[],
            lease_id=None,
            lease_expires_at=None,
            policy_generation=NetworkConnection.policy_generation + 1,
        )
        .returning(NetworkConnection.id)
    )
    settled_id = result.scalar_one_or_none()
    if settled_id is None:
        return None
    await db.flush()
    return await get_by_id(
        db,
        organization_id=organization_id,
        connection_id=settled_id,
        fresh=True,
    )


async def delete_inactive_personal(db: AsyncSession, *, user_id: UUID) -> int:
    """Delete only revoked, scrubbed personal rows with no live worker lease."""
    result = await db.execute(
        sql_delete(NetworkConnection)
        .where(
            NetworkConnection.scope == "user",
            NetworkConnection.owner_user_id == user_id,
            NetworkConnection.desired_state == "revoked",
            NetworkConnection.state_payload.is_(None),
            NetworkConnection.login_payload.is_(None),
            or_(
                NetworkConnection.lease_expires_at.is_(None),
                NetworkConnection.lease_expires_at <= func.clock_timestamp(),
            ),
        )
        .returning(NetworkConnection.id)
        .execution_options(synchronize_session="fetch")
    )
    deleted_ids = result.scalars().all()
    await db.flush()
    return len(deleted_ids)
