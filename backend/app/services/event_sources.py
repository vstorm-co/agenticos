"""Reusable event source management and transactional, per-subscriber admission."""

import base64
import json
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal, NoReturn, cast
from uuid import UUID, uuid4

from pydantic import SecretStr, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)
from app.core.field_errors import field_problems
from app.core.permissions import AuthContext, Perm
from app.core.vault import VaultScope, seal, unseal
from app.db.locks import LockScope, hold_subject
from app.db.models.event_source import (
    EventDelivery,
    EventDispatch,
    EventSource,
    EventSourceCredential,
    EventSubscription,
)
from app.repositories import agent as agent_repo
from app.repositories import agent_trigger as trigger_repo
from app.repositories import event_source as repo
from app.repositories import resource_grant_repo
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_exposure as exposure_repo
from app.schemas.event_source import (
    EventSourceCreate,
    EventSourceCreated,
    EventSourceList,
    EventSourceRead,
    EventSourceUpdate,
    JsonObject,
    Provider,
    SourceAuth,
    SourceCredentials,
    SourceUsage,
    SourceUsageList,
)
from app.services import trigger_events
from app.services.access import (
    AGENT,
    EVENT_SOURCE,
    WORKFLOW,
    accessible_ids,
    resolve_access,
    visible_resource_ids,
)
from app.services.background_jobs import enqueue
from app.services.event_source_auth import standard_key, verify_source
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowInlineStorageLimitError,
)
from app.workflows.graph.model import jsonb_value_fits

_BODY = TypeAdapter(JsonObject)


def _non_json_number(value: str) -> NoReturn:
    raise ValueError(f"Invalid JSON number: {value}")


def credential_json(credentials: SourceCredentials) -> str:
    """Plaintext exists only at the vault boundary, never in model dumps or repr."""
    return json.dumps(
        {
            name: value.get_secret_value()
            for name, value in {
                "secret": credentials.secret,
                "username": credentials.username,
                "password": credentials.password,
            }.items()
            if value is not None
        }
    )


def prepare_credentials(
    auth: SourceAuth, credentials: SourceCredentials, *, generate: bool
) -> tuple[SourceCredentials, str | None]:
    reveal = None
    if auth.method == "basic":
        if (
            not credentials.username
            or not credentials.password
            or not credentials.username.get_secret_value()
            or not credentials.password.get_secret_value()
            or ":" in credentials.username.get_secret_value()
        ):
            raise BadRequestError(
                message="Basic Auth needs a username without ':' and a nonempty password"
            )
        return SourceCredentials(username=credentials.username, password=credentials.password), None
    if not credentials.secret or not credentials.secret.get_secret_value():
        if not generate or auth.method == "provider":
            raise BadRequestError(message="Enter the provider's signing secret")
        reveal = (
            "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()
            if auth.method == "standard_webhooks"
            else secrets.token_urlsafe(32)
        )
        credentials = SourceCredentials(secret=SecretStr(reveal))
    assert credentials.secret is not None
    if auth.method == "standard_webhooks":
        standard_key(credentials.secret.get_secret_value())
    return SourceCredentials(secret=credentials.secret), reveal


class EventSourceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def webhook_url(source_id: UUID) -> str:
        return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/webhooks/sources/{source_id}"

    async def get(
        self,
        ctx: AuthContext,
        source_id: UUID,
        *,
        perm: Perm = Perm.EVENT_SOURCES_VIEW,
        lock: bool = False,
    ) -> EventSource:
        source = await repo.get(self.db, source_id, organization_id=ctx.organization_id, lock=lock)
        if source is None or not await resolve_access(
            self.db, ctx, source, perm, resource_type=EVENT_SOURCE
        ):
            raise NotFoundError(message="Event source not found")
        return source

    async def require_use(
        self, ctx: AuthContext, source_id: UUID, *, lock: bool = False
    ) -> EventSource:
        """Check use permission, optionally locking before a foreign-key write or audit."""
        return await self.get(ctx, source_id, perm=Perm.EVENT_SOURCES_USE, lock=lock)

    async def read(self, ctx: AuthContext, source: EventSource) -> EventSourceRead:
        return self._read(
            source,
            can_use=await resolve_access(
                self.db, ctx, source, Perm.EVENT_SOURCES_USE, resource_type=EVENT_SOURCE
            ),
            can_edit=await resolve_access(
                self.db, ctx, source, Perm.EVENT_SOURCES_EDIT, resource_type=EVENT_SOURCE
            ),
        )

    def _read(self, source: EventSource, *, can_use: bool, can_edit: bool) -> EventSourceRead:
        return EventSourceRead(
            id=source.id,
            name=source.name,
            provider=cast(Provider, source.provider),
            auth=SourceAuth.model_validate(source.auth),
            delivery_id_header=source.delivery_id_header,
            visibility=cast(Literal["private", "org"], source.visibility),
            owner_user_id=source.owner_user_id,
            is_active=source.is_active,
            webhook_url=self.webhook_url(source.id),
            can_use=can_use,
            can_edit=can_edit,
        )

    async def list(self, ctx: AuthContext, *, skip: int = 0, limit: int = 50) -> EventSourceList:
        if ctx.user_id is None:
            return EventSourceList(items=[], total=0)
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=EVENT_SOURCE, perm=Perm.EVENT_SOURCES_VIEW
        )
        sources, total = await repo.list_sources(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            scope=ctx.scope_for(Perm.EVENT_SOURCES_VIEW),
            shared_ids=shared,
            skip=skip,
            limit=limit,
        )
        usable = await accessible_ids(
            self.db, ctx, sources, Perm.EVENT_SOURCES_USE, resource_type=EVENT_SOURCE
        )
        editable = await accessible_ids(
            self.db, ctx, sources, Perm.EVENT_SOURCES_EDIT, resource_type=EVENT_SOURCE
        )
        return EventSourceList(
            items=[
                self._read(source, can_use=source.id in usable, can_edit=source.id in editable)
                for source in sources
            ],
            total=total,
        )

    async def create(self, ctx: AuthContext, data: EventSourceCreate) -> EventSourceCreated:
        credentials, reveal = prepare_credentials(data.auth, data.credentials, generate=True)
        sealed = seal(
            credential_json(credentials), scope=VaultScope.organization(ctx.organization_id)
        )
        credential = await repo.save(
            self.db,
            EventSourceCredential(
                organization_id=ctx.organization_id,
                sealed_secret=sealed.ciphertext,
                secret_key_version=sealed.key_version,
            ),
        )
        source = await repo.save(
            self.db,
            EventSource(
                organization_id=ctx.organization_id,
                owner_user_id=ctx.subject_id,
                name=data.name,
                provider=data.provider,
                auth=data.auth.model_dump(mode="json"),
                delivery_id_header=data.delivery_id_header,
                visibility=data.visibility,
                is_active=data.is_active,
                secret_id=credential.id,
            ),
        )
        await self._audit(ctx, source.id, "created")
        return EventSourceCreated(
            **(await self.read(ctx, source)).model_dump(), reveal_secret=reveal
        )

    async def update(
        self, ctx: AuthContext, source_id: UUID, data: EventSourceUpdate
    ) -> EventSourceRead:
        source = await self.get(ctx, source_id, perm=Perm.EVENT_SOURCES_EDIT, lock=True)
        credential = await repo.credential(
            self.db, source.secret_id, organization_id=ctx.organization_id
        )
        if credential is None:
            raise NotFoundError(message="Source credential not found")
        current_credentials = SourceCredentials.model_validate_json(
            unseal(
                credential.sealed_secret,
                scope=VaultScope.organization(ctx.organization_id),
                key_version=credential.secret_key_version,
            )
        )
        try:
            config = EventSourceCreate(
                name=data.name or source.name,
                provider=cast(Provider, source.provider),
                auth=data.auth or SourceAuth.model_validate(source.auth),
                delivery_id_header=data.delivery_id_header
                if "delivery_id_header" in data.model_fields_set
                else source.delivery_id_header,
                credentials=data.credentials or current_credentials,
            )
        except ValidationError as exc:
            fields = field_problems(exc.errors(include_input=False), root="")
            for problem in fields:
                if not problem["field"]:
                    problem["field"] = "auth"
            raise BadRequestError(
                message="The source authentication configuration is invalid",
                details={"fields": fields},
            ) from exc
        credentials, _ = prepare_credentials(config.auth, config.credentials, generate=False)
        source.auth = config.auth.model_dump(mode="json")
        source.delivery_id_header = config.delivery_id_header
        if data.credentials is not None:
            sealed = seal(
                credential_json(credentials), scope=VaultScope.organization(ctx.organization_id)
            )
            credential.sealed_secret = sealed.ciphertext
            credential.secret_key_version = sealed.key_version
            await repo.save(self.db, credential)
        if data.name is not None:
            source.name = data.name
        if data.visibility is not None:
            source.visibility = data.visibility
        if data.is_active is not None:
            source.is_active = data.is_active
        await repo.save(self.db, source)
        await self._audit(ctx, source.id, "updated")
        return await self.read(ctx, source)

    async def replace_credentials(
        self, ctx: AuthContext, source_id: UUID, data: SourceCredentials
    ) -> None:
        source = await self.get(ctx, source_id, perm=Perm.EVENT_SOURCES_EDIT, lock=True)
        credentials, _ = prepare_credentials(
            SourceAuth.model_validate(source.auth), data, generate=False
        )
        credential = await repo.credential(
            self.db, source.secret_id, organization_id=ctx.organization_id
        )
        if credential is None:
            raise NotFoundError(message="Source credential not found")
        sealed = seal(
            credential_json(credentials), scope=VaultScope.organization(ctx.organization_id)
        )
        credential.sealed_secret = sealed.ciphertext
        credential.secret_key_version = sealed.key_version
        await repo.save(self.db, credential)
        await self._audit(ctx, source.id, "credentials_replaced")

    async def usage(self, ctx: AuthContext, source_id: UUID) -> SourceUsageList:
        await self.get(ctx, source_id)
        items = []
        for sub in await repo.subscriptions(
            self.db, source_id, organization_id=ctx.organization_id
        ):
            if sub.trigger_id:
                trigger = await trigger_repo.get_by_id(self.db, sub.trigger_id)
                if trigger and trigger.organization_id == ctx.organization_id:
                    target_agent = await agent_repo.get(
                        self.db, trigger.agent_id, organization_id=ctx.organization_id
                    )
                    visible = target_agent is not None and await resolve_access(
                        self.db, ctx, target_agent, Perm.AGENTS_VIEW, resource_type=AGENT
                    )
                    items.append(
                        SourceUsage(
                            id=sub.id,
                            kind="routine",
                            target_id=trigger.id if visible else None,
                            name=trigger.name if visible else None,
                            is_active=trigger.is_active if visible else None,
                        )
                    )
            else:
                exposure = await exposure_repo.get_by_id(self.db, cast(UUID, sub.exposure_id))
                if exposure and exposure.organization_id == ctx.organization_id:
                    workflow = await workflow_repo.get(
                        self.db, exposure.workflow_id, organization_id=ctx.organization_id
                    )
                    if workflow:
                        visible = await resolve_access(
                            self.db, ctx, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
                        )
                        items.append(
                            SourceUsage(
                                id=sub.id,
                                kind="workflow",
                                target_id=workflow.id if visible else None,
                                name=workflow.name if visible else None,
                                is_active=exposure.is_active if visible else None,
                            )
                        )
        return SourceUsageList(items=items, total=len(items))

    async def delete(self, ctx: AuthContext, source_id: UUID) -> None:
        source = await self.get(ctx, source_id, perm=Perm.EVENT_SOURCES_EDIT, lock=True)
        subscriptions = await repo.subscriptions(
            self.db, source.id, organization_id=ctx.organization_id
        )
        if subscriptions:
            raise BadRequestError(
                message="Detach the routines and workflows using this source before deleting it",
                details={"subscription_ids": [str(sub.id) for sub in subscriptions]},
            )
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=EVENT_SOURCE.key,
            resource_id=source.id,
        )
        await repo.delete_source(self.db, source)
        await self._audit(ctx, source.id, "deleted")

    async def bind_routine(self, ctx: AuthContext, source_id: UUID, trigger_id: UUID) -> None:
        await self.get(ctx, source_id, perm=Perm.EVENT_SOURCES_USE, lock=True)
        trigger = await trigger_repo.get_by_id(self.db, trigger_id)
        if trigger is None or trigger.organization_id != ctx.organization_id:
            raise NotFoundError(message="Routine not found")
        agent = await agent_repo.get(self.db, trigger.agent_id, organization_id=ctx.organization_id)
        if agent is None or not all(
            [
                await resolve_access(self.db, ctx, agent, perm, resource_type=AGENT)
                for perm in (Perm.AGENTS_EDIT, Perm.AGENTS_RUN)
            ]
        ):
            raise AuthorizationError(
                message="Editing and running the agent is required to attach a source"
            )
        subscription = await repo.target_subscription(self.db, trigger_id=trigger_id)
        if subscription is None:
            subscription = EventSubscription(
                organization_id=ctx.organization_id, source_id=source_id, trigger_id=trigger_id
            )
        elif subscription.source_id == source_id:
            return
        else:
            # Keep the row referenced by both accepted and concurrently arriving dispatches.
            subscription.source_id = source_id
        await repo.save(self.db, subscription)

    async def bind_workflow(self, ctx: AuthContext, source_id: UUID, exposure_id: UUID) -> None:
        await self.get(ctx, source_id, perm=Perm.EVENT_SOURCES_USE, lock=True)
        exposure = await exposure_repo.get_by_id(self.db, exposure_id)
        if exposure is None or exposure.organization_id != ctx.organization_id:
            raise NotFoundError(message="Workflow entry not found")
        workflow = await workflow_repo.get(
            self.db, exposure.workflow_id, organization_id=ctx.organization_id
        )
        if workflow is None or not all(
            [
                await resolve_access(self.db, ctx, workflow, perm, resource_type=WORKFLOW)
                for perm in (Perm.WORKFLOWS_EDIT, Perm.WORKFLOWS_RUN)
            ]
        ):
            raise AuthorizationError(
                message="Editing and running the workflow is required to attach a source"
            )
        existing = await repo.target_subscription(self.db, exposure_id=exposure_id)
        if existing and existing.source_id == source_id:
            return
        await self.unbind_workflow(exposure_id)
        await repo.save(
            self.db,
            EventSubscription(
                organization_id=ctx.organization_id, source_id=source_id, exposure_id=exposure_id
            ),
        )

    async def unbind_workflow(self, exposure_id: UUID) -> None:
        await repo.unbind(self.db, exposure_id=exposure_id)

    async def receive(
        self, source_id: UUID, *, body: bytes, headers: Mapping[str, str]
    ) -> tuple[EventSource, EventDelivery, bool]:
        """Verify once, persist receipt and one durable dispatch per subscription atomically."""
        from app.services.agent_trigger import AgentTriggerService
        from app.worker.jobs import DISPATCH_SOURCE_EVENT, DispatchSourceEvent

        source = await repo.get(self.db, source_id)
        if source is None:
            raise NotFoundError(message="Event source not found")
        credential = await repo.credential(
            self.db, source.secret_id, organization_id=source.organization_id
        )
        if credential is None:
            raise NotFoundError(message="Source credential not found")
        verified_envelope = credential.sealed_secret
        credentials = SourceCredentials.model_validate_json(
            unseal(
                credential.sealed_secret,
                scope=VaultScope.organization(source.organization_id),
                key_version=credential.secret_key_version,
            )
        )
        auth = SourceAuth.model_validate(source.auth)
        headers = {key.lower(): value for key, value in headers.items()}
        if not verify_source(
            source.provider,
            auth,
            credentials,
            body=body,
            headers=headers,
            url=self.webhook_url(source.id),
        ):
            raise AuthorizationError(message="Webhook authentication did not verify")
        try:
            parsed = json.loads(body, parse_constant=_non_json_number)
            if source.provider == "hubspot" and isinstance(parsed, list):
                parsed = {"events": parsed}
            payload = _BODY.validate_python(parsed, strict=True)
            jsonb_value_fits(payload)
        except (ValueError, UnicodeError, RecursionError, ValidationError) as exc:
            raise BadRequestError(message="A webhook body must be a JSON object") from exc
        # Invalid requests never take the admission lock. A credential replacement
        # edits the envelope in place under that lock, so re-read it as well.
        source = await repo.get(self.db, source_id, lock=True)
        if source is None:
            raise NotFoundError(message="Event source not found")
        current = await repo.credential(
            self.db, source.secret_id, organization_id=source.organization_id
        )
        if (
            current is None
            or current.sealed_secret != verified_envelope
            or SourceAuth.model_validate(source.auth) != auth
        ):
            raise AuthorizationError(message="Webhook authentication changed during delivery")
        if auth.method == "standard_webhooks":
            external_id = headers.get("webhook-id") or None
        elif source.delivery_id_header and not auth.reserves_header(
            source.provider, source.delivery_id_header
        ):
            external_id = headers.get(source.delivery_id_header) or None
        elif auth.method in {"api_key", "hmac"} and auth.header_name == "x-delivery-id":
            # The default delivery ID header can also be configured for authentication.
            external_id = None
        else:
            external_id = trigger_events.delivery_id(source.provider, headers, payload)
        if external_id and len(external_id) > 255:
            raise BadRequestError(message="A delivery ID may contain at most 255 characters")
        receipt = EventDelivery(
            id=uuid4(),
            organization_id=source.organization_id,
            source_id=source.id,
            external_id=external_id,
            body=payload,
            headers={"x-github-event": headers["x-github-event"]}
            if source.provider == "github" and "x-github-event" in headers
            else {},
        )
        admitted = await repo.admit(self.db, receipt)
        if admitted and source.is_active:
            for sub in await repo.subscriptions(
                self.db, source.id, organization_id=source.organization_id, for_dispatch=True
            ):
                version_id = None
                principal_id = None
                policy_id = None
                if sub.trigger_id:
                    target_trigger = await trigger_repo.get_by_id(
                        self.db, sub.trigger_id, fresh=True
                    )
                    if (
                        not target_trigger
                        or not target_trigger.is_active
                        or target_trigger.source_id != source.id
                    ):
                        continue
                    policy_id = await AgentTriggerService(self.db).source_admission_policy(
                        target_trigger
                    )
                else:
                    target_exposure = await exposure_repo.get_by_id(
                        self.db, cast(UUID, sub.exposure_id)
                    )
                    if not target_exposure or not target_exposure.is_active:
                        continue
                    version_id = target_exposure.workflow_version_id
                    principal_id = target_exposure.execution_principal_user_id
                dispatch = await repo.save(
                    self.db,
                    EventDispatch(
                        organization_id=source.organization_id,
                        delivery_id=receipt.id,
                        subscription_id=sub.id,
                        routine_source_policy_id=policy_id,
                        workflow_version_id=version_id,
                        workflow_principal_user_id=principal_id,
                    ),
                )
                await enqueue(
                    self.db,
                    DISPATCH_SOURCE_EVENT,
                    DispatchSourceEvent(
                        organization_id=source.organization_id, dispatch_id=dispatch.id
                    ),
                    organization_id=source.organization_id,
                )
        return source, receipt, admitted

    async def dispatch(self, organization_id: UUID, dispatch_id: UUID) -> None:
        """A row lock and admission transaction make restart safe without coupling subscribers."""
        pending = await repo.dispatch(
            self.db, dispatch_id, organization_id=organization_id, lock=False
        )
        if pending is None or pending.status != "pending":
            return
        # Deletion and publication take the target lock before clearing the dispatch FK.
        if pending.workflow_version_id is not None:
            await hold_subject(self.db, LockScope.WORKFLOW_FILE_BYTES, organization_id)
        elif pending.subscription_id is not None:
            await repo.lock_dispatch_routine(
                self.db, subscription_id=pending.subscription_id, organization_id=organization_id
            )
        row = await repo.dispatch(self.db, dispatch_id, organization_id=organization_id)
        if row is None or row.status != "pending":
            return
        receipt = await repo.delivery(self.db, row.delivery_id, organization_id=organization_id)
        sub = (
            await repo.subscription(self.db, row.subscription_id, organization_id=organization_id)
            if row.subscription_id
            else None
        )
        source = (
            await repo.get(self.db, receipt.source_id, organization_id=organization_id)
            if receipt
            else None
        )
        status = "skipped"
        if (
            source
            and source.is_active
            and receipt
            and receipt.body is not None
            and sub
            and sub.source_id == source.id
        ):
            try:
                # Roll back partial target admission on a domain refusal, then keep its diagnostic.
                async with self.db.begin_nested():
                    if sub.trigger_id:
                        from app.services.agent_trigger import AgentTriggerService

                        admitted = await AgentTriggerService(self.db).fire_source_delivery(
                            sub.trigger_id,
                            source_id=source.id,
                            source_policy_id=row.routine_source_policy_id,
                            organization_id=organization_id,
                            body=receipt.body,
                            delivery_id=receipt.id,
                            received_at=receipt.created_at,
                            headers=receipt.headers,
                        )
                        status = "admitted" if admitted else "skipped"
                    else:
                        from app.schemas.workflow_exposure import WebhookAdmitted
                        from app.services.workflow_exposure import WorkflowExposureService

                        admitted_workflow = await WorkflowExposureService(
                            self.db
                        ).receive_source_delivery(
                            cast(UUID, sub.exposure_id),
                            organization_id=organization_id,
                            source_id=source.id,
                            body=receipt.body,
                            delivery_id=receipt.external_id or str(receipt.id),
                            receipt_id=receipt.id,
                            version_id=row.workflow_version_id,
                            principal_user_id=row.workflow_principal_user_id,
                        )
                        status = (
                            "admitted"
                            if isinstance(admitted_workflow, WebhookAdmitted)
                            else "skipped"
                        )
            except AppException as exc:
                if isinstance(exc, RateLimitError) or (
                    isinstance(exc, (WorkflowAdmissionQuotaError, WorkflowInlineStorageLimitError))
                    and exc.can_fit_when_idle
                ):
                    await self._defer_dispatch(row)
                    return
                status = "failed"
                row.error_code = exc.code
        row.status = status
        row.completed_at = datetime.now(UTC)
        await repo.save(self.db, row)

    async def _defer_dispatch(self, row: EventDispatch) -> None:
        """Capacity waits can outlast a job's crash retries. Keep one delayed retry queued."""
        from app.worker.jobs import DISPATCH_SOURCE_EVENT, DispatchSourceEvent

        now = datetime.now(UTC)
        # Waiting the elapsed age doubles the interval under sustained load.
        delay = min(max(now - row.created_at, timedelta(minutes=1)), timedelta(minutes=15))
        await enqueue(
            self.db,
            DISPATCH_SOURCE_EVENT,
            DispatchSourceEvent(organization_id=row.organization_id, dispatch_id=row.id),
            organization_id=row.organization_id,
            run_after=now + delay,
            dedupe_key=f"event-dispatch:{row.id}",
        )

    async def _audit(self, ctx: AuthContext, source_id: UUID, action: str) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action=f"event_source.{action}",
            target_type="event_source",
            target_id=str(source_id),
        )

    async def cleanup(self) -> None:
        before = datetime.now(UTC) - timedelta(days=settings.BACKGROUND_JOB_RETENTION_DAYS)
        await repo.settle_abandoned_dispatches(self.db, before=before)
        await repo.clear_terminal_payloads(self.db, before=before)
