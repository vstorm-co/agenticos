"""Conversation-owned browser/desktop admission, storage and durable lifecycle."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.core.vault import VaultScope, seal, unseal
from app.db.models.agent_run import RunSurface
from app.db.models.conversation_environment import ConversationEnvironment
from app.repositories import agent_run as run_repo
from app.repositories import conversation_environment as environments
from app.schemas.conversation_environment import (
    ConversationEnvironmentControl,
    ConversationEnvironmentKind,
    ConversationEnvironmentList,
    ConversationEnvironmentRead,
    ConversationEnvironmentRefusal,
    ConversationEnvironmentRefusalCode,
    ConversationEnvironmentStart,
    ConversationEnvironmentState,
)
from app.schemas.project_context import ProjectExecutionTarget
from app.services.background_jobs import enqueue
from app.services.conversation_environment_policy import (
    EnvironmentNotReady,
    EnvironmentSettings,
    authority,
    current_actor,
    settings_for,
)
from app.services.conversation_environment_resources import (
    ENVIRONMENT_RESOURCE,
    EnvironmentResource,
)
from app.worker.jobs import (
    CLEANUP_CONVERSATION_ENVIRONMENT,
    MAINTAIN_CONVERSATION_ENVIRONMENT,
    PROVISION_CONVERSATION_ENVIRONMENT,
    ConversationEnvironmentPayload,
)

_CONTROL = TypeAdapter(ConversationEnvironmentControl)
_STATE = TypeAdapter(ConversationEnvironmentState)
_REASON = TypeAdapter(ConversationEnvironmentRefusalCode)


def idle_until(seconds: int = 900) -> datetime:
    return datetime.now(UTC) + timedelta(
        seconds=min(seconds, settings.CONVERSATION_ENVIRONMENT_MAX_IDLE_SECONDS)
    )


def personal_owner(ctx: AuthContext) -> UUID:
    if ctx.user_id is None or ctx.api_key_id is not None or ctx.subject_is_publisher_fallback:
        raise AuthorizationError(message="A manual environment belongs to a signed-in person")
    return ctx.user_id


class ConversationEnvironmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def read(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        agent_id: UUID,
        kind: ConversationEnvironmentKind,
        execution_target: ProjectExecutionTarget = "agent",
    ) -> ConversationEnvironmentRead:
        owner = personal_owner(ctx)
        row = await environments.latest(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            conversation_id=conversation_id,
            agent_id=agent_id,
            kind=kind,
        )
        resolved: EnvironmentSettings | None = None
        try:
            admitted = await authority(
                self.db,
                ctx,
                conversation_id=conversation_id,
                agent_id=agent_id,
                execution_target=execution_target,
            )
            resolved = await settings_for(self.db, admitted, kind)
        except EnvironmentNotReady as refused:
            return await self._read(
                row, agent_id, kind, execution_target, refusal=refused.refusal, resolved=resolved
            )
        if row is not None and (
            row.fingerprint != resolved.fingerprint or row.execution_target != execution_target
        ):
            return await self._read(
                row,
                agent_id,
                kind,
                execution_target,
                resolved=resolved,
                refusal=ConversationEnvironmentRefusal(
                    code="environment_changed",
                    message="The selected environment changed. Open it again to use the current settings.",
                ),
            )
        return await self._read(row, agent_id, kind, execution_target, resolved=resolved)

    async def list(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        agent_id: UUID,
        execution_target: ProjectExecutionTarget = "agent",
    ) -> ConversationEnvironmentList:
        return ConversationEnvironmentList(
            items=[
                await self.read(ctx, conversation_id, agent_id, kind, execution_target)
                for kind in ("browser", "desktop")
            ]
        )

    async def ensure(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        kind: ConversationEnvironmentKind,
        request: ConversationEnvironmentStart,
        *,
        producer_run_id: UUID | None = None,
    ) -> ConversationEnvironmentRead:
        owner = personal_owner(ctx)
        target = request.project_execution_target or "agent"
        try:
            admitted = await authority(
                self.db,
                ctx,
                conversation_id=conversation_id,
                agent_id=request.agent_id,
                execution_target=target,
            )
            resolved = await settings_for(self.db, admitted, kind)
        except EnvironmentNotReady as refused:
            return await self._read(None, request.agent_id, kind, target, refusal=refused.refusal)
        if producer_run_id is not None:
            run = await run_repo.get_run(
                self.db, producer_run_id, organization_id=ctx.organization_id
            )
            if (
                run is None
                or run.user_id != owner
                or run.agent_id != request.agent_id
                or run.conversation_id != conversation_id
                or run.status != "running"
                or run.surface != RunSurface.WEB.value
                or run.agent_version_id != admitted.version_id
            ):
                raise AuthorizationError(
                    message="The environment producer is not this person's active run"
                )
        await environments.lock_owner(self.db, ctx.organization_id, owner)
        row = await environments.latest(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            conversation_id=conversation_id,
            agent_id=request.agent_id,
            kind=kind,
            for_update=True,
        )
        now = datetime.now(UTC)
        if row is not None and row.state in ("starting", "ready"):
            if (
                row.expires_at > now
                and row.fingerprint == resolved.fingerprint
                and row.execution_target == target
            ):
                row.expires_at = idle_until(resolved.config.session_idle_seconds)
                await self.db.flush()
                return await self._read(row, request.agent_id, kind, target, resolved=resolved)
            await self._refuse_active_agent(row)
            await self.expire(row)
        if (
            await environments.active_count(self.db, ctx.organization_id, owner, now)
            >= settings.CONVERSATION_ENVIRONMENTS_PER_USER
        ):
            return await self._read(
                None,
                request.agent_id,
                kind,
                target,
                refusal=ConversationEnvironmentRefusal(
                    code="capacity_reached",
                    message="End another environment before opening a new one.",
                ),
            )
        row = await environments.add(
            self.db,
            ConversationEnvironment(
                id=uuid4(),
                organization_id=ctx.organization_id,
                vault_organization_id=ctx.organization_id,
                user_id=owner,
                conversation_id=conversation_id,
                agent_id=request.agent_id,
                agent_version_id=admitted.version_id,
                source_run_id=producer_run_id,
                kind=kind,
                execution_target=target,
                state="starting",
                fingerprint=resolved.fingerprint,
                revision=1,
                session_lifetime=resolved.config.session_lifetime,
                idle_seconds=min(
                    resolved.config.session_idle_seconds,
                    settings.CONVERSATION_ENVIRONMENT_MAX_IDLE_SECONDS,
                ),
                provisioning_attempt=0,
                expires_at=idle_until(resolved.config.session_idle_seconds),
            ),
        )
        if producer_run_id is None:
            await enqueue(
                self.db,
                PROVISION_CONVERSATION_ENVIRONMENT,
                self.payload(row),
                organization_id=ctx.organization_id,
                dedupe_key=f"environment-provision:{row.id}",
                dedupe_active=True,
                concurrency_key=f"environment:{row.id}",
            )
        await enqueue(
            self.db,
            CLEANUP_CONVERSATION_ENVIRONMENT,
            self.payload(row),
            organization_id=ctx.organization_id,
            run_after=row.expires_at,
            dedupe_key=f"environment-cleanup:{row.id}:{row.revision}",
            dedupe_active=True,
            concurrency_key=f"environment:{row.id}",
        )
        return await self._read(row, request.agent_id, kind, target, resolved=resolved)

    async def end(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        agent_id: UUID,
        kind: ConversationEnvironmentKind,
        execution_target: ProjectExecutionTarget = "agent",
    ) -> None:
        owner = personal_owner(ctx)
        await current_actor(self.db, ctx.organization_id, owner)
        await environments.lock_owner(self.db, ctx.organization_id, owner)
        row = await environments.latest(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            conversation_id=conversation_id,
            agent_id=agent_id,
            kind=kind,
            for_update=True,
        )
        if row is None or row.execution_target != execution_target or row.state == "expired":
            return
        await self._refuse_active_agent(row)
        await self.expire(row)

    async def _refuse_active_agent(self, row: ConversationEnvironment) -> None:
        held = (
            None
            if row.resource_key is None
            else await environments.driver(self.db, row.resource_key)
        )
        if held is not None and held.control == "agent" and held.lease_until > datetime.now(UTC):
            raise ConflictError(
                message="Wait for the agent to release this environment before ending it"
            )

    async def expire(self, row: ConversationEnvironment) -> None:
        """Retire admission now; queued cleanup runs after this transaction commits."""
        if row.state != "expired":
            row.state = "expired"
            row.expires_at = datetime.now(UTC)
            row.revision += 1
            await self.db.flush()
        if row.resource_ciphertext is not None:
            await enqueue(
                self.db,
                CLEANUP_CONVERSATION_ENVIRONMENT,
                self.payload(row),
                organization_id=row.organization_id,
                dedupe_key=f"environment-cleanup:{row.id}:{row.revision}",
                dedupe_active=True,
                concurrency_key=f"environment:{row.id}",
            )

    @staticmethod
    def payload(row: ConversationEnvironment) -> ConversationEnvironmentPayload:
        return ConversationEnvironmentPayload(
            environment_id=row.id, organization_id=row.vault_organization_id, revision=row.revision
        )

    async def _read(
        self,
        row: ConversationEnvironment | None,
        agent_id: UUID,
        kind: ConversationEnvironmentKind,
        target: ProjectExecutionTarget,
        *,
        refusal: ConversationEnvironmentRefusal | None = None,
        resolved: EnvironmentSettings | None = None,
    ) -> ConversationEnvironmentRead:
        now = datetime.now(UTC)
        if refusal is not None and refusal.code == "environment_changed":
            row = None
        state: ConversationEnvironmentState = (
            "not_started" if row is None else _STATE.validate_python(row.state)
        )
        if row is not None and row.expires_at <= now:
            state = "expired"
            refusal = refusal or ConversationEnvironmentRefusal(
                code="environment_expired",
                message="This environment expired. Open it again to continue in a new session.",
            )
        elif refusal is not None and refusal.code != "environment_changed":
            state = "failed"
        elif row is not None and row.refusal_code is not None:
            refusal = ConversationEnvironmentRefusal(
                code=_REASON.validate_python(row.refusal_code),
                message=(
                    "Manual desktop preparation requires a conversation-, user-, agent- or project-scoped executor."
                    if row.refusal_code == "backend_not_supported"
                    else "The environment is unavailable. Check its connection and open it again."
                ),
            )
        held = (
            None
            if row is None or row.resource_key is None
            else await environments.driver(self.db, row.resource_key)
        )
        control: ConversationEnvironmentControl = (
            "none"
            if state not in ("starting", "ready") or held is None or held.lease_until <= now
            else _CONTROL.validate_python(held.control)
        )
        return ConversationEnvironmentRead(
            id=None if row is None else row.id,
            kind=kind,
            execution_target=target,
            agent_id=agent_id,
            state=state,
            control=control,
            session_lifetime="run" if resolved is None else resolved.config.session_lifetime,
            idle_seconds=min(
                900 if resolved is None else resolved.config.session_idle_seconds,
                settings.CONVERSATION_ENVIRONMENT_MAX_IDLE_SECONDS,
            ),
            can_control=state == "ready" and control != "agent" and refusal is None,
            expires_at=None if row is None else row.expires_at,
            refusal=refusal,
        )

    async def claim(
        self,
        payload: ConversationEnvironmentPayload,
        attempt: int,
    ) -> EnvironmentSettings | None:
        row = await environments.for_worker(self.db, payload.environment_id)
        if not self._current(row, payload) or row is None or row.state != "starting":
            return None
        if (
            row.user_id is None
            or row.conversation_id is None
            or row.agent_id is None
            or row.expires_at <= datetime.now(UTC)
        ):
            await self.expire(row)
            return None
        actor = await current_actor(self.db, payload.organization_id, row.user_id)
        target = TypeAdapter(ProjectExecutionTarget).validate_python(row.execution_target)
        admitted = await authority(
            self.db,
            actor,
            conversation_id=row.conversation_id,
            agent_id=row.agent_id,
            execution_target=target,
        )
        # Resolve current project authority before locking the environment,
        # matching admission and driver renewal's project → environment order.
        row = await environments.for_worker(self.db, payload.environment_id, for_update=True)
        if (
            not self._current(row, payload)
            or row is None
            or row.state != "starting"
            or row.expires_at <= datetime.now(UTC)
        ):
            return None
        kind = TypeAdapter(ConversationEnvironmentKind).validate_python(row.kind)
        resolved = await settings_for(self.db, admitted, kind)
        if resolved.fingerprint != row.fingerprint:
            raise EnvironmentNotReady(
                "environment_changed", "The environment changed before it could start."
            )
        if row.source_run_id is not None:
            run = await run_repo.get_run(
                self.db, row.source_run_id, organization_id=payload.organization_id
            )
            if (
                run is None
                or run.status != "running"
                or run.surface != RunSurface.WEB.value
                or run.agent_version_id != admitted.version_id
                or run.user_id != row.user_id
                or run.conversation_id != row.conversation_id
                or run.agent_id != row.agent_id
            ):
                raise AuthorizationError(message="The environment producer is no longer active")
            resolved = replace(
                resolved, authority=replace(resolved.authority, producer_run_id=row.source_run_id)
            )
        row.provisioning_attempt = attempt
        await self.db.flush()
        return resolved

    @staticmethod
    def _current(
        row: ConversationEnvironment | None, payload: ConversationEnvironmentPayload
    ) -> bool:
        return (
            row is not None
            and row.organization_id == payload.organization_id
            and row.revision == payload.revision
        )

    async def store_resource(
        self,
        payload: ConversationEnvironmentPayload,
        attempt: int,
        resource: EnvironmentResource,
        resource_key: str,
    ) -> bool:
        row = await environments.for_worker(self.db, payload.environment_id, for_update=True)
        if (
            row is None
            or row.vault_organization_id != payload.organization_id
            or row.provisioning_attempt != attempt
        ):
            return False
        if (
            resource.environment_id != row.id
            or resource.organization_id != payload.organization_id
            or resource.kind != row.kind
        ):
            raise ValueError("The provisioned resource does not belong to this environment")
        accepted = (
            self._current(row, payload)
            and row.state == "starting"
            and row.expires_at > datetime.now(UTC)
        )
        if not accepted and (row.state != "expired" or row.resource_ciphertext is not None):
            return False
        sealed = seal(
            resource.model_dump_json(), scope=VaultScope.organization(payload.organization_id)
        )
        row.resource_ciphertext, row.resource_key_version = sealed.ciphertext, sealed.key_version
        row.resource_key = resource_key
        await self.db.flush()
        if not accepted:
            await enqueue(
                self.db,
                CLEANUP_CONVERSATION_ENVIRONMENT,
                self.payload(row),
                organization_id=row.organization_id,
                dedupe_key=f"environment-cleanup:{row.id}:{row.revision}",
                dedupe_active=True,
                concurrency_key=f"environment:{row.id}",
            )
        return accepted

    async def replace_resource(
        self, row: ConversationEnvironment, resource: EnvironmentResource
    ) -> None:
        """Replace only the locked owner's validated private resource journal."""
        if (
            resource.environment_id != row.id
            or resource.organization_id != row.organization_id
            or resource.kind != row.kind
        ):
            raise ConflictError(message="The resource does not belong to this environment")
        sealed = seal(
            resource.model_dump_json(), scope=VaultScope.organization(resource.organization_id)
        )
        row.resource_ciphertext, row.resource_key_version = sealed.ciphertext, sealed.key_version
        await self.db.flush()

    @staticmethod
    def resource(row: ConversationEnvironment, organization_id: UUID) -> EnvironmentResource:
        if row.resource_ciphertext is None or row.resource_key_version is None:
            raise EnvironmentNotReady(
                "environment_expired", "This environment has no live resource."
            )
        resource = ENVIRONMENT_RESOURCE.validate_json(
            unseal(
                row.resource_ciphertext,
                scope=VaultScope.organization(organization_id),
                key_version=row.resource_key_version,
            )
        )
        if (
            resource.environment_id != row.id
            or resource.organization_id != organization_id
            or resource.kind != row.kind
        ):
            raise EnvironmentNotReady(
                "environment_expired", "This environment's protected identity does not match."
            )
        return resource

    async def ready(self, payload: ConversationEnvironmentPayload, attempt: int) -> bool:
        row = await environments.for_worker(self.db, payload.environment_id, for_update=True)
        if (
            not self._current(row, payload)
            or row is None
            or row.state != "starting"
            or row.provisioning_attempt != attempt
            or row.resource_ciphertext is None
            or row.expires_at <= datetime.now(UTC)
        ):
            return False
        row.state = "ready"
        row.refusal_code = None
        await self.db.flush()
        return True

    async def failed(
        self,
        payload: ConversationEnvironmentPayload,
        *,
        reason: ConversationEnvironmentRefusalCode = "provisioning_failed",
    ) -> None:
        row = await environments.for_worker(self.db, payload.environment_id, for_update=True)
        if not self._current(row, payload) or row is None or row.state != "starting":
            return
        row.state = "failed"
        row.refusal_code = reason
        await self.db.flush()
        if row.resource_ciphertext is not None:
            await enqueue(
                self.db,
                CLEANUP_CONVERSATION_ENVIRONMENT,
                payload,
                organization_id=payload.organization_id,
                dedupe_key=f"environment-cleanup:{row.id}:{row.revision}",
                dedupe_active=True,
                concurrency_key=f"environment:{row.id}",
            )

    async def live(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        environment_id: UUID,
        target: ProjectExecutionTarget,
        *,
        lock: bool = False,
        touch: bool = False,
    ) -> tuple[ConversationEnvironment, EnvironmentSettings, EnvironmentResource]:
        owner = personal_owner(ctx)
        row = await environments.owned(
            self.db,
            environment_id,
            organization_id=ctx.organization_id,
            user_id=owner,
            conversation_id=conversation_id,
        )
        if row is None or row.agent_id is None:
            raise NotFoundError(message="This environment is unavailable")
        admitted = await authority(
            self.db,
            ctx,
            conversation_id=conversation_id,
            agent_id=row.agent_id,
            execution_target=target,
        )
        resolved = await settings_for(
            self.db, admitted, TypeAdapter(ConversationEnvironmentKind).validate_python(row.kind)
        )
        if lock:
            row = await environments.owned(
                self.db,
                environment_id,
                organization_id=ctx.organization_id,
                user_id=owner,
                conversation_id=conversation_id,
                for_update=True,
            )
        if row is None or row.state != "ready" or row.expires_at <= datetime.now(UTC):
            raise EnvironmentNotReady("environment_expired", "This environment is no longer live.")
        if row.execution_target != target or row.fingerprint != resolved.fingerprint:
            raise EnvironmentNotReady(
                "environment_changed", "The selected environment changed. Open it again."
            )
        if row.source_run_id is not None and row.session_lifetime == "run":
            resolved = replace(
                resolved, authority=replace(resolved.authority, producer_run_id=row.source_run_id)
            )
        resource = self.resource(row, ctx.organization_id)
        if touch:
            row.expires_at = idle_until(row.idle_seconds)
            await self.db.flush()
        return row, resolved, resource

    async def cleanup_resource(
        self, payload: ConversationEnvironmentPayload
    ) -> EnvironmentResource | None:
        row = await environments.for_worker(self.db, payload.environment_id, for_update=True)
        if (
            row is None
            or row.vault_organization_id != payload.organization_id
            or row.revision != payload.revision
        ):
            return None
        held = (
            None
            if row.resource_key is None
            else await environments.driver(self.db, row.resource_key)
        )
        if (
            row.state != "expired"
            and held is not None
            and held.control == "agent"
            and held.lease_until > datetime.now(UTC)
            and all((row.organization_id, row.user_id, row.conversation_id, row.agent_id))
        ):
            row.expires_at = idle_until(row.idle_seconds)
            await self.db.flush()
            return None
        if (
            row.state in ("starting", "ready")
            and row.expires_at > datetime.now(UTC)
            and all((row.organization_id, row.user_id, row.conversation_id, row.agent_id))
        ):
            return None
        if row.state != "expired":
            row.state = "expired"
            await self.db.flush()
        if row.resource_ciphertext is None:
            return None
        return self.resource(row, payload.organization_id)

    async def cleaned(self, payload: ConversationEnvironmentPayload) -> None:
        row = await environments.for_worker(self.db, payload.environment_id, for_update=True)
        if (
            row is None
            or row.vault_organization_id != payload.organization_id
            or row.revision != payload.revision
        ):
            return
        row.resource_ciphertext = None
        row.resource_key_version = None
        row.resource_key = None
        row.state = "expired"
        if not all((row.organization_id, row.user_id, row.conversation_id, row.agent_id)):
            await self.db.delete(row)
        await self.db.flush()

    async def sweep(self) -> None:
        now = datetime.now(UTC)
        for row in await environments.sweep_candidates(self.db, now):
            if row.resource_key is not None:
                held = await environments.driver(self.db, row.resource_key)
                if (
                    held is not None
                    and held.control == "agent"
                    and held.lease_until > now
                    and all((row.organization_id, row.user_id, row.conversation_id, row.agent_id))
                ):
                    row.expires_at = idle_until(row.idle_seconds)
                    continue
            await self.expire(row)
        for row in await environments.active_for_maintenance(self.db, now):
            await enqueue(
                self.db,
                MAINTAIN_CONVERSATION_ENVIRONMENT,
                self.payload(row),
                organization_id=row.organization_id,
                dedupe_key=f"environment-maintain:{row.id}",
                dedupe_active=True,
                concurrency_key=f"environment:{row.id}",
            )
            row.last_maintained_at = now
        await self.db.flush()
