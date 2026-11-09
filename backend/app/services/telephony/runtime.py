"""Execute an admitted phone intent, bind one media stream and always bound provider time."""

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import anyio
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.telephony import PhoneCall
from app.db.session import get_worker_db_context
from app.repositories import agent_embed_repo, agent_run_repo, voice_call_repo
from app.repositories import telephony as repo
from app.schemas.telephony import PhoneChoice
from app.schemas.voice import ReadyFrame
from app.services.access import acting_member, publisher_context
from app.services.agent_embed import Admission
from app.services.agent_registry import AgentRegistryService
from app.services.conversation import ConversationService
from app.services.telephony.calls import PhoneCallService
from app.services.telephony.policy import PhonePolicyService, contact_fingerprint
from app.services.telephony.provider import (
    AcceptanceUnknown,
    PhoneCredentials,
    PhoneProvider,
    TwilioPhoneProvider,
    call_twiml,
    signature_ok,
    stream_nonce,
    url,
)
from app.services.telephony.stream import PhoneStream
from app.services.voice.embed import embed_caller
from app.services.voice.session import VoiceCallSession, still_allowed
from app.services.voice.starter import VoiceCaller
from app.services.voice.transcript import SessionFactory

logger = logging.getLogger(__name__)


async def live_contact(db: AsyncSession, row: PhoneCall) -> AuthContext:
    if row.user_id is None or row.contact_id is None:
        raise AuthorizationError(message="This call has no consenting member")
    policy = PhonePolicyService(db)
    contact = await repo.contact_by_id(db, row.contact_id, organization_id=row.organization_id)
    if (
        contact is None
        or contact.user_id != row.user_id
        or contact_fingerprint(contact) != row.contact_hash
    ):
        raise AuthorizationError(message="The phone contact's consent changed")
    number = await policy.available_contact(contact, mode=row.mode, reserved_call_id=row.id)
    if number != row.destination:
        raise AuthorizationError(message="The verified phone number changed")
    ctx = await acting_member(db, row.organization_id, str(row.user_id))
    if ctx is None:
        raise AuthorizationError(message="The call's member is no longer active")
    if row.mode == "conversation" and row.agent_id is None:
        raise AuthorizationError(message="The telephone agent no longer exists")
    if row.agent_id is not None:
        await AgentRegistryService(db).get(ctx, row.agent_id, perm=Perm.AGENTS_RUN)
        if row.mode == "conversation" and row.agent_version_id is None:
            raise AuthorizationError(message="The admitted voice version no longer exists")
    if row.source_context_required and row.source_conversation_id is None:
        raise AuthorizationError(
            message="The telephone intention's source context no longer exists"
        )
    if row.source_conversation_id is not None:
        await ConversationService(db).get_conversation(
            row.source_conversation_id,
            organization_id=row.organization_id,
            user_id=row.user_id,
            for_write=False,
            include_favourite=False,
        )
    if row.source_required and row.source_run_id is None:
        raise AuthorizationError(
            message="The telephone intention's original authority no longer exists"
        )
    if row.purpose == "important":
        from app.services.telephony.cases import eligible_case

        if row.outcome_id is None or row.agent_id is None:
            raise AuthorizationError(message="The original telephone case no longer exists")
        await eligible_case(
            db,
            ctx,
            contact,
            outcome_id=row.outcome_id,
            agent_id=row.agent_id,
            conversation_id=row.source_conversation_id,
        )
    if row.source_run_id is not None:
        from app.services.routine_authority import RoutineAuthority

        source = await agent_run_repo.get_run(
            db, row.source_run_id, organization_id=row.organization_id
        )
        if source is None or source.user_id != row.user_id:
            raise AuthorizationError(message="The telephone intention's source no longer exists")
        if str(source.agent_id) not in contact.agent_ids:
            raise AuthorizationError(message="The source agent no longer has phone consent")
        authority = await RoutineAuthority.capture(db, ctx, agent_id=source.agent_id, run=source)
        if authority is not None:
            await authority.check_in(db, source.agent_id)
    return ctx


async def dial(
    call_id: UUID,
    *,
    provider: PhoneProvider | None = None,
    sessions: SessionFactory = get_worker_db_context,
) -> None:
    adapter = provider or TwilioPhoneProvider()
    async with sessions() as db:
        row = await repo.call(db, call_id)
        if row is None:
            return
        await hold_subject(db, LockScope.PHONE_CALLS_PER_ORG, row.organization_id)
        if row.purpose == "important":
            await repo.lock_case_admission(db, row)
        row = await repo.call(db, call_id, lock=True)
        if row is None or row.status != "queued":
            return
        if row.not_before is not None and row.not_before > datetime.now(UTC):
            from app.services.background_jobs import enqueue
            from app.worker.jobs import DIAL_PHONE, DialPhone

            await enqueue(
                db,
                DIAL_PHONE,
                DialPhone(call_id=row.id),
                organization_id=row.organization_id,
                run_after=row.not_before,
                dedupe_key=f"phone:{row.id}",
            )
            return
        try:
            endpoint, _, auth = await PhonePolicyService(db).load_endpoint(
                row.endpoint_id, organization_id=row.organization_id, lock=True
            )
            if endpoint.generation != row.endpoint_generation or row.expires_at <= datetime.now(
                UTC
            ):
                raise ConflictError(message="The phone intention expired or its endpoint changed")
            await live_contact(db, row)
        except AppException:
            row.status = "cancelled"
            row.finished_at = datetime.now(UTC)
            row.estimated_cost_usd = Decimal(0)
            await repo.save(db, row)
            await db.commit()
            return
        row.status = "dialing"
        await repo.save(db, row)
        # A crash after this point must never dial again, even if POST never began.
        await db.commit()
        target = row.destination
        assert target is not None
        twiml = call_twiml(auth, row)
        cap = row.cap_seconds
    try:
        sid = await adapter.dial(
            auth, number=target, twiml=twiml, callback=url(f"/status/{call_id}"), cap_seconds=cap
        )
    except AcceptanceUnknown:
        await _settle_submission(sessions, call_id, status="unknown")
    except AppException:
        await _settle_submission(sessions, call_id, status="failed")
    else:
        if await _settle_submission(sessions, call_id, status="ringing", sid=sid):
            await end_media(call_id, provider=adapter, sessions=sessions)


async def _settle_submission(
    sessions: SessionFactory,
    call_id: UUID,
    *,
    status: Literal["unknown", "failed", "ringing"],
    sid: str | None = None,
) -> bool:
    async with sessions() as db:
        row = await repo.call(db, call_id, lock=True)
        if row is None or row.status not in {"dialing", "unknown", "ending"}:
            return False
        was_ending = row.status == "ending"
        if sid is not None:
            if row.provider_sid is not None and row.provider_sid != sid:
                row.status = "unknown"
            else:
                row.provider_sid = sid
                row.status = status
        else:
            row.status = status
        if was_ending and row.status != "failed":
            row.status = "ending"
        if row.status == "failed":
            row.estimated_cost_usd = Decimal(0)
            row.finished_at = datetime.now(UTC)
        await repo.save(db, row)
        await db.commit()
        return was_ending and sid is not None and row.provider_sid == sid and row.status == "ending"


async def cap_inbound(
    db: AsyncSession, call: PhoneCall, *, provider: PhoneProvider | None = None
) -> str:
    _, _, auth = await PhonePolicyService(db).load_endpoint(
        call.endpoint_id, organization_id=call.organization_id
    )
    assert call.provider_sid is not None
    sid = call.provider_sid
    cap = min(
        call.cap_seconds,
        int(
            (
                call.created_at + timedelta(seconds=call.cap_seconds) - datetime.now(UTC)
            ).total_seconds()
        ),
    )
    if cap < 1:
        raise ConflictError(message="The inbound call has reached its original deadline")
    text = call_twiml(auth, call)
    # The inbound receipt is visible before a provider update or media handshake.
    await db.commit()
    await (provider or TwilioPhoneProvider()).cap(auth, sid, cap)
    return text


async def status_callback(db: AsyncSession, call_id: UUID, params: dict[str, str]) -> None:
    row = await repo.call(db, call_id, lock=True)
    if row is None:
        raise NotFoundError(message="Telephone receipt not found")
    auth = await _cleanup_credentials(db, row)
    sid = params.get("CallSid", "")
    from app.services.telephony.provider import SID

    if (
        params.get("AccountSid") != auth.account
        or auth.account != row.account_sid
        or not SID.fullmatch(sid)
        or (row.provider_sid is not None and row.provider_sid != sid)
    ):
        raise AuthorizationError(message="Telephone receipt does not match this call")
    if row.direction == "outbound" and (
        params.get("To") != row.destination or params.get("From") != auth.number
    ):
        raise AuthorizationError(
            message="Telephone destination does not match the admitted contact"
        )
    if row.direction == "inbound" and params.get("To") != auth.number:
        raise AuthorizationError(message="Telephone destination does not match this number")
    row.provider_sid = sid
    status = params.get("CallStatus")
    terminal = row.status in repo.TERMINAL
    if terminal and status != "completed":
        return
    if status in {"completed", "busy", "no-answer", "failed", "canceled"}:
        if not terminal:
            row.status = "completed" if status == "completed" else "failed"
            row.finished_at = datetime.now(UTC)
        duration = params.get("CallDuration", "")
        # Whole billable minutes, at the operator's conservative rate. Never a
        # claim about Twilio's invoice; unknown/transfer durations retain the cap.
        if status != "completed":
            row.estimated_cost_usd = Decimal(0)
        elif (
            duration.isascii()
            and duration.isdecimal()
            and len(duration) <= 6
            and row.transferred_contact_id is None
        ):
            seconds = min(int(duration), row.cap_seconds)
            minutes = max(1, (seconds + 59) // 60)
            row.estimated_cost_usd = min(row.estimated_cost_usd, row.price_per_minute_usd * minutes)
    await repo.save(db, row)


async def hangup(
    db: AsyncSession, ctx: AuthContext, call_id: UUID, *, provider: PhoneProvider | None = None
) -> None:
    row = await PhoneCallService(db).controllable(ctx, call_id, lock=True)
    if row.status in repo.TERMINAL:
        return
    previous_status = row.status
    row.status = "ending"
    if previous_status == "queued":
        row.status = "cancelled"
        row.finished_at = datetime.now(UTC)
        row.estimated_cost_usd = Decimal(0)
    await repo.save(db, row)
    await db.commit()
    await end_media(
        call_id, provider=provider or TwilioPhoneProvider(), sessions=get_worker_db_context
    )


async def transfer(
    db: AsyncSession,
    call_id: UUID,
    contact_id: UUID,
    *,
    ctx: AuthContext | None = None,
    source_run_id: UUID | None = None,
    endpoint_id: UUID | None = None,
    provider: PhoneProvider | None = None,
) -> None:
    initial = await repo.call(db, call_id)
    if initial is None:
        raise NotFoundError(message="Telephone call not found")
    await hold_subject(db, LockScope.PHONE_CALLS_PER_ORG, initial.organization_id)
    row = await repo.call(db, call_id, lock=True)
    assert row is not None
    if ctx is not None:
        await PhoneCallService(db).controllable(ctx, call_id)
    elif source_run_id is not None and row.voice_call_id is not None:
        voice = await voice_call_repo.get(
            db, row.voice_call_id, organization_id=row.organization_id
        )
        if voice is None or voice.run_id != source_run_id or row.endpoint_id != endpoint_id:
            raise AuthorizationError(message="This agent run does not own that telephone stream")
    else:
        raise AuthorizationError(
            message="A transfer needs the live telephone run or its console owner"
        )
    if row.status != "active" or row.provider_sid is None or row.transferred_contact_id is not None:
        raise ConflictError(message="Only an active, untransferred call can be transferred")
    endpoint, _, auth = await PhonePolicyService(db).load_endpoint(
        row.endpoint_id, organization_id=row.organization_id, lock=True
    )
    if (
        endpoint.generation != row.endpoint_generation
        or str(contact_id) not in endpoint.transfer_contact_ids
    ):
        raise AuthorizationError(message="That contact is not an allowed transfer target")
    target = await repo.contact_by_id(db, contact_id, organization_id=row.organization_id)
    if target is None:
        raise NotFoundError(message="Transfer contact not found")
    number = await PhonePolicyService(db).available_contact(
        target, mode="transfer", reserved_call_id=row.id
    )
    hard_end = min(
        row.expires_at,
        (row.stream_claimed_at or row.created_at) + timedelta(seconds=row.cap_seconds),
    )
    remaining = int((hard_end - datetime.now(UTC)).total_seconds())
    if remaining < 1:
        raise ConflictError(message="This call has reached its time limit")
    row.transferred_contact_id = target.id
    row.status = "transferring"
    sid = row.provider_sid
    await repo.save(db, row)
    await db.commit()
    try:
        await (provider or TwilioPhoneProvider()).transfer(
            auth, sid, number=number, seconds=remaining
        )
    except AcceptanceUnknown:
        # Closing our media stream must not hang up a possibly accepted transfer.
        raise
    except AppException:
        current = await repo.call(db, call_id, lock=True)
        if current is not None and current.status == "transferring":
            current.status = "active"
            current.transferred_contact_id = None
            await repo.save(db, current)
            await db.commit()
        raise
    current = await repo.call(db, call_id, lock=True)
    if current is not None and current.status == "transferring":
        current.status = "transferred"
        await repo.save(db, current)
        await db.commit()


async def media(
    websocket: WebSocket,
    call_id: UUID,
    *,
    provider: PhoneProvider | None = None,
    sessions: SessionFactory = get_worker_db_context,
) -> None:
    adapter = provider or TwilioPhoneProvider()
    async with sessions() as db:
        row = await repo.call(db, call_id)
        if (
            row is None
            or row.mode != "conversation"
            or row.status not in {"dialing", "unknown", "ringing", "active"}
            or row.stream_claimed_at is not None
        ):
            await websocket.close(code=1008)
            return
        policy = PhonePolicyService(db)
        endpoint, _, auth = await policy.load_endpoint(
            row.endpoint_id, organization_id=row.organization_id
        )
        if auth.account != row.account_sid:
            raise AuthorizationError(message="The telephone account no longer matches this call")
        address = url(f"/media/{call_id}", websocket=True)
        signature = websocket.headers.get("x-twilio-signature", "")
        if not (
            signature_ok(auth, address, {}, signature)
            or signature_ok(auth, address + "/", {}, signature)
        ):
            await websocket.close(code=1008)
            return
        sid, nonce = row.provider_sid, stream_nonce(auth, row)
    await websocket.accept()

    async def ready(frame: ReadyFrame) -> None:
        async with sessions() as db:
            row = await repo.call(db, call_id, lock=True)
            if row is None or row.status not in {"dialing", "unknown", "ringing", "active"}:
                raise WebSocketDisconnect(1008)
            row.voice_call_id = frame.call_id
            row.conversation_id = frame.conversation_id
            row.status = "active"
            await repo.save(db, row)
            await db.commit()

    stream = PhoneStream(
        websocket, account_sid=auth.account, call_sid=sid, nonce=nonce, ready=ready
    )
    session_started = False
    claimed = False
    try:
        await stream.start()
        assert stream.call is not None
        caller = await _claim_stream(call_id, sessions, provider_sid=stream.call)
        claimed = True

        async def reauthorize(db: AsyncSession) -> AuthContext | None:
            try:
                current = await repo.call(db, call_id)
                if (
                    current is None
                    or current.status in repo.TERMINAL
                    or current.status in {"ending", "transferring", "transferred"}
                ):
                    return None
                endpoint, _, _ = await PhonePolicyService(db).load_endpoint(
                    current.endpoint_id, organization_id=current.organization_id
                )
                if (
                    endpoint.generation != current.endpoint_generation
                    or current.expires_at <= datetime.now(UTC)
                ):
                    return None
                if current.direction == "outbound":
                    await live_contact(db, current)
                assert caller.agent_id is not None
                return await still_allowed(db, caller, agent_id=caller.agent_id)
            except AppException:
                return None

        session_started = True
        await VoiceCallSession(stream, caller, sessions=sessions, reauthorize=reauthorize).run()
    except WebSocketDisconnect, TimeoutError:
        stream.ended_reason = stream.ended_reason or (
            "disconnected" if session_started else "bad_stream"
        )
    except AppException:
        stream.ended_reason = "revoked"
        raise
    finally:
        with anyio.CancelScope(shield=True):
            try:
                if claimed:
                    await end_media(
                        call_id, provider=adapter, sessions=sessions, end_reason=stream.ended_reason
                    )
            except AppException:
                logger.warning("phone_cleanup_pending", extra={"call_id": str(call_id)})
            finally:
                await websocket.close()


async def _cleanup_credentials(db: AsyncSession, row: PhoneCall) -> PhoneCredentials:
    from app.repositories import channel_bot_repo
    from app.services.telephony.provider import credentials

    endpoint = await repo.endpoint(db, row.endpoint_id, organization_id=row.organization_id)
    if endpoint is None:
        raise NotFoundError(message="Telephone routing no longer exists")
    bot = await channel_bot_repo.get_for_org(
        db, endpoint.bot_id, organization_id=row.organization_id
    )
    if bot is None or bot.authorization_generation != endpoint.bot_generation:
        raise AuthorizationError(
            message="The original telephone account is unavailable for cleanup"
        )
    auth = credentials(bot)
    if auth.account != row.account_sid:
        raise AuthorizationError(
            message="The original telephone account is unavailable for cleanup"
        )
    return auth


async def end_media(
    call_id: UUID,
    *,
    provider: PhoneProvider,
    sessions: SessionFactory,
    end_reason: str | None = None,
) -> None:
    async with sessions() as db:
        row = await repo.call(db, call_id, lock=True)
        if row is None or row.status in {"transferring", "transferred"}:
            return
        sid = row.provider_sid
        if row.status in repo.TERMINAL:
            return
        row.status = "ending"
        if end_reason is not None:
            row.end_reason = end_reason[:64]
        await repo.save(db, row)
        await db.commit()
        auth = await _cleanup_credentials(db, row)
    if sid is None:
        return
    await provider.hangup(auth, sid)
    async with sessions() as db:
        row = await repo.call(db, call_id, lock=True)
        if row is not None and row.status == "ending":
            row.status = (
                "completed"
                if row.end_reason in {None, "user", "time_limit", "disconnected"}
                else "failed"
            )
            row.finished_at = datetime.now(UTC)
            await repo.save(db, row)
            await db.commit()


async def reap(
    *, provider: PhoneProvider | None = None, sessions: SessionFactory = get_worker_db_context
) -> int:
    adapter = provider or TwilioPhoneProvider()
    cursor: UUID | None = None
    count = 0
    while True:
        async with sessions() as db:
            identifiers = await repo.live_page(db, after=cursor)
        if not identifiers:
            async with sessions() as db:
                await repo.purge_receipts(db)
                await db.commit()
            return count
        for identifier in identifiers:
            count += int(await _reap_one(identifier, provider=adapter, sessions=sessions))
        cursor = identifiers[-1]


async def _reap_one(identifier: UUID, *, provider: PhoneProvider, sessions: SessionFactory) -> bool:
    async with sessions() as db:
        row = await repo.call(db, identifier)
        if row is None or row.status in repo.TERMINAL:
            return False
        now = datetime.now(UTC)
        hard_end = (
            min(
                row.expires_at,
                (row.stream_claimed_at or row.created_at) + timedelta(seconds=row.cap_seconds),
            )
            if row.stream_claimed_at is not None
            else row.expires_at
        )
        expired = now >= hard_end
        must_end = expired or row.status == "ending"
        if not must_end:
            try:
                endpoint, _, _ = await PhonePolicyService(db).load_endpoint(
                    row.endpoint_id, organization_id=row.organization_id
                )
                if endpoint.generation != row.endpoint_generation:
                    raise ConflictError(message="Telephone routing changed")
                if row.direction == "outbound":
                    await live_contact(db, row)
                if row.transferred_contact_id is not None:
                    target = await repo.contact_by_id(
                        db, row.transferred_contact_id, organization_id=row.organization_id
                    )
                    if target is None:
                        raise AuthorizationError(message="The transfer contact was removed")
                    await PhonePolicyService(db).available_contact(
                        target, mode="transfer", reserved_call_id=row.id
                    )
            except AppException:
                must_end = True
        if not must_end:
            return False
        row = await repo.call(db, identifier, lock=True)
        if row is None or row.status in repo.TERMINAL:
            return False
        row.status = "ending"
        await repo.save(db, row)
        sid = row.provider_sid
        try:
            auth = await _cleanup_credentials(db, row)
        except AppException:
            auth = None
        # Release the row lock and durably retain cleanup intent before provider IO.
        await db.commit()
    cleanup_available = auth is not None
    try:
        if auth is not None and sid is not None:
            await provider.hangup(auth, sid)
    except AppException:
        cleanup_available = False
    if not cleanup_available:
        logger.warning("phone_reaper_provider_unavailable", extra={"call_id": str(identifier)})
        if not expired:
            return False
        # Every admitted provider leg already has its own hard time limit.
        # Keep the reservation when cleanup cannot confirm its final invoice.
    elif sid is None and not expired:
        return False
    async with sessions() as db:
        row = await repo.call(db, identifier, lock=True)
        # A signed callback can settle the receipt while hang-up is in flight.
        if row is None or row.status != "ending":
            return False
        row.status = "failed"
        row.finished_at = now
        await repo.save(db, row)
        await db.commit()
        return True


async def _claim_stream(
    call_id: UUID, sessions: SessionFactory, *, provider_sid: str
) -> VoiceCaller:
    async with sessions() as db:
        row = await repo.call(db, call_id)
        if row is None:
            raise WebSocketDisconnect(1008)
        await hold_subject(db, LockScope.PHONE_CALLS_PER_ORG, row.organization_id)
        row = await repo.call(db, call_id, lock=True)
        assert row is not None
        endpoint, _, _ = await PhonePolicyService(db).load_endpoint(
            row.endpoint_id, organization_id=row.organization_id, lock=True
        )
        if (
            row.stream_claimed_at is not None
            or row.status in repo.TERMINAL
            or endpoint.generation != row.endpoint_generation
            or row.expires_at <= datetime.now(UTC)
            or row.status not in {"dialing", "unknown", "ringing", "active"}
            or (row.provider_sid is not None and row.provider_sid != provider_sid)
        ):
            raise WebSocketDisconnect(1008)
        cap = min(row.cap_seconds, int((row.expires_at - datetime.now(UTC)).total_seconds()))
        if row.direction == "outbound":
            ctx = await live_contact(db, row)
            conversation_id = None
            if row.source_conversation_id is not None:
                source = await ConversationService(db).get_conversation(
                    row.source_conversation_id,
                    organization_id=row.organization_id,
                    user_id=row.user_id,
                    for_write=True,
                    include_favourite=False,
                )
                if source.project_id is None and source.user_id == row.user_id:
                    conversation_id = source.id
            context = None
            if row.outcome_id is not None:
                case = await repo.own_case(
                    db,
                    organization_id=row.organization_id,
                    user_id=ctx.subject_id,
                    outcome_id=row.outcome_id,
                )
                if case is not None:
                    context = json.dumps(
                        {
                            "outcome_id": str(case.id),
                            "case_summary": case.summary[:1200],
                            "contact_reason": row.importance_reason,
                        },
                        ensure_ascii=False,
                    )
            caller = VoiceCaller(
                ctx=ctx,
                user_id=row.user_id,
                user_name=None,
                surface="web",
                anonymous=False,
                auth_token=None,
                embed_id=None,
                agent_id=row.agent_id,
                conversation_id=conversation_id,
                phone_call_id=row.id,
                phone_context=context,
                phone_cap_seconds=cap,
                phone_agent_version_id=row.agent_version_id,
            )
        else:
            if endpoint.inbound_embed_id is None:
                raise WebSocketDisconnect(1008)
            embed = await agent_embed_repo.get(
                db, endpoint.inbound_embed_id, organization_id=row.organization_id
            )
            if embed is None:
                raise WebSocketDisconnect(1008)
            ctx = await publisher_context(
                db, organization_id=row.organization_id, publisher_user_id=embed.owner_user_id
            )
            await PhonePolicyService(db).public_embed(ctx, embed.id)
            caller = replace(
                await embed_caller(db, Admission(embed=embed, visitor=None), visitor_key=None),
                phone_call_id=row.id,
                phone_cap_seconds=cap,
            )
        row.stream_claimed_at = datetime.now(UTC)
        row.provider_sid = provider_sid
        await repo.save(db, row)
        await db.commit()
    return caller


async def end_from_agent(
    db: AsyncSession, call_id: UUID, *, source_run_id: UUID, endpoint_id: UUID
) -> None:
    row = await repo.call(db, call_id, lock=True)
    if (
        row is None
        or row.endpoint_id != endpoint_id
        or row.voice_call_id is None
        or row.status != "active"
    ):
        raise AuthorizationError(message="This run does not hold an active telephone call")
    voice = await voice_call_repo.get(db, row.voice_call_id, organization_id=row.organization_id)
    if voice is None or voice.run_id != source_run_id:
        raise AuthorizationError(message="This run does not own that telephone call")
    row.status = "ending"
    await repo.save(db, row)
    await db.commit()
    await end_media(call_id, provider=TwilioPhoneProvider(), sessions=get_worker_db_context)


async def transfer_options(
    db: AsyncSession,
    call_id: UUID,
    *,
    ctx: AuthContext | None = None,
    source_run_id: UUID | None = None,
    endpoint_id: UUID | None = None,
) -> list[PhoneChoice]:
    from app.repositories import user_repo

    row = await repo.call(db, call_id)
    if row is None:
        raise NotFoundError(message="Telephone call not found")
    if ctx is not None:
        await PhoneCallService(db).controllable(ctx, call_id)
    elif (
        row.voice_call_id is not None
        and source_run_id is not None
        and row.endpoint_id == endpoint_id
    ):
        voice = await voice_call_repo.get(
            db, row.voice_call_id, organization_id=row.organization_id
        )
        if voice is None or voice.run_id != source_run_id:
            raise AuthorizationError(message="This run does not own that telephone call")
    else:
        raise AuthorizationError(message="A live telephone call is required")
    endpoint, _, _ = await PhonePolicyService(db).load_endpoint(
        row.endpoint_id, organization_id=row.organization_id
    )
    if endpoint.generation != row.endpoint_generation or row.status != "active":
        return []
    choices: list[PhoneChoice] = []
    for value in endpoint.transfer_contact_ids:
        target = await repo.contact_by_id(db, UUID(value), organization_id=row.organization_id)
        if target is None:
            continue
        try:
            await PhonePolicyService(db).available_contact(
                target, mode="transfer", reserved_call_id=row.id
            )
        except AppException:
            continue
        person = await user_repo.get_by_id(db, target.user_id)
        if person is not None:
            choices.append(PhoneChoice(id=target.id, label=person.full_name or "Phone contact"))
    return choices
