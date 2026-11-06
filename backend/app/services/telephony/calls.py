"""Durable call intentions: reserve before dialing, fence retries and keep receipts."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.telephony import PhoneCall
from app.repositories import agent_run_repo, conversation_repo
from app.repositories import telephony as repo
from app.schemas.telephony import PhoneCallCreate, PhoneCallRead
from app.services.agent_registry import AgentRegistryService
from app.services.background_jobs import enqueue
from app.services.conversation import ConversationService
from app.services.telephony.policy import PhonePolicyService, contact_fingerprint
from app.worker.jobs import DIAL_PHONE, DialPhone


class PhoneCallService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.policy = PhonePolicyService(db)

    async def create(
        self, ctx: AuthContext, data: PhoneCallCreate, *, source_run_id: UUID | None = None
    ) -> PhoneCallRead:
        if (
            ctx.user_id is None
            or ctx.subject_is_publisher_fallback
            or ctx.api_key_id is not None
            or current_impersonator() is not None
        ):
            raise AuthorizationError(
                message="A telephone call needs the consenting member behind it"
            )
        await hold_subject(self.db, LockScope.PERSONAL_DATA_PER_USER, ctx.subject_id)
        await hold_subject(self.db, LockScope.PHONE_CALLS_PER_ORG, ctx.organization_id)
        if data.outcome_id is not None:
            previous_case = await repo.call_for_case(
                self.db,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                outcome_id=data.outcome_id,
            )
            if previous_case is not None:
                return PhoneCallRead.model_validate(previous_case)
        if source_run_id is not None and data.outcome_id is None:
            previous_source = await repo.call_for_source(
                self.db,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                source_run_id=source_run_id,
                endpoint_id=data.endpoint_id,
            )
            if previous_source is not None:
                return PhoneCallRead.model_validate(previous_source)
        fingerprint = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        existing = await repo.request(self.db, ctx.organization_id, data.request_key)
        if existing is not None:
            if existing.user_id != ctx.user_id or existing.request_hash != fingerprint:
                raise ConflictError(
                    message="This call request key already belongs to a different intention"
                )
            return PhoneCallRead.model_validate(existing)
        endpoint, _, auth = await self.policy.load_endpoint(
            data.endpoint_id, organization_id=ctx.organization_id, lock=True
        )
        contact = await repo.contact(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        if contact is None:
            raise AuthorizationError(
                message="Opt into phone calls on your verified SMS number first"
            )
        number = await self.policy.available_contact(contact, mode=data.mode)
        version_id = None
        agent_id = data.agent_id
        purpose = "direct"
        not_before = datetime.now(UTC)
        if data.agent_id is not None:
            agent = await AgentRegistryService(self.db).get(
                ctx, data.agent_id, perm=Perm.AGENTS_RUN
            )
            version_id = agent.current_version_id
        if data.source_conversation_id is not None:
            await ConversationService(self.db).get_conversation(
                data.source_conversation_id,
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                for_write=True,
                include_favourite=False,
            )
        if source_run_id is not None:
            run = await agent_run_repo.get_run(
                self.db, source_run_id, organization_id=ctx.organization_id
            )
            if (
                run is None
                or run.user_id != ctx.user_id
                or run.is_test
                or run.key_scopes is not None
                or run.initiated_by_publisher_fallback
            ):
                raise AuthorizationError(
                    message="The call needs a production run admitted for this member"
                )
            if str(run.agent_id) not in contact.agent_ids:
                raise AuthorizationError(
                    message="Select this agent in your telephone contact consent first"
                )
            if data.agent_id is not None and data.agent_id != run.agent_id:
                raise AuthorizationError(
                    message="The telephone agent must match the originating run"
                )
            agent_id = run.agent_id
            purpose = "scheduled" if run.routine_origin_id is not None else "direct"
            if data.mode == "conversation":
                if run.routine_origin_id is not None:
                    raise AuthorizationError(
                        message="Scheduled work may prepare an opted-in spoken report; start an interactive call from your console"
                    )
                if run.agent_id != data.agent_id or run.agent_version_id is None:
                    raise AuthorizationError(
                        message="The telephone agent must match this run's published version"
                    )
                version_id = run.agent_version_id
        if data.mode == "conversation":
            from app.services.voice.settings import resolve_voice

            if data.agent_id is None or version_id is None:
                raise BadRequestError(message="Choose a published voice agent")
            _, spec, _ = await AgentRegistryService(self.db).get_pinned_spec(
                ctx, data.agent_id, version_id
            )
            if resolve_voice(spec.voice) is None:
                raise BadRequestError(
                    message="The selected published agent is not configured for voice calls"
                )
        if data.outcome_id is not None:
            from app.services.telephony.cases import eligible_case

            if agent_id is None:
                raise AuthorizationError(message="Important-case contact needs its selected agent")
            not_before = await eligible_case(
                self.db,
                ctx,
                contact,
                outcome_id=data.outcome_id,
                agent_id=agent_id,
                conversation_id=data.source_conversation_id,
            )
            purpose = "important"
        cost = await self.policy.admit_budget(endpoint)
        if data.outcome_id is not None and not await repo.mark_case_phone_attempt(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            outcome_id=data.outcome_id,
            at=datetime.now(UTC),
        ):
            raise ConflictError(message="This case is settled or already had its telephone attempt")
        row = PhoneCall(
            id=uuid4(),
            organization_id=ctx.organization_id,
            endpoint_id=endpoint.id,
            endpoint_generation=endpoint.generation,
            request_key=data.request_key,
            request_hash=fingerprint,
            user_id=ctx.user_id,
            contact_id=contact.id,
            contact_hash=contact_fingerprint(contact),
            agent_id=agent_id,
            agent_version_id=version_id,
            purpose=purpose,
            outcome_id=data.outcome_id,
            importance_reason=data.importance_reason,
            not_before=not_before,
            source_context_required=data.source_conversation_id is not None,
            source_required=source_run_id is not None,
            source_run_id=source_run_id,
            source_conversation_id=data.source_conversation_id,
            account_sid=auth.account,
            direction="outbound",
            mode=data.mode,
            status="queued",
            destination=number,
            report_language=contact.report_language,
            report=data.report,
            cap_seconds=endpoint.max_call_seconds,
            price_per_minute_usd=endpoint.price_per_minute_usd,
            estimated_cost_usd=cost,
            expires_at=max(datetime.now(UTC), not_before)
            + timedelta(seconds=endpoint.max_call_seconds + 60),
        )
        if data.mode == "report":
            conversation = await conversation_repo.create_conversation(
                self.db,
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                title="Spoken report",
            )
            row.conversation_id = conversation.id
            await conversation_repo.create_message(
                self.db,
                conversation_id=conversation.id,
                role="assistant",
                content="Prepared spoken report (playback is not confirmed):\n\n"
                + (data.report or ""),
            )
        await repo.save(self.db, row)
        if data.source_conversation_id is not None:
            await conversation_repo.create_message(
                self.db,
                conversation_id=data.source_conversation_id,
                role="assistant",
                content="Telephone call requested. Its receipt and transcript are available to the call owner.",
                client_message_id=f"phone:{row.id}",
                parts=[{"type": "phone_call", "phone_call_id": str(row.id)}],
            )
        from app.services.change_feed import announce_conversation

        if row.conversation_id is not None:
            announce_conversation(
                self.db,
                organization_id=ctx.organization_id,
                conversation_id=row.conversation_id,
                actor_user_id=ctx.user_id,
            )
        if data.source_conversation_id is not None:
            announce_conversation(
                self.db,
                organization_id=ctx.organization_id,
                conversation_id=data.source_conversation_id,
                actor_user_id=ctx.user_id,
            )
        await enqueue(
            self.db,
            DIAL_PHONE,
            DialPhone(call_id=row.id),
            organization_id=ctx.organization_id,
            dedupe_key=f"phone:{row.id}",
            run_after=not_before,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="phone.call_requested",
            target_type="phone_call",
            target_id=str(row.id),
            details={"mode": row.mode, "endpoint_id": str(endpoint.id)},
        )
        return PhoneCallRead.model_validate(row)

    async def inbound(self, endpoint_id: UUID, params: dict[str, str]) -> PhoneCall:
        endpoint, _, auth = await self.policy.load_endpoint(endpoint_id)
        await hold_subject(self.db, LockScope.PHONE_CALLS_PER_ORG, endpoint.organization_id)
        endpoint, _, auth = await self.policy.load_endpoint(endpoint_id, lock=True)
        if (
            params.get("AccountSid") != auth.account
            or params.get("To") != auth.number
            or endpoint.inbound_embed_id is None
        ):
            raise AuthorizationError(message="This number does not accept inbound agent calls")
        from app.services.telephony.provider import SID

        sid = params.get("CallSid", "")
        if not SID.fullmatch(sid):
            raise AuthorizationError(message="Invalid inbound telephone receipt")
        key = uuid5(endpoint.id, sid)
        previous = await repo.request(self.db, endpoint.organization_id, key)
        if previous is not None:
            if (
                previous.status in repo.TERMINAL
                or previous.endpoint_generation != endpoint.generation
                or previous.expires_at <= datetime.now(UTC)
            ):
                raise ConflictError(message="This inbound call has already ended")
            return previous
        cost = await self.policy.admit_budget(endpoint)
        row = PhoneCall(
            organization_id=endpoint.organization_id,
            endpoint_id=endpoint.id,
            endpoint_generation=endpoint.generation,
            request_key=key,
            request_hash=hashlib.sha256(sid.encode()).hexdigest(),
            account_sid=auth.account,
            provider_sid=sid,
            direction="inbound",
            mode="conversation",
            status="ringing",
            cap_seconds=endpoint.max_call_seconds,
            price_per_minute_usd=endpoint.price_per_minute_usd,
            estimated_cost_usd=cost,
            expires_at=datetime.now(UTC) + timedelta(seconds=endpoint.max_call_seconds + 30),
        )
        return await repo.save(self.db, row)

    async def readable(self, ctx: AuthContext, call_id: UUID, *, lock: bool = False) -> PhoneCall:
        row = await repo.call(self.db, call_id, organization_id=ctx.organization_id, lock=lock)
        if row is None or (row.user_id != ctx.user_id and not ctx.has(Perm.CHANNELS_MANAGE)):
            raise NotFoundError(message="Telephone call not found")
        return row

    async def controllable(
        self, ctx: AuthContext, call_id: UUID, *, lock: bool = False
    ) -> PhoneCall:
        """Only the initiating member's current session may control a live call."""
        row = await self.readable(ctx, call_id, lock=lock)
        if (
            ctx.user_id is None
            or ctx.api_key_id is not None
            or current_impersonator() is not None
            or row.user_id != ctx.user_id
        ):
            raise AuthorizationError(message="Only the call owner may control this telephone call")
        return row

    async def get(self, ctx: AuthContext, call_id: UUID) -> PhoneCallRead:
        return PhoneCallRead.model_validate(await self.readable(ctx, call_id))

    async def recent(self, ctx: AuthContext) -> list[PhoneCallRead]:
        return [
            PhoneCallRead.model_validate(row)
            for row in await repo.recent_calls(
                self.db,
                organization_id=ctx.organization_id,
                user_id=None if ctx.has(Perm.CHANNELS_MANAGE) else ctx.subject_id,
            )
        ]
