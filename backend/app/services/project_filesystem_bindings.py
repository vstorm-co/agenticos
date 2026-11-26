"""Issue sandbox-only transport credentials and short-lived Project directories.

The binding identifies a sandbox, not a Project. Only an admitted run lease
opens a Project directory, and the gateway reauthorizes it on every operation.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, AuthenticationError, AuthorizationError
from app.core.vault import VaultScope, seal, unseal
from app.db.models.agent_run import RunStatus
from app.db.models.project_filesystem import ProjectFilesystemBinding, ProjectFilesystemLease
from app.repositories import agent_run as run_repo
from app.repositories import project_filesystem_bindings as binding_repo
from app.repositories import sandbox_connection as connection_repo
from app.schemas.project_filesystem_authority import (
    ProjectFilesystemAuthority,
    ProjectFilesystemBindingRead,
    ProjectFilesystemCredential,
    ProjectFilesystemLeaseRead,
)

LEASE_SECONDS = 90
"""An orphaned run's mount expires even before the normal run reaper finds it."""


class ProjectFilesystemBindingService:
    """Own a workspace credential's envelope and the leases handed to its supervisor."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def credential(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        session_name: str,
        workspace_id: UUID | None,
        conversation_id: UUID | None,
    ) -> ProjectFilesystemCredential:
        """Reuse an immutable binding credential; a revoked binding is never revived."""
        binding = await binding_repo.binding_for_session(
            self.db,
            organization_id=organization_id,
            connection_id=connection_id,
            session_name=session_name,
        )
        if binding is None:
            plaintext = secrets.token_urlsafe(32)
            envelope = seal(plaintext, scope=VaultScope.organization(organization_id))
            await binding_repo.insert_binding(
                self.db,
                row=ProjectFilesystemBinding(
                    id=uuid4(),
                    organization_id=organization_id,
                    connection_id=connection_id,
                    workspace_id=workspace_id,
                    conversation_id=conversation_id,
                    session_name=session_name,
                    token_digest=_digest(plaintext),
                    ciphertext=envelope.ciphertext,
                    secret_key_version=envelope.key_version,
                ),
            )
            # Concurrent openers use the winning row's token, never their losing candidate.
            binding = await binding_repo.binding_for_session(
                self.db,
                organization_id=organization_id,
                connection_id=connection_id,
                session_name=session_name,
            )
            if binding is None:
                raise RuntimeError("Filesystem binding insert did not produce a session identity")
        if (
            binding.revoked_at is not None
            or binding.workspace_id != workspace_id
            or binding.conversation_id != conversation_id
        ):
            raise AuthorizationError(
                message="The sandbox filesystem identity changed. Recreate its filesystem connection.",
                details={},
            )
        token = unseal(
            binding.ciphertext,
            scope=VaultScope.organization(organization_id),
            key_version=binding.secret_key_version,
        )
        return ProjectFilesystemCredential(binding_id=binding.id, token=SecretStr(token))

    async def authenticate(
        self, binding_id: UUID, token: SecretStr | None
    ) -> ProjectFilesystemBinding:
        """Authenticate only the fixed sandbox binding, with no Project disclosure."""
        binding = await binding_repo.binding_by_id(self.db, binding_id)
        if (
            binding is None
            or token is None
            or binding.revoked_at is not None
            or not secrets.compare_digest(binding.token_digest, _digest(token.get_secret_value()))
        ):
            raise AuthenticationError(
                message="The sandbox filesystem credential is invalid", details={}
            )
        connection = await connection_repo.get(
            self.db, binding.connection_id, organization_id=binding.organization_id
        )
        if connection is None or not connection.is_active:
            raise AuthenticationError(
                message="The sandbox filesystem connection is unavailable", details={}
            )
        return binding

    async def proof(
        self, binding_id: UUID, token: SecretStr | None
    ) -> ProjectFilesystemBindingRead:
        binding = await self.authenticate(binding_id, token)
        return ProjectFilesystemBindingRead(
            binding_id=binding.id,
            session_name=binding.session_name,
            tenant=str(binding.organization_id),
        )

    async def issue_lease(
        self,
        *,
        binding_id: UUID,
        project_id: UUID,
        generation: UUID | None,
        run_id: UUID,
        authority: ProjectFilesystemAuthority,
    ) -> ProjectFilesystemLeaseRead:
        """Retain server-validated admission; no public endpoint creates leases.

        The caller first validates the Project with `ProjectRunAuthority`. This
        check also binds that admission to the sandbox's exact conversation.
        """
        binding = await binding_repo.binding_by_id(self.db, binding_id, for_update=True)
        actor = authority.actor
        run = await run_repo.get_run(self.db, run_id, organization_id=actor.organization_id)
        if (
            binding is None
            or binding.revoked_at is not None
            or binding.organization_id != actor.organization_id
            or binding.conversation_id != authority.conversation_id
            or actor.user_id is None
            or actor.subject_is_publisher_fallback
            or not authority.audience.private
            or "projects:read" not in authority.granted_scopes
            or run is None
            or run.status != RunStatus.RUNNING.value
            or run.user_id != actor.user_id
            or run.conversation_id != binding.conversation_id
        ):
            raise AuthorizationError(message="This run cannot mount this Project", details={})
        now = datetime.now(UTC)
        active = await binding_repo.live_leases(self.db, binding=binding, now=now)
        for previous in active:
            if (
                previous.run_id == run_id
                and previous.project_id == project_id
                and previous.workspace_generation == generation
            ):
                return ProjectFilesystemLeaseRead(
                    id=previous.id,
                    project_id=project_id,
                    workspace_generation=generation,
                    path=f"/project/{previous.id}",
                    expires_at=previous.expires_at,
                )
            raise AlreadyExistsError(
                message="This sandbox is already using another Project filesystem lease",
                details={},
            )
        lease = await binding_repo.create_lease(
            self.db,
            lease=ProjectFilesystemLease(
                id=uuid4(),
                organization_id=binding.organization_id,
                binding_id=binding.id,
                project_id=project_id,
                workspace_generation=generation,
                run_id=run_id,
                actor_id=actor.user_id,
                authority_json=authority.model_dump_json(),
                expires_at=now + timedelta(seconds=LEASE_SECONDS),
            ),
        )
        return ProjectFilesystemLeaseRead(
            id=lease.id,
            project_id=project_id,
            workspace_generation=generation,
            path=f"/project/{lease.id}",
            expires_at=lease.expires_at,
        )

    async def renew(self, *, lease_id: UUID, run_id: UUID, organization_id: UUID) -> None:
        now = datetime.now(UTC)
        renewed = await binding_repo.renew_lease(
            self.db,
            lease_id=lease_id,
            run_id=run_id,
            organization_id=organization_id,
            now=now,
            expires_at=now + timedelta(seconds=LEASE_SECONDS),
        )
        if not renewed:
            raise AuthorizationError(message="The Project filesystem lease expired", details={})

    async def revoke(self, *, lease_id: UUID, run_id: UUID, organization_id: UUID) -> None:
        await binding_repo.revoke_lease(
            self.db,
            lease_id=lease_id,
            run_id=run_id,
            organization_id=organization_id,
            now=datetime.now(UTC),
        )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
