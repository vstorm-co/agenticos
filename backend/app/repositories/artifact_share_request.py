"""Share request repository (PostgreSQL async): requests to share a page or confirm a version."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.artifact_share_request import (
    ArtifactShareRequest,
    ShareRequestKind,
    ShareRequestStatus,
    VoidReason,
)


async def get(
    db: AsyncSession, request_id: UUID, *, artifact_id: UUID
) -> ArtifactShareRequest | None:
    result = await db.execute(
        select(ArtifactShareRequest).where(
            ArtifactShareRequest.id == request_id, ArtifactShareRequest.artifact_id == artifact_id
        )
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, **fields: Any) -> ArtifactShareRequest:
    request = ArtifactShareRequest(**fields)
    db.add(request)
    await db.flush()
    await db.refresh(request)
    return request


async def list_for_artifact(
    db: AsyncSession,
    artifact_id: UUID,
    *,
    pending_only: bool = True,
    decided_only: bool = False,
    kinds: Sequence[ShareRequestKind] | None = None,
    only_requester_id: UUID | None = None,
    plain_access_too: bool = False,
    restricted: bool = False,
    skip: int = 0,
    limit: int | None = None,
) -> tuple[list[ArtifactShareRequest], int]:
    """A page's requests, the pending ones first and then newest first, with the total.

    Only the pending ones unless asked for all, or only the decided and void ones with
    `decided_only`. A `restricted` listing keeps those made
    by `only_requester_id` and, with `plain_access_too`, the requests for access to a
    page that reads no data. The decided ones are never pruned, so a long-lived page
    lists them a page at a time.
    """
    where = [ArtifactShareRequest.artifact_id == artifact_id]
    if pending_only:
        where.append(ArtifactShareRequest.status == ShareRequestStatus.PENDING.value)
    if decided_only:
        where.append(ArtifactShareRequest.status != ShareRequestStatus.PENDING.value)
    if kinds is not None:
        where.append(ArtifactShareRequest.kind.in_([kind.value for kind in kinds]))
    if restricted:
        own = ArtifactShareRequest.requester_user_id == only_requester_id
        plain = and_(
            ArtifactShareRequest.kind == ShareRequestKind.ACCESS.value,
            ArtifactShareRequest.query_fingerprint.is_(None),
        )
        where.append(or_(own, plain) if plain_access_too else own)
    query = (
        select(ArtifactShareRequest)
        .where(*where)
        .order_by(
            ArtifactShareRequest.status != ShareRequestStatus.PENDING.value,
            ArtifactShareRequest.created_at.desc(),
            ArtifactShareRequest.id,
        )
        .offset(skip)
    )
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    total = await db.scalar(select(func.count(ArtifactShareRequest.id)).where(*where))
    return list(result.scalars().all()), total or 0


async def pending(
    db: AsyncSession,
    artifact_id: UUID,
    *,
    kind: ShareRequestKind,
    requester_user_id: UUID | None = None,
) -> ArtifactShareRequest | None:
    """The pending request of this kind - the person's own for `audience` and `access`,
    the page's only one for `version`."""
    query = select(ArtifactShareRequest).where(
        ArtifactShareRequest.artifact_id == artifact_id,
        ArtifactShareRequest.kind == kind.value,
        ArtifactShareRequest.status == ShareRequestStatus.PENDING.value,
    )
    if requester_user_id is not None:
        query = query.where(ArtifactShareRequest.requester_user_id == requester_user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def settle(
    db: AsyncSession,
    request: ArtifactShareRequest,
    *,
    status: ShareRequestStatus,
    decided_by_user_id: UUID | None = None,
    void_reason: VoidReason | None = None,
) -> ArtifactShareRequest:
    """End a pending request: decided by a person, or voided for a reason."""
    request.status = status.value
    request.decided_by_user_id = decided_by_user_id
    request.decided_at = datetime.now(UTC)
    request.void_reason = void_reason.value if void_reason is not None else None
    await db.flush()
    await db.refresh(request)
    return request


async def void_pending(
    db: AsyncSession,
    artifact_id: UUID,
    *,
    reason: VoidReason,
    kinds: Sequence[ShareRequestKind] | None = None,
    fingerprint_other_than: str | None = None,
    stale_fingerprint_only: bool = False,
) -> None:
    """Void a page's pending requests.

    With `stale_fingerprint_only`, only those made against page queries other than
    `fingerprint_other_than` - `None` meaning a page with none.
    """
    statement = sql_update(ArtifactShareRequest).where(
        ArtifactShareRequest.artifact_id == artifact_id,
        ArtifactShareRequest.status == ShareRequestStatus.PENDING.value,
    )
    if kinds is not None:
        statement = statement.where(ArtifactShareRequest.kind.in_([kind.value for kind in kinds]))
    if stale_fingerprint_only:
        statement = statement.where(
            ArtifactShareRequest.query_fingerprint.is_distinct_from(fingerprint_other_than)
        )
    await db.execute(
        statement.values(
            status=ShareRequestStatus.VOIDED.value,
            void_reason=reason.value,
            decided_at=datetime.now(UTC),
        ).execution_options(synchronize_session="fetch")
    )
