"""One call, for exactly as long as its socket is open (#54).

The socket's lifetime is the call's lifetime on our side: four tasks in one
anyio task group - the event pump, the socket reader, the heartbeat and the time
cap - and nothing outlives the group. A relay call's audio rides on two of them:
the socket reader passes the caller's to the provider, the pump forwards the
agent's in event order. Every way out (the caller's `end`, the socket gone, a
limit, an error, a revocation, a shutdown, a cancellation) goes through one
shielded `finally`, which records the call row's end, then hangs the provider
call up - the end first, so a reconnect waiting on it does not also wait out
the hang-up - then finishes the run (spend recorded on every path) and commits:
the terminal commit of the run path (amendment 5).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import anyio
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.realtime import RealtimeSession
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, AuthenticationError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import RunStatus
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.voice_call import VoiceEndReason
from app.db.session import get_db_context
from app.repositories import (
    agent_embed_repo,
    agent_repo,
    agent_run_repo,
    member_repo,
    voice_call_repo,
)
from app.repositories import organization as organization_repo
from app.schemas.voice import (
    ApprovalFrame,
    ClientFrame,
    EndFrame,
    MuteFrame,
    PlayedFrame,
    StartFrame,
)
from app.services.access import AGENT, publisher_context, resolve_access
from app.services.voice import limits
from app.services.voice.exceptions import VoiceRefused
from app.services.voice.hangup import HangUpTarget, hang_up
from app.services.voice.limits import HEARTBEAT_SECONDS
from app.services.voice.pump import EventPump
from app.services.voice.registry import LIVE_CALLS
from app.services.voice.relay import AudioRelay
from app.services.voice.seed import seed_history, summariser
from app.services.voice.settings import VoiceSettingsService
from app.services.voice.starter import StartedCall, VoiceCaller, VoiceCallStarter
from app.services.voice.transcript import SessionFactory
from app.services.voice.transport import send_audio_frame, send_frame
from app.services.ws_auth import authenticate_socket_token

logger = logging.getLogger(__name__)

Reauthorize = Callable[[AsyncSession], Awaitable[AuthContext | None]]
"""A heartbeat's re-check: the caller's context as it stands now, or `None` to end the call."""

_FRAMES: TypeAdapter[ClientFrame] = TypeAdapter(ClientFrame)

FLOODED = "The call's audio arrived far faster than anyone can speak, so it was ended."
"""Why a relay call whose audio was not a microphone's ended. Stored as an `error`
end: a reason of its own would need the `voice_calls` CHECK constraint widened."""

NOTICE_WAIT_SECONDS = 8.0
"""How long a spoken limit notice may take before the call is ended anyway."""

NOTICES: dict[VoiceEndReason, str] = {
    VoiceEndReason.TIME_LIMIT: "The call has reached its time limit. In one short sentence, tell the person the call is ending now.",
    VoiceEndReason.BUDGET: "The budget for this agent has run out. In one short sentence, tell the person the call is ending now.",
    VoiceEndReason.MINUTES: "This organization's call minutes for the month are used up. In one short sentence, tell the person the call is ending now.",
}

_STATUS = {
    VoiceEndReason.USER: RunStatus.COMPLETED,
    VoiceEndReason.TIME_LIMIT: RunStatus.COMPLETED,
    VoiceEndReason.MINUTES: RunStatus.COMPLETED,
    VoiceEndReason.GUARDRAIL: RunStatus.COMPLETED,
    VoiceEndReason.BUDGET: RunStatus.BUDGET_EXCEEDED,
    VoiceEndReason.DISCONNECTED: RunStatus.CANCELLED,
    VoiceEndReason.REVOKED: RunStatus.CANCELLED,
    VoiceEndReason.SHUTDOWN: RunStatus.CANCELLED,
    VoiceEndReason.REAPED: RunStatus.FAILED,
    VoiceEndReason.ERROR: RunStatus.FAILED,
}


async def still_allowed(
    db: AsyncSession, caller: VoiceCaller, *, agent_id: UUID
) -> AuthContext | None:
    """The caller's context as it stands now, or `None` when the call may not go on (amendment 11).

    Re-read on every heartbeat rather than trusted from the start: the session
    token (revoked by signing out), the membership and its *current* role, the
    caller's run access to the agent (a grant may have been withdrawn), the
    agent's published state, and the organization's voice switches - the `/chat`
    one too, for a call from the console. The role comes back in the context, so
    the call can stop taking approvals from somebody who lost `approvals:decide`.
    A visitor's call from an embed also needs that embed still active with its
    voice switch on - pausing the page or switching calls off ends calls on it -
    and runs under the publisher's role as it stands now (`publisher_context`).
    """
    if caller.auth_token is not None:
        try:
            await authenticate_socket_token(db, caller.auth_token, allow_expired=True)
        except AuthenticationError:
            return None
    organization_id = caller.ctx.organization_id
    ctx = caller.ctx
    if caller.user_id is not None and not caller.anonymous:
        membership = await member_repo.get(
            db, organization_id=organization_id, user_id=caller.user_id
        )
        if membership is None:
            return None
        ctx = AuthContext(
            user_id=caller.user_id,
            organization_id=organization_id,
            role=membership.role,
            is_app_admin=caller.ctx.is_app_admin,
        )
    if caller.embed_id is not None:
        embed = await agent_embed_repo.get(db, caller.embed_id, organization_id=organization_id)
        if embed is None or not embed.is_active or not embed.config.get("voice_conversation"):
            return None
        # Re-derived as a text turn derives it, so a publisher deactivated or
        # demoted mid-call stops lending the call their role.
        ctx = await publisher_context(
            db, organization_id=organization_id, publisher_user_id=embed.owner_user_id
        )
    agent = await agent_repo.get(db, agent_id, organization_id=organization_id)
    if (
        agent is None
        or agent.current_version_id is None
        or agent.status == AgentStatus.ARCHIVED.value
    ):
        return None
    if not await resolve_access(db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT):
        return None
    organization = await organization_repo.get_by_id(db, organization_id)
    if (
        organization is None
        or not organization.voice_conversations_enabled
        or (caller.surface == "web" and not organization.voice_in_chat)
    ):
        return None
    return ctx


async def socket_caller(
    user: User, organization: Organization, *, auth_token: str
) -> VoiceCaller | None:
    """The person a console voice socket carries, or `None` when they are no longer a member.

    `ActiveOrgWS` checked membership at the handshake but returns no role, and a
    call's approvals depend on the role; read here, in the service, because a
    route may not reach a repository.
    """
    async with get_db_context() as db:
        membership = await member_repo.get(db, organization_id=organization.id, user_id=user.id)
    if membership is None:
        return None
    return VoiceCaller(
        # The same context `deps.get_auth_context` builds, app-admin flag included.
        ctx=AuthContext(
            user_id=user.id,
            organization_id=organization.id,
            role=membership.role,
            is_app_admin=user.is_app_admin,
        ),
        user_id=user.id,
        user_name=user.full_name,
        surface="web",
        anonymous=False,
        auth_token=auth_token,
        embed_id=None,
        agent_id=None,
        conversation_id=None,
    )


class VoiceCallSession:
    """One call over one socket: start, live, and a teardown that always hangs up."""

    def __init__(
        self,
        websocket: WebSocket,
        caller: VoiceCaller,
        *,
        sessions: SessionFactory = get_db_context,
        reauthorize: Reauthorize | None = None,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
        first_frame_seconds: float = 10.0,
        notice_seconds: float = NOTICE_WAIT_SECONDS,
    ) -> None:
        self._ws = websocket
        self._notice_seconds = notice_seconds
        self._caller = caller
        self._sessions = sessions
        self._reauthorize = reauthorize
        self._heartbeat_seconds = heartbeat_seconds
        self._first_frame_seconds = first_frame_seconds
        self._reason: VoiceEndReason | None = None
        self._message: str | None = None
        self._scope: anyio.CancelScope | None = None
        self._closed = anyio.Event()
        self._pump: EventPump | None = None
        self._session: RealtimeSession | None = None
        self._group: anyio.abc.TaskGroup | None = None
        self._noticing = False
        self._started_at = time.monotonic()

    async def _send(self, kind: str, payload: dict[str, object]) -> None:
        await send_frame(self._ws, kind, payload)

    def request_end(self, reason: VoiceEndReason, *, message: str | None = None) -> None:
        """End the call for `reason`. The first reason wins; the teardown does the rest.

        `message` says why in words, for a reason too broad to (an `error` that
        is the caller's doing rather than ours); it goes with the first reason.
        """
        if self._reason is None:
            self._reason = reason
            self._message = message
        if self._scope is not None:
            self._scope.cancel()

    async def closed(self) -> None:
        """Return once the call has finished its teardown."""
        await self._closed.wait()

    async def _receive(self) -> ClientFrame | bytes | None:
        """The next frame: a client frame, the caller's audio (binary), or `None` for noise."""
        message = await self._ws.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        text = message.get("text")
        if text is None:
            audio = message.get("bytes")
            return audio if isinstance(audio, bytes) else None
        try:
            return _FRAMES.validate_python(json.loads(text))
        except (ValidationError, ValueError):
            return None

    async def run(self) -> None:
        """Hold the call from its `start` frame to its teardown; returns when it is over."""
        LIVE_CALLS.add(self)
        frame: ClientFrame | bytes | None = None
        try:
            with anyio.move_on_after(self._first_frame_seconds) as waited:
                frame = await self._receive()
            if waited.cancelled_caught or not isinstance(frame, StartFrame):
                await self._send("ended", {"reason": "no_start"})
                return
            async with self._sessions() as db:
                starter = VoiceCallStarter(
                    db,
                    sessions=self._sessions,
                    send=self._send,
                    heard=lambda: None if self._pump is None else self._pump.heard,
                )
                try:
                    started = await starter.start(self._caller, frame)
                except VoiceRefused as refused:
                    await self._send(
                        "ended", {"reason": refused.reason, "message": refused.message}
                    )
                    return
                await self._live(db, started, frame)
        except WebSocketDisconnect:
            return
        finally:
            LIVE_CALLS.discard(self)
            self._closed.set()

    async def _live(self, db: AsyncSession, started: StartedCall, frame: StartFrame) -> None:
        provider_call_id: str | None = None
        error: str | None = None
        self._started_at = time.monotonic()
        entry = started.resolved.entry
        relay = (
            AudioRelay(
                send_bytes=lambda data: send_audio_frame(self._ws, data),
                send=self._send,
                input_sample_rate=entry.input_sample_rate,
                output_sample_rate=entry.output_sample_rate,
            )
            if entry.transport == "relay"
            else None
        )
        pump = self._pump = EventPump(started=started, send=self._send, relay=relay)
        LIVE_CALLS.bind(started.call_id, self)
        try:
            # After the first commit, so inside this `try`: a failure here still
            # finishes the run, ends the row and tells the client (review fix 6).
            async with self._sessions() as own:
                history = await seed_history(
                    own,
                    conversation_id=started.conversation_id,
                    context_window=started.resolved.entry.context_window,
                    summarise=summariser(started.prepared),
                )
            realtime = started.prepared.realtime(
                started.model,
                settings=started.settings,
                message_history=history,
                cost_limit=started.cost_limit,
            )
            provider_session = None
            if started.resolved.entry.transport == "webrtc":
                answer = await started.prepared.answer_offer(realtime, frame.sdp_offer or "")
                provider_call_id = answer.session.call_id
                async with self._sessions() as own:
                    await voice_call_repo.set_provider_call_id(
                        own, started.call_id, provider_call_id=provider_call_id
                    )
                await self._send("answer", {"sdp": answer.sdp})
                provider_session = answer.session
            await self._send(
                "ready",
                {
                    "call_id": str(started.call_id),
                    "run_id": str(started.prepared.run.id),
                    "conversation_id": str(started.conversation_id),
                    "transport": started.resolved.entry.transport,
                    "input_sample_rate": started.resolved.entry.input_sample_rate,
                    "output_sample_rate": started.resolved.entry.output_sample_rate,
                    "cap_seconds": started.cap_seconds,
                    "minutes_left": started.minutes_left,
                },
            )
            async with (
                started.prepared.realtime_session(
                    realtime, provider_session=provider_session
                ) as session,
                anyio.create_task_group() as group,
            ):
                self._scope = group.cancel_scope
                self._session = session
                started.meter.attach(session.usage)
                self._group = group
                if self._reason is not None:
                    group.cancel_scope.cancel()
                group.start_soon(self._events, pump, session)
                group.start_soon(self._socket, started, session, relay)
                group.start_soon(self._heartbeat, started, pump, session)
                group.start_soon(self._cap, started, pump, session)
        except anyio.get_cancelled_exc_class():
            # Cancelled from outside - a shutdown the registry did not reach first.
            self._reason = self._reason or VoiceEndReason.SHUTDOWN
            raise
        except Exception:
            logger.exception("voice_call_failed", extra={"call_id": str(started.call_id)})
            self._reason = self._reason or VoiceEndReason.ERROR
            error = "The call failed."
        finally:
            with anyio.CancelScope(shield=True):
                await self._teardown(db, started, pump, provider_call_id, error)

    async def _events(self, pump: EventPump, session: RealtimeSession) -> None:
        try:
            async for event in session:
                await pump.handle(event, session)
                if pump.budget_exhausted and self._group is not None and not self._noticing:
                    # Beside the pump, not inside it: the notice waits for the agent
                    # to stop speaking, which only this loop can see.
                    self._group.start_soon(
                        self._end_with_notice, pump, session, VoiceEndReason.BUDGET
                    )
        except UsageLimitExceeded:
            # The hard stop under the per-response check: caught here, inside the
            # group, because a task group re-raises it wrapped in an ExceptionGroup.
            self.request_end(VoiceEndReason.BUDGET)
            return
        self.request_end(VoiceEndReason.ERROR)

    async def _socket(
        self, started: StartedCall, session: RealtimeSession, relay: AudioRelay | None
    ) -> None:
        """Read the caller's frames until they hang up or the socket goes.

        Over WebRTC the browser mutes its own track and the audio never passes
        here, so mute, `played` and binary frames are the relay's. Push-to-talk
        is the browser's alone on both transports: a disabled track is silence.
        """
        while True:
            try:
                frame = await self._receive()
            except WebSocketDisconnect:
                self.request_end(VoiceEndReason.DISCONNECTED)
                return
            if isinstance(frame, EndFrame):
                self.request_end(VoiceEndReason.USER)
                return
            if isinstance(frame, ApprovalFrame):
                await self._decide(started, frame)
            elif relay is None:
                continue
            elif isinstance(frame, bytes):
                if not await relay.inbound(session, frame):
                    self.request_end(VoiceEndReason.ERROR, message=FLOODED)
                    return
            elif isinstance(frame, PlayedFrame):
                relay.heard(frame.bytes)
            elif isinstance(frame, MuteFrame):
                relay.mute(frame.muted)

    async def _decide(self, started: StartedCall, frame: ApprovalFrame) -> None:
        """Hand a decision to the call's bridge; one it cannot take is answered, not fatal.

        A decision that lost to the 60-second timeout, or for an approval the call
        is not waiting on, is told as `expired` so the card closes - the call goes on.
        """
        try:
            decided = await started.bridge.decide(frame.id, approve=frame.decision == "approve")
        except AppException:
            logger.info("voice_approval_not_decided", extra={"call_id": str(started.call_id)})
            decided = False
        if not decided:
            await self._send("approval_settled", {"id": frame.id, "outcome": "expired"})

    async def _heartbeat(
        self, started: StartedCall, pump: EventPump, session: RealtimeSession
    ) -> None:
        while True:
            await anyio.sleep(self._heartbeat_seconds)
            elapsed = time.monotonic() - self._started_at
            started.meter.book_elapsed(elapsed)
            async with self._sessions() as db:
                await voice_call_repo.heartbeat(
                    db,
                    started.call_id,
                    at=datetime.now(UTC),
                    cost_usd=started.meter.total_usd,
                    seconds=int(elapsed),
                )
                now_ctx = await (self._reauthorize or self._default_reauthorize(started))(db)
                if now_ctx is None:
                    self.request_end(VoiceEndReason.REVOKED)
                    return
                started.bridge.refresh_decider(
                    now_ctx
                    if not self._caller.anonymous and now_ctx.has(Perm.APPROVALS_DECIDE)
                    else None
                )
                own_row = await voice_call_repo.get(
                    db, started.call_id, organization_id=self._caller.ctx.organization_id
                )
                if own_row is not None and own_row.ended_at is not None:
                    # A reconnect on another worker ended this half-open connection (Task 17).
                    self.request_end(VoiceEndReason.DISCONNECTED)
                    return
                organization = await organization_repo.get_by_id(
                    db, self._caller.ctx.organization_id
                )
                left = (
                    None
                    if organization is None
                    else await VoiceSettingsService(db).minutes_left_seconds(organization)
                )
            if left is not None and left <= 0:
                await self._end_with_notice(pump, session, VoiceEndReason.MINUTES)
                return
            budget = started.prepared.built.budget
            # Other runs spend while a call lasts; re-read their spend each heartbeat
            # rather than trusting the figure read when the call began.
            budget.refresh_baselines()
            if not await budget.can_afford_next_request():
                await self._end_with_notice(pump, session, VoiceEndReason.BUDGET)
                return

    def _default_reauthorize(self, started: StartedCall) -> Reauthorize:
        async def check(db: AsyncSession) -> AuthContext | None:
            return await still_allowed(db, self._caller, agent_id=started.prepared.agent.id)

        return check

    async def _cap(self, started: StartedCall, pump: EventPump, session: RealtimeSession) -> None:
        warn_at = started.cap_seconds - limits.WARN_SECONDS
        if warn_at > 0:
            await anyio.sleep(warn_at)
            await self._send("limit", {"seconds_left": limits.WARN_SECONDS})
            await anyio.sleep(limits.WARN_SECONDS)
        else:
            await anyio.sleep(max(started.cap_seconds, 0))
        await self._end_with_notice(pump, session, VoiceEndReason.TIME_LIMIT)

    async def _end_with_notice(
        self, pump: EventPump, session: RealtimeSession, reason: VoiceEndReason
    ) -> None:
        """Let the agent say one sentence about why, then end (spec §4.4).

        One notice per call: a second limit reached while the first is being
        said ends the call with the first's reason.
        """
        if self._noticing:
            return
        self._noticing = True
        await self._send("notice", {"kind": reason.value})
        try:
            # A fresh event, set by the pump when the agent next stops speaking:
            # the notice's own sentence, not an earlier answer's end.
            pump.output_done = anyio.Event()
            try:
                await session.send(NOTICES[reason], respond=True)
            except UsageLimitExceeded:
                # The cost limit is spent, so the notice cannot be said: the call
                # ends on the budget, which is what spent it.
                self.request_end(VoiceEndReason.BUDGET)
                return
            with anyio.move_on_after(self._notice_seconds):
                await pump.output_done.wait()
        finally:
            self.request_end(reason)

    async def _teardown(
        self,
        db: AsyncSession,
        started: StartedCall,
        pump: EventPump,
        provider_call_id: str | None,
        error: str | None,
    ) -> None:
        reason = self._reason or VoiceEndReason.ERROR
        call_id = str(started.call_id)
        elapsed = time.monotonic() - self._started_at
        try:
            started.meter.book_elapsed(elapsed)
            if self._session is not None:
                # A response cut off by the end never completed, so it was never
                # booked: the session's running total still holds it.
                started.meter.book_response(self._session.usage)
        except Exception:
            logger.exception("voice_final_booking_failed", extra={"call_id": call_id})
        now = datetime.now(UTC)
        try:
            # The row's end first: a reconnect on this worker waits for it, and must
            # not wait out the provider's hang-up as well.
            async with self._sessions() as own:
                await voice_call_repo.end(
                    own,
                    started.call_id,
                    at=now,
                    reason=reason,
                    cost_usd=started.meter.total_usd,
                    seconds=int(elapsed),
                    guardrail_hits=started.guard.hits,
                )
        except Exception:
            logger.exception("voice_call_row_end_failed", extra={"call_id": call_id})
        hung = False
        try:
            hung = await hang_up(
                HangUpTarget(
                    transport=started.resolved.entry.transport,
                    provider=started.resolved.provider,
                    provider_call_id=provider_call_id,
                    secret=started.secret,
                )
            )
        except Exception:
            logger.exception("voice_hangup_crashed", extra={"call_id": call_id})
        try:
            await pump.flush()
        except Exception:
            logger.exception("voice_flush_failed", extra={"call_id": call_id})
        try:
            async with self._sessions() as own:
                if hung:
                    await voice_call_repo.mark_hung_up(own, started.call_id, at=now)
                # A bridge that could not expire its own approval (the call ended
                # mid-write) must not leave it pending for ever.
                await agent_run_repo.expire_pending_approvals(
                    own, run_id=started.prepared.run.id, decided_at=now
                )
        except Exception:
            logger.exception("voice_call_row_close_failed", extra={"call_id": call_id})
        try:
            await started.runner.finish(
                started.prepared, status=_STATUS[reason], error=error or self._message
            )
            await db.commit()
        except Exception:
            logger.exception("voice_run_finish_failed", extra={"call_id": call_id})
        ended: dict[str, object] = {"reason": reason.value}
        if self._message is not None:
            ended["message"] = self._message
        await self._send("ended", ended)
