"""Connection administration; initiating people never lend their network identity."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm, Scope
from app.core.vault import unseal
from app.db.models.network_connection import NetworkConnection
from app.repositories import member_repo, network_connection_repo, session_repo
from app.schemas.network_connection import (
    NetworkConnectionCreate,
    NetworkConnectionList,
    NetworkConnectionRead,
    NetworkEnrollmentRead,
    NetworkPeerList,
    NetworkPeerRead,
)
from app.services.access import NETWORK_CONNECTION, resolve_access, visible_resource_ids
from app.services.background_jobs import enqueue
from app.services.network_connections.admission import guard_member
from app.services.network_connections.broker import TailscaleBroker
from app.services.network_connections.secrets import connection_scope
from app.worker.jobs import RUN_NETWORK_CONNECTION, RunNetworkConnection

ENROLLMENT_LIFETIME = timedelta(minutes=10)
MAX_CONNECTIONS_PER_OWNER = 10
MAX_PENDING_PER_PERSON = 1
MAX_PENDING_PER_ORGANIZATION = 4


class NetworkConnectionService:
    """Administer one org's connections without allocating compute on reads."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def available() -> bool:
        return (
            settings.TAILSCALE_ENABLED
            and TailscaleBroker(settings.TAILSCALE_BROKER_PATH).available()
        )

    async def _interactive(self, ctx: AuthContext, session_id: UUID | None) -> UUID:
        if (
            ctx.user_id is None
            or ctx.personal_user_id != ctx.user_id
            or current_impersonator() is not None
            or session_id is None
        ):
            raise AuthorizationError(message="Network connections need your own signed-in session")
        session = await session_repo.get_by_id(self.db, session_id)
        if (
            session is None
            or session.user_id != ctx.user_id
            or session.impersonator_user_id is not None
            or not session.is_active
            or session.expires_at <= datetime.now(UTC)
        ):
            raise AuthorizationError(message="Sign in again to manage network connections")
        return session_id

    async def _can(self, ctx: AuthContext, row: NetworkConnection, permission: Perm) -> bool:
        if row.organization_id != ctx.organization_id:
            return False
        if row.scope == "user" and row.owner_user_id != ctx.user_id:
            return False
        return await resolve_access(self.db, ctx, row, permission, resource_type=NETWORK_CONNECTION)

    async def _write_guard(self, ctx: AuthContext, *, admission: bool = False) -> None:
        await guard_member(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            admission=admission,
        )
        # Re-read after the removal/erasure fence. AuthContext may have been
        # resolved just before a membership removal committed.
        if (
            await member_repo.get_active(
                self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
            )
            is None
        ):
            raise AuthorizationError(message="Your membership has changed; sign in again")

    async def _admission_capacity(self, ctx: AuthContext) -> None:
        pending = await network_connection_repo.count_pending_enrollments(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        if pending >= MAX_PENDING_PER_PERSON:
            raise BadRequestError(message="Finish or pause your current network connection first")
        total = await network_connection_repo.count_pending_enrollments(
            self.db, organization_id=ctx.organization_id
        )
        if total >= MAX_PENDING_PER_ORGANIZATION:
            raise BadRequestError(
                message="This organization has too many network connections in progress"
            )

    async def _get(
        self,
        ctx: AuthContext,
        connection_id: UUID,
        *,
        permission: Perm = Perm.NETWORKS_VIEW,
        for_update: bool = False,
    ) -> NetworkConnection:
        row = await network_connection_repo.get_by_id(
            self.db,
            organization_id=ctx.organization_id,
            connection_id=connection_id,
            for_update=for_update,
        )
        if row is None or not await self._can(ctx, row, permission):
            raise NotFoundError(
                message="Network connection not found", details={"connection_id": connection_id}
            )
        return row

    async def _read(self, ctx: AuthContext, row: NetworkConnection) -> NetworkConnectionRead:
        result = NetworkConnectionRead.model_validate(row)
        return result.model_copy(
            update={"can_manage": await self._can(ctx, row, Perm.NETWORKS_MANAGE)}
        )

    async def list(
        self,
        ctx: AuthContext,
        *,
        session_id: UUID | None,
        skip: int = 0,
        limit: int = 50,
    ) -> NetworkConnectionList:
        await self._interactive(ctx, session_id)
        role_scope = ctx.scope_for(Perm.NETWORKS_VIEW)
        visible = await visible_resource_ids(
            self.db, ctx, resource_type=NETWORK_CONNECTION, perm=Perm.NETWORKS_VIEW
        )
        rows, total = await network_connection_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=role_scope >= Scope.ALL,
            owner_scope=role_scope >= Scope.OWN,
            shared_scope=role_scope >= Scope.SHARED,
            team_scope=role_scope >= Scope.TEAM,
            visible_ids=visible or [],
            skip=skip,
            limit=limit,
        )
        return NetworkConnectionList(
            items=[await self._read(ctx, row) for row in rows],
            total=total,
            available=self.available(),
        )

    async def get(
        self, ctx: AuthContext, *, connection_id: UUID, session_id: UUID | None
    ) -> NetworkConnectionRead:
        await self._interactive(ctx, session_id)
        return await self._read(ctx, await self._get(ctx, connection_id))

    async def create(
        self, ctx: AuthContext, data: NetworkConnectionCreate, *, session_id: UUID | None
    ) -> NetworkConnectionRead:
        """Save a connection record. Only connect starts a node or enrolls a device."""
        await self._interactive(ctx, session_id)
        self._runtime_required()
        await self._write_guard(ctx, admission=True)
        scope = ctx.scope_for(Perm.NETWORKS_MANAGE)
        if scope < Scope.OWN or (data.scope == "org" and scope < Scope.SHARED):
            raise AuthorizationError(message="You cannot create this kind of network connection")
        count = await network_connection_repo.count_for_owner(
            self.db, organization_id=ctx.organization_id, owner_user_id=ctx.subject_id
        )
        if count >= MAX_CONNECTIONS_PER_OWNER:
            raise BadRequestError(message="This member has reached the network connection limit")
        row = await network_connection_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            owner_user_id=ctx.subject_id,
            scope=data.scope,
            name=data.name,
        )
        await self._audit(ctx, row, "created")
        return await self._read(ctx, row)

    async def connect(
        self, ctx: AuthContext, *, connection_id: UUID, session_id: UUID | None
    ) -> NetworkConnectionRead:
        session = await self._interactive(ctx, session_id)
        await self._write_guard(ctx, admission=True)
        row = await self._get(ctx, connection_id, permission=Perm.NETWORKS_MANAGE, for_update=True)
        self._runtime_required()
        if row.desired_state == "revoked":
            raise BadRequestError(message="Add a new connection after revoking this one")
        now = datetime.now(UTC)
        if (
            row.enrollment_expires_at is not None
            and row.enrollment_expires_at > now
            and row.runtime_state in ("starting", "running")
        ):
            if row.enrollment_user_id == ctx.user_id and row.enrollment_session_id == session:
                return await self._read(ctx, row)
            raise BadRequestError(
                message="Another sign-in is in progress; pause it before connecting again"
            )
        await self._admission_capacity(ctx)
        row = await self._change(
            row,
            {
                "policy_generation": row.policy_generation + 1,
                "desired_state": "active",
                "runtime_state": "starting",
                "cleanup_state": "none",
                "enrollment_id": uuid4(),
                "enrollment_user_id": ctx.subject_id,
                "enrollment_session_id": session,
                "enrollment_expires_at": now + ENROLLMENT_LIFETIME,
                "login_payload": None,
                "last_error_code": None,
            },
        )
        await self._queue(row, "enroll")
        await self._audit(ctx, row, "connect_requested")
        return await self._read(ctx, row)

    async def enrollment(
        self, ctx: AuthContext, *, connection_id: UUID, session_id: UUID | None
    ) -> NetworkEnrollmentRead:
        session = await self._interactive(ctx, session_id)
        await self._write_guard(ctx)
        row = await self._get(ctx, connection_id, permission=Perm.NETWORKS_MANAGE)
        if row.enrollment_user_id != ctx.user_id or row.enrollment_session_id != session:
            raise NotFoundError(message="Enrollment not found")
        valid = (
            row.desired_state == "active"
            and row.enrollment_expires_at is not None
            and row.enrollment_expires_at > datetime.now(UTC)
        )
        login_url = (
            unseal(
                row.login_payload, scope=connection_scope(row), key_version=row.secret_key_version
            )
            if valid and row.login_payload is not None and row.auth_state == "sign_in_required"
            else None
        )
        return NetworkEnrollmentRead(
            attempt_id=row.enrollment_id if valid else None,
            expires_at=row.enrollment_expires_at if valid else None,
            login_url=login_url,
        )

    async def peers(
        self, ctx: AuthContext, *, connection_id: UUID, session_id: UUID | None
    ) -> NetworkPeerList:
        """Return the last observed peers; listing never scans or starts a node."""
        await self._interactive(ctx, session_id)
        row = await self._get(ctx, connection_id)
        return NetworkPeerList(
            items=[NetworkPeerRead.model_validate(peer) for peer in row.peers]
            if row.desired_state != "revoked"
            else [],
            observed_at=row.last_seen_at,
        )

    async def refresh(
        self, ctx: AuthContext, *, connection_id: UUID, session_id: UUID | None
    ) -> NetworkConnectionRead:
        session = await self._interactive(ctx, session_id)
        await self._write_guard(ctx, admission=True)
        row = await self._get(ctx, connection_id, permission=Perm.NETWORKS_MANAGE, for_update=True)
        self._runtime_required()
        if row.desired_state != "active" or row.auth_state != "authenticated":
            raise BadRequestError(message="Connect this network before refreshing its devices")
        if row.runtime_state in ("starting", "running"):
            return await self._read(ctx, row)
        await self._admission_capacity(ctx)
        row = await self._change(
            row,
            {
                "policy_generation": row.policy_generation + 1,
                "runtime_state": "starting",
                "enrollment_id": uuid4(),
                "enrollment_user_id": ctx.subject_id,
                "enrollment_session_id": session,
                "enrollment_expires_at": datetime.now(UTC) + timedelta(seconds=45),
                "login_payload": None,
                "last_error_code": None,
            },
        )
        await self._queue(row, "status")
        await self._audit(ctx, row, "refresh_requested")
        return await self._read(ctx, row)

    async def pause(
        self, ctx: AuthContext, *, connection_id: UUID, session_id: UUID | None
    ) -> NetworkConnectionRead:
        await self._interactive(ctx, session_id)
        await self._write_guard(ctx)
        row = await self._get(ctx, connection_id, permission=Perm.NETWORKS_MANAGE, for_update=True)
        if row.desired_state == "revoked":
            raise BadRequestError(message="This network connection has been revoked")
        if row.desired_state != "paused":
            row = await self._change(
                row,
                {
                    "desired_state": "paused",
                    "policy_generation": row.policy_generation + 1,
                    "login_payload": None,
                    "enrollment_expires_at": None,
                },
            )
            await self._audit(ctx, row, "paused")
        if row.runtime_state != "stopped" or row.lease_id is not None:
            stopped = await network_connection_repo.settle_inactive(
                self.db,
                organization_id=row.organization_id,
                connection_id=row.id,
                expected_policy_generation=row.policy_generation,
                changes={},
            )
            if stopped is not None:
                row = stopped
        return await self._read(ctx, row)

    async def revoke(
        self, ctx: AuthContext, *, connection_id: UUID, session_id: UUID | None
    ) -> NetworkConnectionRead:
        await self._interactive(ctx, session_id)
        await self._write_guard(ctx)
        row = await self._get(ctx, connection_id, permission=Perm.NETWORKS_MANAGE, for_update=True)
        if row.desired_state != "revoked":
            row = await self._revoke(row)
            await self._audit(ctx, row, "revoked")
        return await self._read(ctx, row)

    async def _revoke(self, row: NetworkConnection) -> NetworkConnection:
        """Commit the deny before cleanup; the lease stays fenced until its owner stops."""
        row = await self._change(
            row,
            {
                "desired_state": "revoked",
                "policy_generation": row.policy_generation + 1,
                "login_payload": None,
                "enrollment_expires_at": None,
                "cleanup_state": (
                    "pending"
                    if row.state_payload
                    else "manual"
                    if row.node_id or row.tailnet_name
                    else "complete"
                ),
                "peers": [],
            },
        )
        if row.state_payload:
            await self._queue(row, "logout", run_after=datetime.now(UTC) + timedelta(seconds=16))
        else:
            stopped = await network_connection_repo.settle_inactive(
                self.db,
                organization_id=row.organization_id,
                connection_id=row.id,
                expected_policy_generation=row.policy_generation,
                changes={"auth_state": "not_connected"},
            )
            if stopped is not None:
                row = stopped
        return row

    async def revoke_member(self, *, organization_id: UUID, user_id: UUID) -> int:
        """Membership removal permanently withdraws each personal connector's authority."""
        # Routine jobs hold the per-user lock; take the NOWAIT guard only when
        # there is something to revoke, so a member with no rows is always removable.
        if not await network_connection_repo.has_personal_for_member(
            self.db, organization_id=organization_id, user_id=user_id
        ):
            return 0
        await guard_member(self.db, organization_id=organization_id, user_id=user_id)
        rows = await network_connection_repo.list_personal_for_member(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            for_update=True,
        )
        revoked = 0
        for row in rows:
            if row.desired_state != "revoked":
                await self._revoke(row)
                revoked += 1
        return revoked

    async def prepare_user_deletion(self, user_id: UUID) -> None:
        """Do not orphan a live identity, or retain private metadata after erasure."""
        rows = await network_connection_repo.list_personal_for_user(self.db, user_id=user_id)
        for row in rows:
            await self._prepare_deletion(row)
        deleted = await network_connection_repo.delete_inactive_personal(self.db, user_id=user_id)
        if deleted != len(rows):
            raise ConflictError(
                message="Network cleanup is still finishing; try deleting the account again"
            )

    async def prepare_organization_deletion(self, organization_id: UUID) -> None:
        """Called with the organization locked, before its identities can cascade away."""
        rows = await network_connection_repo.list_for_organization(
            self.db,
            organization_id=organization_id,
        )
        for row in rows:
            await self._prepare_deletion(row)

    async def _prepare_deletion(self, row: NetworkConnection) -> None:
        if row.state_payload or row.login_payload:
            raise ConflictError(
                message="Revoke network connections and wait for cleanup before deleting"
            )
        if row.desired_state != "revoked":
            row = await self._revoke(row)
        settled = await network_connection_repo.settle_inactive(
            self.db,
            organization_id=row.organization_id,
            connection_id=row.id,
            expected_policy_generation=row.policy_generation,
            changes={"auth_state": "not_connected"},
        )
        if settled is None:
            raise ConflictError(message="Network cleanup is still finishing; try deleting again")

    async def _change(
        self, row: NetworkConnection, changes: network_connection_repo.NetworkConnectionChanges
    ) -> NetworkConnection:
        updated = await network_connection_repo.update(
            self.db,
            organization_id=row.organization_id,
            connection_id=row.id,
            changes=changes,
        )
        if updated is None:
            raise NotFoundError(message="Network connection not found")
        return updated

    async def _queue(
        self,
        row: NetworkConnection,
        mode: Literal["enroll", "status", "logout"],
        *,
        run_after: datetime | None = None,
    ) -> None:
        await enqueue(
            self.db,
            RUN_NETWORK_CONNECTION,
            RunNetworkConnection(
                organization_id=row.organization_id,
                connection_id=row.id,
                enrollment_id=row.enrollment_id,
                policy_generation=row.policy_generation,
                mode=mode,
            ),
            organization_id=row.organization_id,
            concurrency_key=f"network-connection:{row.id}",
            dedupe_key=f"network-connection:{row.id}:{row.policy_generation}:{row.enrollment_id}:{mode}",
            dedupe_active=True,
            run_after=run_after,
        )

    async def _audit(self, ctx: AuthContext, row: NetworkConnection, action: str) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=f"network_connection.{action}",
            target_type="network_connection",
            target_id=str(row.id),
            details={"scope": row.scope, "policy_generation": row.policy_generation},
        )

    @staticmethod
    def _runtime_required() -> None:
        if not NetworkConnectionService.available():
            raise ConfigurationError(message="Tailscale is not enabled on this deployment")

    @staticmethod
    async def run_node(job: RunNetworkConnection) -> None:
        from app.services.network_connections.runtime import run_node

        await run_node(job)

    @staticmethod
    async def settle_ended(job: RunNetworkConnection, why: str) -> None:
        from app.services.network_connections.lifecycle import settle_ended

        await settle_ended(job, why)

    @staticmethod
    async def recover() -> int:
        from app.services.network_connections.lifecycle import recover

        return await recover()
