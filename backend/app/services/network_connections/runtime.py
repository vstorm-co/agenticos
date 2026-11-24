"""Fenced lifecycle jobs for a single persistent Tailscale identity."""

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.vault import seal, unseal
from app.db.models.network_connection import NetworkConnection
from app.db.session import get_worker_db_context
from app.repositories import network_connection_repo
from app.services.network_connections.authority import authorize_node
from app.services.network_connections.broker import BrokerFailure, TailscaleBroker
from app.services.network_connections.lifecycle import failure_code, settle_ended
from app.services.network_connections.protocol import (
    LEASE_SECONDS,
    NodeState,
    StateFrame,
    StatusFrame,
)
from app.services.network_connections.secrets import connection_scope, write_key_version
from app.worker.jobs import RunNetworkConnection


class NodeSession:
    """A lease holder writes only while its admitted request remains current."""

    def __init__(self, job: RunNetworkConnection, lease_id: UUID) -> None:
        self.job = job
        self.lease_id = lease_id

    @property
    def desired_state(self) -> Literal["active", "revoked"]:
        return "revoked" if self.job.mode == "logout" else "active"

    async def _row(self, db: AsyncSession) -> NetworkConnection:
        row = await network_connection_repo.get_by_id(
            db,
            organization_id=self.job.organization_id,
            connection_id=self.job.connection_id,
            for_update=True,
        )
        if row is None or row.lease_id != self.lease_id:
            raise BrokerFailure("lease_lost")
        await authorize_node(db, self.job, row)
        return row

    async def _save(
        self, db: AsyncSession, changes: network_connection_repo.NetworkConnectionChanges
    ) -> None:
        updated = await network_connection_repo.update(
            db,
            organization_id=self.job.organization_id,
            connection_id=self.job.connection_id,
            changes=changes,
            lease_id=self.lease_id,
            expected_policy_generation=self.job.policy_generation,
        )
        if updated is None:
            raise BrokerFailure("lease_lost")

    async def heartbeat(self) -> None:
        async with get_worker_db_context() as db:
            await self._row(db)
            renewed = await network_connection_repo.renew_lease(
                db,
                organization_id=self.job.organization_id,
                connection_id=self.job.connection_id,
                lease_id=self.lease_id,
                expected_policy_generation=self.job.policy_generation,
                desired_state=self.desired_state,
                lease_seconds=LEASE_SECONDS,
            )
            if not renewed:
                raise BrokerFailure("lease_lost")

    async def persist(self, frame: StateFrame) -> None:
        async with get_worker_db_context() as db:
            row = await self._row(db)
            plaintext = json.dumps(
                {"state": {key: value.get_secret_value() for key, value in frame.state.items()}},
                separators=(",", ":"),
            )
            sealed = seal(
                plaintext, scope=connection_scope(row), key_version=write_key_version(row)
            )
            await self._save(
                db,
                {
                    "state_payload": sealed.ciphertext,
                    "secret_key_version": sealed.key_version,
                    "state_sequence": row.state_sequence + 1,
                },
            )
        # The context commits before the caller acknowledges the child's write.

    async def observe(self, frame: StatusFrame) -> None:
        async with get_worker_db_context() as db:
            row = await self._row(db)
            if self.job.mode == "logout":
                return
            if (
                row.node_id is not None
                and frame.node_id is not None
                and row.node_id != frame.node_id
            ) or (
                row.tailnet_name is not None
                and frame.tailnet_name is not None
                and row.tailnet_name != frame.tailnet_name
            ):
                raise BrokerFailure("identity_changed")
            changes: network_connection_repo.NetworkConnectionChanges = {
                "runtime_state": "running",
                "last_seen_at": datetime.now(UTC),
                "last_error_code": None,
            }
            if frame.key_expired:
                changes.update(auth_state="expired", login_payload=None)
            elif frame.backend_state == "Running" and frame.node_id and frame.tailnet_name:
                changes.update(
                    auth_state="authenticated",
                    node_id=frame.node_id,
                    tailnet_name=frame.tailnet_name,
                    login_payload=None,
                    peers=[peer.model_dump(mode="json") for peer in frame.peers],
                )
            elif frame.backend_state == "NeedsMachineAuth":
                changes.update(auth_state="approval_required", login_payload=None)
            elif frame.backend_state == "NeedsLogin":
                changes["auth_state"] = "sign_in_required"
                if self.job.mode == "enroll" and frame.auth_url is not None:
                    sealed = seal(
                        frame.auth_url.get_secret_value(),
                        scope=connection_scope(row),
                        key_version=write_key_version(row),
                    )
                    changes.update(
                        login_payload=sealed.ciphertext, secret_key_version=sealed.key_version
                    )
                else:
                    changes["login_payload"] = None
            await self._save(db, changes)

    async def finish(self, reason: str) -> None:
        async with get_worker_db_context() as db:
            row = await network_connection_repo.get_by_id(
                db,
                organization_id=self.job.organization_id,
                connection_id=self.job.connection_id,
                for_update=True,
            )
            if row is None or row.lease_id != self.lease_id:
                return
            if row.policy_generation == self.job.policy_generation:
                changes: network_connection_repo.NetworkConnectionChanges = {"login_payload": None}
                if self.job.mode == "logout":
                    # Device login grants no admin API scope. Logout and local
                    # erasure do not prove provider-side device removal.
                    changes.update(
                        state_payload=None,
                        cleanup_state="manual",
                        auth_state="not_connected",
                        peers=[],
                        last_error_code=None if reason == "logged_out" else "runtime_failed",
                        enrollment_expires_at=None,
                    )
                elif reason == "ready":
                    changes.update(enrollment_expires_at=None, last_error_code=None)
                else:
                    changes["last_error_code"] = failure_code(reason)
                await network_connection_repo.update(
                    db,
                    organization_id=row.organization_id,
                    connection_id=row.id,
                    changes=changes,
                    lease_id=self.lease_id,
                    expected_policy_generation=self.job.policy_generation,
                )
            await network_connection_repo.release_lease(
                db,
                organization_id=row.organization_id,
                connection_id=row.id,
                lease_id=self.lease_id,
                expected_policy_generation=self.job.policy_generation,
            )


async def _claim_state(job: RunNetworkConnection, lease: NodeSession) -> NodeState | None:
    """Recheck admission and commit the writer lease before revealing stored state."""
    if not settings.TAILSCALE_ENABLED:
        raise BrokerFailure("runtime_unavailable")
    async with get_worker_db_context() as db:
        row = await network_connection_repo.get_by_id(
            db,
            organization_id=job.organization_id,
            connection_id=job.connection_id,
            for_update=True,
        )
        if row is None or row.policy_generation != job.policy_generation:
            return None
        await authorize_node(db, job, row)
        claimed = await network_connection_repo.claim_lease(
            db,
            organization_id=job.organization_id,
            connection_id=job.connection_id,
            lease_id=lease.lease_id,
            expected_policy_generation=job.policy_generation,
            desired_state=lease.desired_state,
            lease_seconds=LEASE_SECONDS,
        )
        if claimed is None:
            raise BrokerFailure("lease_lost")
        try:
            return (
                NodeState.model_validate_json(
                    unseal(
                        row.state_payload,
                        scope=connection_scope(row),
                        key_version=row.secret_key_version,
                    )
                )
                if row.state_payload
                else NodeState()
            )
        except ValidationError:
            raise BrokerFailure("invalid_runtime_response") from None


async def run_node(job: RunNetworkConnection) -> None:
    lease = NodeSession(job, uuid4())
    reason = "runtime_failed"
    try:
        state = await _claim_state(job, lease)
        if state is None:
            return
        await lease.heartbeat()
        reason = await TailscaleBroker(settings.TAILSCALE_BROKER_PATH).run(
            connection_id=job.connection_id,
            mode=job.mode,
            state=state,
            callbacks=lease,
        )
    except BrokerFailure as exc:
        reason = exc.code
        raise
    finally:
        await lease.finish(reason)
        await settle_ended(job, reason)
