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
    AnswerFrame,
    ApprovalFrame,
    ApprovalSettledFrame,
    ApprovalUnavailableFrame,
    ClientFrame,
    EndedFrame,
    EndFrame,
    LimitFrame,
    MuteFrame,
    NoticeFrame,
    PlayedFrame,
    ReadyFrame,
    ServerFrame,
    StartFrame,
    StateFrame,
    ToolFrame,
    TurnSavedFrame,
)
from app.services.access import AGENT, publisher_context, resolve_access
from app.services.embed_session import visible_frames
from app.services.voice import limits
from app.services.voice.exceptions import VoiceRefused
from app.services.voice.hangup import HangUpTarget, hang_up
from app.services.voice.limits import HEARTBEAT_SECONDS
from app.services.voice.pump import EventPump
from app.services.voice.registry import LIVE_CALLS
from app.services.voice.relay import AudioRelay
from app.services.voice.seed import seed_history, summariser
from app.services.voice.settings import VoiceSettingsService, agent_takes_calls, voice_switched_on
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

# The reason is stated in words a visitor may hear: on a public page "budget"
# would say more about the organization than the visitor needs to know. The
# notice frame names the reason by its code, which the visitor's page turns into
# copy of its own (the widget's and the hosted page's say only that calls are
# not available).
NOTICES: dict[VoiceEndReason, str] = {
    VoiceEndReason.TIME_LIMIT: "In one short sentence, tell the person the call is ending now and why: it has reached its time limit.",
    VoiceEndReason.BUDGET: "In one short sentence, tell the person the call is ending now and why: calls with you are not available right now.",
    VoiceEndReason.MINUTES: "In one short sentence, tell the person the call is ending now and why: this month's call minutes are used up.",
}

VISITOR_UNAVAILABLE = "Calls are not available right now."
"""What a visitor refused for one of `_OPERATORS_REASONS` is told instead of the reason's words."""

_OPERATORS_REASONS = frozenset({"not_configured", "not_priced", "minutes_exhausted", "budget"})
"""Refusals whose words are written for whoever runs the agent: its Voice card, its
model's price, the organization's minutes and budget. Not a visitor's to read."""

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
    voice switch on, and still on this agent - pausing the page, switching calls
    off or pointing it at another agent ends calls on it - and runs under the publisher's role as it stands now (`publisher_context`).
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
        if (
            embed is None
            or not embed.is_active
            or not embed.config.get("voice_conversation")
            # Pointed at another agent since: the page no longer offers this one.
            or embed.agent_id != agent_id
        ):
            return None
        # Re-derived as a text turn derives it, so a publisher deactivated or
        # demoted mid-call stops lending the call their role.
        ctx = await publisher_context(
            db, organization_id=organization_id, publisher_user_id=embed.owner_user_id
        )
    agent = await agent_repo.get(db, agent_id, organization_id=organization_id)
    if agent is None or not agent_takes_calls(agent):
        return None
    if not await resolve_access(db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT):
        return None
    organization = await organization_repo.get_by_id(db, organization_id)
    if not voice_switched_on(organization, caller.surface):
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


def _visible(frame: ServerFrame, shows: frozenset[str]) -> ServerFrame | None:
    """A frame as an embed's operator agreed to show it, or `None` when it is not sent.

    The text embed's switches (`visible_frames`), read the same way: without tool
    steps a visitor is not told a tool ran, nor its name; without tool results a
    step does not open into what it was called with or what came back - raw
    output is the most likely thing to carry something internal. A saved turn
    keeps its words either way.
    """
    steps = "tool_call" in shows
    details = "tool_result" in shows
    if isinstance(frame, ToolFrame):
        return frame if steps else None
    if isinstance(frame, StateFrame) and frame.state == "tool_running" and not steps:
        return StateFrame(type="state", state="thinking")
    if isinstance(frame, ApprovalUnavailableFrame) and not details:
        return frame.model_copy(update={"args": {}})
    if isinstance(frame, TurnSavedFrame) and not details:
        message = dict(frame.message)
        calls = message.get("tool_calls")
        parts = message.get("parts")
        message["tool_calls"] = (
            [{**call, "args": {}, "result": None} for call in calls if isinstance(call, dict)]
            if steps and isinstance(calls, list)
            else []
        )
        if not steps and isinstance(parts, list):
            message["parts"] = [
                part
                for part in parts
                if not (isinstance(part, dict) and part.get("type") == "tool")
            ]
        return frame.model_copy(update={"message": message})
    return frame


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
        # `time.monotonic()` when the call was ready: the origin of its cap, its
        # seconds and its metered time, as the row's `started_at` is of its
        # minutes. None while it is set up, which counts toward none of them.
        self._started_at: float | None = None
        # A visitor sees what the embed's operator agreed to show (`_visible`); a
        # member on the console sees every frame. Read once, at admission, as the
        # text embed reads it.
        self._shows: frozenset[str] | None = None
        if caller.surface == "embed" or caller.anonymous:
            self._shows = frozenset() if caller.embed is None else visible_frames(caller.embed)

    async def _send(self, frame: ServerFrame) -> None:
        shown = frame if self._shows is None else _visible(frame, self._shows)
        if shown is not None:
            await send_frame(self._ws, shown)

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
                await self._send(EndedFrame(type="ended", reason="no_start"))
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
                    message = refused.message
                    if self._caller.anonymous and refused.reason in _OPERATORS_REASONS:
                        message = VISITOR_UNAVAILABLE
                    await self._send(
                        EndedFrame(type="ended", reason=refused.reason, message=message)
                    )
                    return
                except AppException as failed:
                    # Not a refusal with words of its own (a key that cannot be
                    # unsealed, a run that cannot be prepared): its message is
                    # not written for the caller, so it is logged, not sent.
                    logger.warning("voice_call_not_started", extra={"error": failed.message})
                    await self._send(
                        EndedFrame(
                            type="ended", reason="error", message="The call could not be started."
                        )
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
            # Setup can outlast the sweep's patience - a summary of a long thread
            # is a model call - and the call's own heartbeat has not started, so
            # the row is beaten for meanwhile, as a live call's is.
            answer = None
            async with anyio.create_task_group() as setup:
                setup.start_soon(self._keep_alive, started)
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
                if started.resolved.entry.transport == "webrtc":
                    answer = await started.prepared.answer_offer(realtime, frame.sdp_offer or "")
                    provider_call_id = answer.session.call_id
                    async with self._sessions() as own:
                        await voice_call_repo.set_provider_call_id(
                            own, started.call_id, provider_call_id=provider_call_id
                        )
                setup.cancel_scope.cancel()
            provider_session = None
            if answer is not None:
                await self._send(AnswerFrame(type="answer", sdp=answer.sdp))
                provider_session = answer.session
            ready = ReadyFrame(
                type="ready",
                call_id=started.call_id,
                conversation_id=started.conversation_id,
                transport=started.resolved.entry.transport,
                input_sample_rate=started.resolved.entry.input_sample_rate,
                output_sample_rate=started.resolved.entry.output_sample_rate,
                cap_seconds=started.shown_cap_seconds,
                minutes_left=started.minutes_left,
                resume_token=started.resume_token,
            )
            if not self._caller.anonymous:
                # Not a visitor's: nothing on a public page reads it, and a text
                # embed does not send it either.
                ready.run_id = started.prepared.run.id
            # The call's clock starts here, as its caller's timer does on `ready`.
            at, clock = datetime.now(UTC), time.monotonic()
            async with self._sessions() as own:
                await voice_call_repo.start_clock(own, started.call_id, at=at)
            self._started_at = clock
            await self._send(ready)
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
            await self._send(
                ApprovalSettledFrame(type="approval_settled", id=frame.id, outcome="expired")
            )

    async def _heartbeat(
        self, started: StartedCall, pump: EventPump, session: RealtimeSession
    ) -> None:
        while True:
            await anyio.sleep(self._heartbeat_seconds)
            started.meter.book_elapsed(self._elapsed())
            async with self._sessions() as db:
                await self._beat(db, started)
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

    async def _keep_alive(self, started: StartedCall) -> None:
        """Beat for the row while the call is set up, until setup cancels it."""
        while True:
            await anyio.sleep(self._heartbeat_seconds)
            async with self._sessions() as own:
                await self._beat(own, started)

    async def _beat(self, db: AsyncSession, started: StartedCall) -> None:
        """Prove the call alive, with its seconds and spend so far."""
        at = datetime.now(UTC)
        if self._started_at is None:
            # Still being set up: its clock has not started, so its start moves
            # with the beat, and a sweep ending it here counts no minutes.
            await voice_call_repo.start_clock(db, started.call_id, at=at)
        await voice_call_repo.heartbeat(
            db,
            started.call_id,
            at=at,
            cost_usd=started.meter.total_usd,
            seconds=int(self._elapsed()),
        )
        # On the run too: every other run's budget baseline sums the runs' cost,
        # and would not see this call's until it ended.
        await agent_run_repo.record_live_cost(
            db, run_id=started.prepared.run.id, cost_usd=started.meter.total_usd
        )

    def _elapsed(self) -> float:
        """Seconds since the call was ready: none while it is set up."""
        return 0.0 if self._started_at is None else time.monotonic() - self._started_at

    def _default_reauthorize(self, started: StartedCall) -> Reauthorize:
        async def check(db: AsyncSession) -> AuthContext | None:
            return await still_allowed(db, self._caller, agent_id=started.prepared.agent.id)

        return check

    async def _cap(self, started: StartedCall, pump: EventPump, session: RealtimeSession) -> None:
        """End the call at its cap, as whichever limit set it: its time, or the month's minutes.

        A visitor whose call the minutes cut short is not warned a minute ahead:
        the warning would time the organization's remaining minutes for them.
        """
        reason = started.cap_reason
        left = started.cap_seconds - self._elapsed()
        warn_at = left - limits.WARN_SECONDS
        if warn_at > 0 and (reason is VoiceEndReason.TIME_LIMIT or not self._caller.anonymous):
            await anyio.sleep(warn_at)
            await self._send(LimitFrame(type="limit", seconds_left=limits.WARN_SECONDS))
            await anyio.sleep(limits.WARN_SECONDS)
        else:
            await anyio.sleep(max(left, 0))
        await self._end_with_notice(pump, session, reason)

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
        await self._send(NoticeFrame(type="notice", kind=reason.value))
        try:
            # Armed before the notice is asked for: set when the agent stops
            # speaking after the notice's own response, not an earlier answer's.
            done = pump.arm_output_done()
            try:
                await session.send(self._notice(reason), respond=True)
            except UsageLimitExceeded:
                # The cost limit is spent, so the notice cannot be said: the call
                # ends on the budget, which is what spent it.
                self.request_end(VoiceEndReason.BUDGET)
                return
            with anyio.move_on_after(self._notice_seconds):
                await done.wait()
        finally:
            self.request_end(reason)

    def _notice(self, reason: VoiceEndReason) -> str:
        """What the agent is asked to say. A visitor hears the month's minutes as calls not
        being available, as on the hosted page: the allowance is not theirs to know."""
        if self._caller.anonymous and reason is VoiceEndReason.MINUTES:
            return NOTICES[VoiceEndReason.BUDGET]
        return NOTICES[reason]

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
        elapsed = self._elapsed()
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
                if self._started_at is None:
                    # Never ready, so it lasted no time: on the minutes as in its seconds.
                    await voice_call_repo.start_clock(own, started.call_id, at=now)
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
            # `finish` writes whatever is still parked on the run's channel as
            # pending, on this session; the call that would have decided it is over.
            await agent_run_repo.expire_pending_approvals(
                db, run_id=started.prepared.run.id, decided_at=now
            )
            await db.commit()
        except Exception:
            logger.exception("voice_run_finish_failed", extra={"call_id": call_id})
        ended = EndedFrame(type="ended", reason=reason.value)
        if self._message is not None:
            ended.message = self._message
        await self._send(ended)
