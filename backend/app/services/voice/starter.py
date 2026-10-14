"""Starting a call: every refusal before anything is spent (#54).

In order, and each refusal rolls back whatever was flushed: the organization's
switch, the agent and the caller's access to it, the Voice section, the
conversation's ownership, the resume rules, the month's minutes, the key, a
price that can be computed, the budget against the call's worst case, and the
caller's concurrent calls. Then the call row and the run are committed - the
first commit of the call (amendment 5) - so approval rows, heartbeats and the
reaper can see them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

import anyio
from pydantic_ai.realtime import RealtimeModel, RealtimeModelSettings
from pydantic_ai.usage import RequestUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import price_request
from app.agents.realtime import build_realtime_model, realtime_settings
from app.agents.voice import VoiceOptions, thinking_effort
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import StorableSecret
from app.db.locks import LockScope, hold_subject
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.voice_call import VoiceCall, VoiceEndReason
from app.repositories import agent_run_repo, conversation_repo, voice_call_repo
from app.repositories import organization as organization_repo
from app.schemas.voice import StartFrame
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService, PreparedRun, VoiceRun
from app.services.conversation import ConversationService
from app.services.organization_secret import OrganizationSecretService
from app.services.voice import limits
from app.services.voice.approvals import SendFrame, VoiceApprovalBridge
from app.services.voice.exceptions import VoiceRefused
from app.services.voice.guard import TranscriptGuard
from app.services.voice.hangup import hang_up_row
from app.services.voice.meter import UsageMeter
from app.services.voice.registry import LIVE_CALLS, WORKER_ID
from app.services.voice.settings import ResolvedVoice, VoiceSettingsService, resolve_voice
from app.services.voice.transcript import SessionFactory, TurnWriter
from app.services.voice.transport import refuse_data_channel


@dataclass(frozen=True)
class VoiceCaller:
    """Who is on the call, as the socket that admitted them established it."""

    ctx: AuthContext
    user_id: UUID | None
    user_name: str | None
    surface: Literal["web", "embed"]
    anonymous: bool
    auth_token: str | None
    embed_id: UUID | None
    agent_id: UUID | None
    conversation_id: UUID | None


@dataclass
class StartedCall:
    """A committed call: its row, its run, and everything the session needs to hold it."""

    call_id: UUID
    prepared: PreparedRun
    resolved: ResolvedVoice
    secret: StorableSecret
    settings: RealtimeModelSettings
    model: RealtimeModel
    cost_limit: Decimal | None
    cap_seconds: int
    minutes_left: int | None
    conversation_id: UUID
    bridge: VoiceApprovalBridge
    guard: TranscriptGuard
    meter: UsageMeter
    writer: TurnWriter
    runner: AgentRunnerService


class VoiceCallStarter:
    """Turns a `start` frame into a committed call, or a refusal with a reason."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        sessions: SessionFactory,
        send: SendFrame,
        heard: Callable[[], str | None],
    ) -> None:
        self.db = db
        self._sessions = sessions
        self._send = send
        self._heard = heard

    async def start(self, caller: VoiceCaller, frame: StartFrame) -> StartedCall:
        """Check every refusal, open the run and the call row, and commit both.

        Raises:
            VoiceRefused: With a stable `reason`; whatever was flushed is rolled back.
        """
        try:
            return await self._start(caller, frame)
        except VoiceRefused:
            await self.db.rollback()
            raise

    async def _start(self, caller: VoiceCaller, frame: StartFrame) -> StartedCall:
        ctx = caller.ctx
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if (
            organization is None
            or not organization.voice_conversations_enabled
            or (caller.surface == "web" and not organization.voice_in_chat)
        ):
            raise VoiceRefused("voice_off", "Voice conversations are switched off here.")
        agent_id = caller.agent_id or frame.agent_id
        if agent_id is None:
            raise VoiceRefused("no_agent", "Pick an agent to call.")
        try:
            agent = await AgentRegistryService(self.db).get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        except (NotFoundError, AuthorizationError):
            raise VoiceRefused("forbidden", "This agent cannot take your call.") from None
        voice_settings = VoiceSettingsService(self.db)
        spec = await voice_settings.published_spec(agent)
        resolved = resolve_voice(None if spec is None else spec.voice)
        if spec is None or resolved is None:
            raise VoiceRefused("not_configured", "This agent is not set up for calls.")
        if resolved.entry.transport == "webrtc":
            if frame.sdp_offer is None:
                raise VoiceRefused("bad_offer", "The call could not be set up.")
            refuse_data_channel(frame.sdp_offer)

        conversation_id = await self._conversation(
            caller, frame, organization_id=ctx.organization_id
        )
        chain_elapsed = await self._resume(
            caller, frame, agent_id=agent.id, conversation_id=conversation_id
        )
        left = await voice_settings.minutes_left_seconds(organization)
        cap = limits.call_cap_seconds(
            org_max=organization.voice_max_call_seconds,
            agent_max=resolved.max_call_seconds,
            chain_elapsed=chain_elapsed,
            minutes_left=left,
        )
        if cap < limits.MIN_CALL_SECONDS:
            if left is not None and left < limits.MIN_CALL_SECONDS:
                raise VoiceRefused(
                    "minutes_exhausted", "This organization has no call minutes left this month."
                )
            # A reconnect whose call has used its longest time already.
            raise VoiceRefused("call_limit", "This call has reached its time limit.")

        secrets = await OrganizationSecretService(self.db).resolve_for_bindings(
            ctx, [resolved.secret_id]
        )
        secret = secrets.get(resolved.secret_id)
        if secret is None:
            raise VoiceRefused(
                "not_configured",
                "This agent's voice key is gone. Choose another on its Voice card.",
            )
        price_provider = "openai" if resolved.provider == "azure" else resolved.provider
        if (
            resolved.entry.pricing.kind == "tokens"
            and price_request(
                RequestUsage(input_tokens=1000, output_tokens=1000), resolved.model, price_provider
            )
            is None
        ):
            raise VoiceRefused(
                "not_priced", "This model's price is unknown, so its budget could not be enforced."
            )

        bridge = VoiceApprovalBridge(
            sessions=self._sessions,
            decider=ctx if (not caller.anonymous and ctx.has(Perm.APPROVALS_DECIDE)) else None,
            send=self._send,
            heard=self._heard,
        )
        runner = AgentRunnerService(self.db)
        prepared = await runner.prepare(
            ctx,
            agent.id,
            surface=RunSurface.EMBED if caller.surface == "embed" else RunSurface.WEB,
            conversation_id=conversation_id,
            user_name=caller.user_name,
            acts_for_sender=not caller.anonymous,
            voice=VoiceRun(
                options=VoiceOptions(
                    on_deferred=bridge,
                    anonymous=caller.anonymous,
                    voice_note=resolved.voice_note,
                    language=resolved.language,
                ),
                model_label=resolved.label,
                provider=resolved.provider,
                secret_id=resolved.secret_id,
            ),
        )
        bridge.attach(prepared.approvals)
        headroom = await prepared.built.budget.headroom()
        if limits.budget_refuses(
            headroom=headroom, worst=limits.worst_case_usd(cap_seconds=cap, entry=resolved.entry)
        ):
            raise VoiceRefused("budget", "There is not enough budget left for a call.")
        # Before the commit: neither opens a connection, and a key that cannot build
        # the model is a refusal here rather than a run orphaned after it.
        model_settings = realtime_settings(
            provider=resolved.provider,
            voice=resolved.voice,
            language=resolved.language,
            thinking=thinking_effort(prepared.spec),
            supports_thinking=resolved.entry.supports_thinking,
        )
        try:
            model = build_realtime_model(
                provider=resolved.provider,
                model=resolved.wire_model,
                secret=secret,
                settings=model_settings,
            )
        except BadRequestError:
            raise VoiceRefused(
                "not_configured",
                "This agent's voice key cannot hold a call. Choose another on its Voice card.",
            ) from None

        now = datetime.now(UTC)
        if caller.user_id is not None:
            await self._claim_slot(caller.user_id, now=now)
        call = await voice_call_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            run_id=prepared.run.id,
            user_id=caller.user_id,
            conversation_id=conversation_id,
            embed_id=caller.embed_id,
            surface=caller.surface,
            provider=resolved.provider,
            model=resolved.wire_model,
            transport=resolved.entry.transport,
            secret_id=resolved.secret_id,
            worker_id=WORKER_ID,
            resume_of=frame.resume_of,
            started_at=now,
        )
        # The first commit (amendment 5). It also releases the slot lock, after the
        # row the next start will count is visible.
        await self.db.commit()
        return StartedCall(
            call_id=call.id,
            prepared=prepared,
            resolved=resolved,
            secret=secret,
            settings=model_settings,
            model=model,
            cost_limit=headroom,
            cap_seconds=cap,
            minutes_left=None if left is None else left // 60,
            conversation_id=conversation_id,
            bridge=bridge,
            guard=TranscriptGuard.for_spec(prepared.spec),
            meter=UsageMeter(
                prepared.built.ledger,
                entry=resolved.entry,
                model_name=resolved.model,
                price_as=price_provider if resolved.provider == "azure" else None,
            ),
            writer=TurnWriter(
                sessions=self._sessions,
                call_id=call.id,
                conversation_id=conversation_id,
                run_id=prepared.run.id,
                agent_id=agent.id,
                agent_version_id=prepared.run.agent_version_id,
            ),
            runner=runner,
        )

    async def _conversation(
        self, caller: VoiceCaller, frame: StartFrame, *, organization_id: UUID
    ) -> UUID:
        requested = caller.conversation_id or frame.conversation_id
        if requested is not None:
            try:
                conversation = await ConversationService(self.db).get_conversation(
                    requested,
                    organization_id=organization_id,
                    user_id=caller.user_id,
                    for_write=True,
                    include_favourite=False,
                )
            except NotFoundError:
                raise VoiceRefused(
                    "forbidden", "That conversation is not yours to call into."
                ) from None
            return conversation.id
        conversation = await conversation_repo.create_conversation(
            self.db, organization_id=organization_id, user_id=caller.user_id, title="Voice call"
        )
        return conversation.id

    async def _resume(
        self, caller: VoiceCaller, frame: StartFrame, *, agent_id: UUID, conversation_id: UUID
    ) -> int:
        """The chain's elapsed seconds for a reconnect, or 0 for a new call.

        Only the same person, agent and conversation, and only within ten seconds
        of the previous connection ending (Q13, amendment 9). A previous connection
        still open is the normal case after a real network drop - the server keeps
        the old socket half-open until its ping times out, 20-40 s, while the
        client retries after 1.5 s - so it is ended here rather than refused.
        """
        if frame.resume_of is None:
            return 0
        previous = await voice_call_repo.get(
            self.db, frame.resume_of, organization_id=caller.ctx.organization_id
        )
        if (
            previous is None
            or previous.user_id != caller.user_id
            or previous.agent_id != agent_id
            or previous.conversation_id != conversation_id
        ):
            raise VoiceRefused("resume_refused", "The call could not be resumed. Start a new one.")
        if previous.ended_at is None:
            # Still open: this reconnect ends it, so it ended just now, for this
            # reconnect - the ten-second window is about a connection that ended
            # on its own, and does not apply.
            previous = await self._end_previous(previous)
            if previous.ended_at is None:
                raise VoiceRefused(
                    "resume_refused", "The call could not be resumed. Start a new one."
                )
        elif (datetime.now(UTC) - previous.ended_at).total_seconds() > limits.RESUME_WINDOW_SECONDS:
            raise VoiceRefused("resume_refused", "The call could not be resumed. Start a new one.")
        return await voice_call_repo.chain_seconds(self.db, previous.id)

    async def _end_previous(self, previous: VoiceCall) -> VoiceCall:
        """End a connection the server still holds open, and wait (bounded) until it reads ended.

        On this worker, through the live registry: the holder's own teardown hangs
        up and records the final cost. On another worker - or a dead one - by
        recording its end from the last heartbeat and hanging it up the reaper's
        way (`hang_up_row`); that worker's next heartbeat finds its row ended and
        stops (Task 19), and its teardown's figures win (`voice_call_repo.end`).
        Its run is closed as `cancelled` here - continued by this reconnect, not
        failed - in case that worker is dead and nothing else would close it; a
        live worker's own `finish` still writes the final figures over it.
        """
        if not LIVE_CALLS.request_end_for(previous.id, VoiceEndReason.DISCONNECTED):
            async with self._sessions() as own:
                now = datetime.now(UTC)
                await voice_call_repo.end(
                    own,
                    previous.id,
                    at=now,
                    reason=VoiceEndReason.DISCONNECTED,
                    cost_usd=previous.cost_usd,
                    seconds=previous.seconds,
                    guardrail_hits=previous.guardrail_hits,
                )
                if previous.run_id is not None:
                    await agent_run_repo.close_voice_run(
                        own,
                        run_id=previous.run_id,
                        status=RunStatus.CANCELLED.value,
                        cost_usd=previous.cost_usd,
                        ended_at=now,
                        error=None,
                    )
                    await agent_run_repo.expire_pending_approvals(
                        own, run_id=previous.run_id, decided_at=now
                    )
                if await hang_up_row(own, previous):
                    await voice_call_repo.mark_hung_up(own, previous.id, at=now)
        with anyio.move_on_after(limits.RESUME_WAIT_SECONDS):
            while True:
                async with self._sessions() as own:
                    current = await voice_call_repo.get(
                        own, previous.id, organization_id=previous.organization_id
                    )
                if current is not None and current.ended_at is not None:
                    return current
                await anyio.sleep(0.25)
        return previous

    async def _claim_slot(self, user_id: UUID, *, now: datetime) -> None:
        """Refuse a call past the person's concurrent-call limit, one start at a time.

        The advisory lock is transaction-scoped and taken before the count, so two
        starts at once cannot both count zero open calls: the second waits until
        the first has committed its row, then counts it.
        """
        await hold_subject(self.db, LockScope.VOICE_CALLS_PER_USER, user_id)
        open_calls = await voice_call_repo.count_open_for_user(
            self.db,
            user_id=user_id,
            fresh_since=now - timedelta(seconds=limits.STALE_AFTER_SECONDS),
        )
        if open_calls >= settings.VOICE_MAX_CALLS_PER_USER:
            raise VoiceRefused("busy", "You are already on a call. End it before starting another.")
