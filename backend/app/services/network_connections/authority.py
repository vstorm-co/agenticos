"""Re-establish the initiating person and session before each node heartbeat."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Perm
from app.db.models.network_connection import NetworkConnection
from app.repositories import session_repo
from app.services.access import NETWORK_CONNECTION, member_context, resolve_access
from app.services.network_connections.broker import BrokerFailure
from app.worker.jobs import RunNetworkConnection


async def authorize_node(
    db: AsyncSession, job: RunNetworkConnection, row: NetworkConnection
) -> None:
    desired = "revoked" if job.mode == "logout" else "active"
    if row.policy_generation != job.policy_generation or row.desired_state != desired:
        raise BrokerFailure("authority_revoked")
    if job.mode == "logout":
        return
    if (
        row.enrollment_id != job.enrollment_id
        or row.enrollment_expires_at is None
        or row.enrollment_expires_at <= datetime.now(UTC)
        or row.enrollment_user_id is None
        or row.enrollment_session_id is None
    ):
        raise BrokerFailure("enrollment_expired")
    session = await session_repo.get_by_id(db, row.enrollment_session_id)
    if (
        session is None
        or session.user_id != row.enrollment_user_id
        or not session.is_active
        or session.impersonator_user_id is not None
        or session.expires_at <= datetime.now(UTC)
    ):
        raise BrokerFailure("authority_revoked")
    ctx = await member_context(
        db, organization_id=row.organization_id, user_id=row.enrollment_user_id
    )
    if (
        ctx is None
        or (row.scope == "user" and row.owner_user_id != ctx.user_id)
        or not await resolve_access(
            db, ctx, row, Perm.NETWORKS_MANAGE, resource_type=NETWORK_CONNECTION
        )
    ):
        raise BrokerFailure("authority_revoked")
