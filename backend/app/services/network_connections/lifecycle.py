"""Recover stopped jobs without restarting enrollment or discarding cleanup work."""

from datetime import UTC, datetime

from app.core.exceptions import ConcurrentChangeError, NotFoundError
from app.db.models.network_connection import NetworkConnection
from app.db.session import get_worker_db_context
from app.repositories import network_connection_repo
from app.schemas.network_connection import NETWORK_ERROR_CODES, NetworkErrorCode
from app.services.network_connections.admission import hold_parent
from app.worker.jobs import RunNetworkConnection


def failure_code(reason: str) -> NetworkErrorCode:
    """Never store a queue exception or provider message as a public error."""
    if reason == "timeout":
        return "enrollment_expired"
    for code in NETWORK_ERROR_CODES:
        if code == reason:
            return code
    return "runtime_failed"


def _current_attempt(row: NetworkConnection, job: RunNetworkConnection) -> bool:
    return row.policy_generation == job.policy_generation and (
        job.mode == "logout" or row.enrollment_id == job.enrollment_id
    )


async def settle_ended(job: RunNetworkConnection, why: str) -> None:
    """A terminal job cannot leave a login URL, perpetual spinner, or live authority."""
    async with get_worker_db_context() as db:
        row = await network_connection_repo.get_by_id(
            db,
            organization_id=job.organization_id,
            connection_id=job.connection_id,
            for_update=True,
        )
        if row is None or not _current_attempt(row, job):
            return
        changes: network_connection_repo.NetworkConnectionSettlement
        if job.mode == "logout":
            if row.desired_state != "revoked" or row.cleanup_state != "pending":
                return
            changes = {
                "state_payload": None,
                "cleanup_state": "manual",
                "auth_state": "not_connected",
                "last_error_code": failure_code(why),
            }
        else:
            if row.desired_state != "active" or (
                row.runtime_state == "stopped"
                and row.enrollment_expires_at is None
                and row.login_payload is None
            ):
                return
            changes = {
                "desired_state": "paused",
                "auth_state": "error",
                "last_error_code": failure_code(why),
            }
        # A recently lost worker can still hold a live lease. The sweep retries
        # after its child has stopped; it never clears keys under a live writer.
        await network_connection_repo.settle_inactive(
            db,
            organization_id=row.organization_id,
            connection_id=row.id,
            expected_policy_generation=job.policy_generation,
            changes=changes,
        )


async def recover() -> int:
    """Stop expired work and retry only revocation cleanup, never a new login."""
    from app.services.network_connections.facade import NetworkConnectionService

    now = datetime.now(UTC)
    async with get_worker_db_context() as db:
        candidates = await network_connection_repo.list_recovery_candidates(db, now=now)
    recovered = 0
    for organization_id, connection_id in candidates:
        async with get_worker_db_context() as db:
            try:
                await hold_parent(db, organization_id)
            except ConcurrentChangeError, NotFoundError:
                continue
            row = await network_connection_repo.get_by_id(
                db,
                organization_id=organization_id,
                connection_id=connection_id,
                for_update=True,
            )
            if row is None or (row.lease_expires_at is not None and row.lease_expires_at > now):
                continue
            changes: network_connection_repo.NetworkConnectionSettlement
            if row.desired_state == "revoked" and row.cleanup_state == "pending":
                if row.state_payload and NetworkConnectionService.available():
                    await NetworkConnectionService(db)._queue(row, "logout")
                    continue
                changes = {
                    "state_payload": None,
                    "auth_state": "not_connected",
                    "cleanup_state": "manual" if row.state_payload or row.node_id else "complete",
                    "last_error_code": "runtime_unavailable" if row.state_payload else None,
                }
            elif row.runtime_state in ("starting", "running") and row.desired_state != "revoked":
                if (
                    row.desired_state == "active"
                    and row.runtime_state == "starting"
                    and row.lease_id is None
                    and row.enrollment_expires_at is not None
                    and row.enrollment_expires_at > now
                ):
                    continue  # Still queued inside the initiating session's deadline.
                expired = row.enrollment_expires_at is not None and row.enrollment_expires_at <= now
                changes = {
                    "desired_state": "paused",
                    "last_error_code": "enrollment_expired" if expired else "runtime_disconnected",
                }
                if row.desired_state == "active":
                    changes["auth_state"] = "error"
            else:
                continue
            settled = await network_connection_repo.settle_inactive(
                db,
                organization_id=organization_id,
                connection_id=connection_id,
                expected_policy_generation=row.policy_generation,
                changes=changes,
            )
            if settled is not None:
                recovered += 1
    return recovered
