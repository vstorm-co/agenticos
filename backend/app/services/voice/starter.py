"""Starting a call: every refusal before anything is spent (#54).

In order, and each refusal rolls back whatever was flushed: the agent and the
caller's access to it, the Voice section - calls are switched on in the agent,
not the organization - the conversation's ownership, the resume rules, the key,
a price that can be computed, the budget against the call's worst case, and the
caller's concurrent calls. Then the call row and the run are committed - the
first commit of the call (amendment 5) - so approval rows, heartbeats and the
reaper can see them.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from secrets import compare_digest, token_urlsafe
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
from app.core.exceptions import AppException, AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import StorableSecret
from app.db.locks import LockScope, hold_subject
from app.db.models.agent_embed import AgentEmbed
from app.db.models.agent_run import RunSurface
from app.db.models.conversation import Conversation
from app.db.models.voice_call import VoiceCall, VoiceEndReason
from app.repositories import conversation_repo, embed_visitor_repo, voice_call_repo
from app.schemas.voice import StartFrame
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService, PreparedRun, VoiceRun
from app.services.conversation import ConversationService
from app.services.embed_session import placement_preamble
from app.services.organization_secret import OrganizationSecretService
from app.services.session import hash_token
from app.services.voice import limits
from app.services.voice.approvals import SendFrame, VoiceApprovalBridge
from app.services.voice.exceptions import VoiceRefused
from app.services.voice.guard import TranscriptGuard
from app.services.voice.meter import UsageMeter
from app.services.voice.questions import VoiceQuestions
from app.services.voice.reaper import close_orphaned
from app.services.voice.registry import LIVE_CALLS, WORKER_ID
from app.services.voice.settings import ResolvedVoice, VoiceSettingsService, resolve_voice
from app.services.voice.transcript import SessionFactory, TurnWriter
from app.services.voice.transport import refuse_data_channel

logger = logging.getLogger(__name__)


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
    visitor_key: str | None = None
    """A hosted page visitor's continuity key, so a new thread is linked to it."""
    conversation_title: str = "Voice call"
    """What a conversation the call starts is called."""
    embed: AgentEmbed | None = None
    """The embed a visitor was admitted to: its placement context and declared variables."""


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
    """When the server ends the call: the agent's longest call, less what a reconnect's chain used."""
    resume_token: str
    """What this connection's caller must present to resume it; the row holds its hash."""
    conversation_id: UUID
    bridge: VoiceApprovalBridge
    questions: VoiceQuestions
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
            AppException: Any other refusal on the way (a key that cannot be
                unsealed, a run that cannot be prepared), rolled back the same way.
        """
        try:
            return await self._start(caller, frame)
        except AppException:
            await self.db.rollback()
            raise

    async def _start(self, caller: VoiceCaller, frame: StartFrame) -> StartedCall:
        ctx = caller.ctx
        agent_id = caller.agent_id or frame.agent_id
        if agent_id is None:
            raise VoiceRefused("no_agent", "Pick an agent to call.")
        try:
            agent = await AgentRegistryService(self.db).get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        except NotFoundError, AuthorizationError:
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
            caller, frame, organization_id=ctx.organization_id, agent_id=agent.id
        )
        chain_elapsed = await self._resume(
            caller, frame, agent_id=agent.id, conversation_id=conversation_id
        )
        cap = limits.call_cap_seconds(
            agent_max=resolved.max_call_seconds, chain_elapsed=chain_elapsed
        )
        if cap < limits.MIN_CALL_SECONDS:
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

        await self._refuse_when_full(caller, now=datetime.now(UTC))

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
                    briefing=_briefing(caller, frame),
                ),
                model_label=resolved.label,
                provider=resolved.provider,
                secret_id=resolved.secret_id,
            ),
        )
        bridge.attach(prepared.approvals)
        questions = VoiceQuestions(send=self._send)
        if caller.surface == "web":
            # The console's call view draws the card; a widget's and a hosted
            # page's do not, and with no channel the agent is offered no `ask_user`.
            prepared.built.deps.ask_questions = questions
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
        resume_token = token_urlsafe(32)
        if caller.user_id is not None:
            await self._claim_slot(caller.user_id, now=now)
        elif caller.embed_id is not None:
            await self._claim_embed_slot(caller.embed_id, now=now)
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
            resume_token_hash=hash_token(resume_token),
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
            resume_token=resume_token,
            conversation_id=conversation_id,
            bridge=bridge,
            questions=questions,
            guard=TranscriptGuard.for_spec(prepared.spec),
            meter=UsageMeter(
                prepared.built.ledger,
                entry=resolved.entry,
                model_name=resolved.model,
                provider=price_provider,
                price_here=resolved.provider == "azure",
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
        self, caller: VoiceCaller, frame: StartFrame, *, organization_id: UUID, agent_id: UUID
    ) -> UUID:
        if caller.surface == "embed":
            return await self._embed_conversation(
                caller, frame, organization_id=organization_id, agent_id=agent_id
            )
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
            _refuse_archived(conversation)
            return conversation.id
        conversation = await conversation_repo.create_conversation(
            self.db,
            organization_id=organization_id,
            user_id=caller.user_id,
            title=caller.conversation_title,
        )
        return conversation.id

    async def _embed_conversation(
        self, caller: VoiceCaller, frame: StartFrame, *, organization_id: UUID, agent_id: UUID
    ) -> UUID:
        """The thread an embed's call lands in (#54, slice 2).

        Never the frame's: a visitor has no conversation to name, and an id a
        stranger sends is not one they own. A hosted page's visitor calls into
        the thread their continuity key holds (resolved at admission, by the
        server). A widget's reconnect continues the thread of the call it
        resumes - only a visitor's call on this same embed and agent, and
        `_resume` then holds it to the ten-second window. Otherwise the call
        starts one, and a page links it to the key conditionally, adopting
        whichever thread won - the two-tab rule `EmbedSession._turn` follows,
        `link_conversation` has the race.
        """
        if caller.conversation_id is not None:
            return await self._reused(caller.conversation_id, organization_id=organization_id)
        if frame.resume_of is not None:
            previous = await voice_call_repo.get(
                self.db, frame.resume_of, organization_id=organization_id
            )
            if (
                previous is not None
                and _holds_resume_token(previous, frame)
                and previous.conversation_id is not None
                and previous.embed_id is not None
                and previous.embed_id == caller.embed_id
                and previous.user_id is None
                and previous.agent_id == agent_id
            ):
                return await self._reused(previous.conversation_id, organization_id=organization_id)
        conversation = await conversation_repo.create_conversation(
            self.db,
            organization_id=organization_id,
            user_id=None,
            title=caller.conversation_title,
        )
        if caller.embed_id is None or caller.visitor_key is None:
            return conversation.id
        visitor = await embed_visitor_repo.get(
            self.db, embed_id=caller.embed_id, visitor_key=caller.visitor_key
        )
        if visitor is None:
            return conversation.id
        return await embed_visitor_repo.link_conversation(
            self.db, db_visitor=visitor, conversation_id=conversation.id
        )

    async def _reused(self, conversation_id: UUID, *, organization_id: UUID) -> UUID:
        """A thread an embed's call continues, refused when it has been archived since."""
        conversation = await ConversationService(self.db).get_conversation(
            conversation_id, organization_id=organization_id, include_favourite=False
        )
        _refuse_archived(conversation)
        return conversation_id

    async def _resume(
        self, caller: VoiceCaller, frame: StartFrame, *, agent_id: UUID, conversation_id: UUID
    ) -> int:
        """The chain's elapsed seconds for a reconnect, or 0 for a new call.

        Only the same person, agent and conversation, holding the token the
        previous connection's `ready` gave them, and only within ten seconds of
        that connection ending (Q13, amendment 9). A previous connection
        still open is the normal case after a real network drop - the server keeps
        the old socket half-open until its ping times out, 20-40 s, while the
        client retries after 1.5 s - so it is ended here rather than refused.
        """
        if frame.resume_of is None:
            return 0
        refused = VoiceRefused("resume_refused", "The call could not be resumed. Start a new one.")
        previous = await voice_call_repo.get(
            self.db, frame.resume_of, organization_id=caller.ctx.organization_id
        )
        if (
            previous is None
            or not _holds_resume_token(previous, frame)
            or previous.user_id != caller.user_id
            or previous.embed_id != caller.embed_id
            or previous.agent_id != agent_id
            or previous.conversation_id != conversation_id
        ):
            raise refused
        # One reconnect at a time per connection, and only while no other one has
        # continued it: the lock holds until this start commits its own row, so a
        # second socket with the same token waits for it and then finds it open.
        await hold_subject(self.db, LockScope.VOICE_RESUME, previous.id)
        if await voice_call_repo.has_open_successor(self.db, previous.id):
            raise refused
        if previous.ended_at is None:
            # Still open: this reconnect ends it, so it ended just now, for this
            # reconnect - the ten-second window is about a connection that ended
            # on its own, and does not apply.
            previous = await self._end_previous(previous)
            if previous.ended_at is None:
                raise refused
        elif (
            datetime.now(UTC) - _closed_at(previous, ended_at=previous.ended_at)
        ).total_seconds() > limits.RESUME_WINDOW_SECONDS:
            raise refused
        elapsed = await voice_call_repo.chain_seconds(self.db, previous.id)
        if elapsed is None:
            # Reconnected as often as a chain is counted: a further connection's
            # time would not be summed with the oldest ones'.
            raise refused
        return elapsed

    async def _end_previous(self, previous: VoiceCall) -> VoiceCall:
        """End a connection the server still holds open, and wait (bounded) until it reads ended.

        On this worker, through the live registry: the holder's own teardown hangs
        up and records the final cost. On another worker - or a dead one - the
        sweep's way (`close_orphaned`): hung up, ended from its last heartbeat,
        and its run closed as `cancelled` - continued by this reconnect, not
        failed - in case that worker is dead and nothing else would close it.
        That worker's next heartbeat finds its row ended and stops (Task 19), and
        its teardown's figures win (`voice_call_repo.end`); its own `finish`
        still writes the final figures over the run. A failure here is logged and
        leaves the row as it was, so the wait below runs out and the reconnect is
        refused rather than crashing.
        """
        if not LIVE_CALLS.request_end_for(previous.id, VoiceEndReason.DISCONNECTED):
            try:
                async with self._sessions() as own:
                    await close_orphaned(
                        own, previous, reason=VoiceEndReason.DISCONNECTED, now=datetime.now(UTC)
                    )
            except Exception:
                logger.exception("voice_previous_close_failed", extra={"call_id": str(previous.id)})
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

    async def _claim_embed_slot(self, embed_id: UUID, *, now: datetime) -> None:
        """Refuse a visitor's call past the embed's concurrent-call limit, one start at a time.

        Visitors have no account to count against, so without this one leaked
        link could hold as many calls at once as its start rate allows and spend
        the organization's budget - every member's runs with it - in parallel. The same lock-then-count as `_claim_slot`.
        """
        await hold_subject(self.db, LockScope.VOICE_CALLS_PER_EMBED, embed_id)
        await self._refuse_embed_when_full(embed_id, now=now)

    async def _claim_slot(self, user_id: UUID, *, now: datetime) -> None:
        """Refuse a call past the person's concurrent-call limit, one start at a time.

        The advisory lock is transaction-scoped and taken before the count, so two
        starts at once cannot both count zero open calls: the second waits until
        the first has committed its row, then counts it.
        """
        await hold_subject(self.db, LockScope.VOICE_CALLS_PER_USER, user_id)
        await self._refuse_user_when_full(user_id, now=now)

    async def _refuse_when_full(self, caller: VoiceCaller, *, now: datetime) -> None:
        """The same counts without the lock: a look before the run is assembled.

        A line already full is refused without paying for an agent's assembly - a
        sandbox, delegates, tools - only to refuse it after. Never the decision
        between two starts racing for the last place: the claim's locked count,
        after, is.
        """
        if caller.user_id is not None:
            # A call hung up a moment ago is still open until its teardown writes
            # the end, so the count is given a moment to drop before it refuses.
            with anyio.move_on_after(limits.ENDING_GRACE_SECONDS):
                while True:
                    if not await self._user_is_full(caller.user_id, now=datetime.now(UTC)):
                        break
                    await anyio.sleep(0.25)
            await self._refuse_user_when_full(caller.user_id, now=datetime.now(UTC))
        elif caller.embed_id is not None:
            await self._refuse_embed_when_full(caller.embed_id, now=now)

    async def _user_is_full(self, user_id: UUID, *, now: datetime) -> bool:
        open_calls = await voice_call_repo.count_open_for_user(
            self.db,
            user_id=user_id,
            fresh_since=now - timedelta(seconds=limits.STALE_AFTER_SECONDS),
        )
        return open_calls >= settings.VOICE_MAX_CALLS_PER_USER

    async def _refuse_user_when_full(self, user_id: UUID, *, now: datetime) -> None:
        if await self._user_is_full(user_id, now=now):
            raise VoiceRefused("busy", "You are already on a call. End it before starting another.")

    async def _refuse_embed_when_full(self, embed_id: UUID, *, now: datetime) -> None:
        open_calls = await voice_call_repo.count_open_for_embed(
            self.db,
            embed_id=embed_id,
            fresh_since=now - timedelta(seconds=limits.STALE_AFTER_SECONDS),
        )
        if open_calls >= settings.VOICE_MAX_CALLS_PER_EMBED:
            raise VoiceRefused(
                "line_busy", "Too many calls are open here right now. Try again in a few minutes."
            )


def _holds_resume_token(previous: VoiceCall, frame: StartFrame) -> bool:
    """Whether a resume presents the token the previous connection's `ready` gave its caller.

    The call id alone is not proof of being on the call. A connection with no
    token on record (opened before there was one) cannot be resumed, and a
    client that sends none is refused rather than failing.
    """
    return (
        previous.resume_token_hash is not None
        and frame.resume_token is not None
        and compare_digest(previous.resume_token_hash, hash_token(frame.resume_token))
    )


def _refuse_archived(conversation: Conversation) -> None:
    """Refuse a call into an archived thread: it is closed to new messages, as
    `ConversationService.add_message` holds it, and a call's turns are messages."""
    if conversation.is_archived:
        raise VoiceRefused(
            "forbidden", "That conversation is archived. Restore it to call into it."
        )


def _closed_at(previous: VoiceCall, *, ended_at: datetime) -> datetime:
    """When an ended connection stopped being held, which the resume window runs from.

    Its end, as a rule. A reconnect that closed it from another worker
    (`close_orphaned`) stamps the end at its last heartbeat, so the minutes stop
    where the connection was last alive - up to a heartbeat and more before the
    close - and that reconnect's own retry, after it failed before `ready`, would
    be refused by a window it is still inside. Its hang-up, recorded at the close,
    says when that was.
    """
    if previous.end_reason == VoiceEndReason.DISCONNECTED.value and previous.hung_up_at is not None:
        return max(ended_at, previous.hung_up_at)
    return ended_at


MAX_BRIEFED_VALUE_CHARS = 200
"""The longest a page-supplied value is carried into a call's instructions.

Longer than any order number, plan or name a page describes a visitor with, and
short enough that a value a visitor pasted does not inflate instructions that
are billed again on every response of the call."""


def _briefing(caller: VoiceCaller, frame: StartFrame) -> str | None:
    """What a text turn on the caller's embed would prepend, or `None` off an embed.

    The same preamble and the same narrowing (`placement_preamble`): only
    variables the embed declares (at most twenty), only URL-safe ones on a hosted
    page, and as unverified data about the visitor rather than instructions. In
    the call's instructions rather than its history on purpose (`CALL_BRIEFING`),
    so each value is bounded first.
    """
    if caller.embed is None:
        return None
    supplied = {
        name: value[:MAX_BRIEFED_VALUE_CHARS] if isinstance(value, str) else value
        for name, value in (frame.context or {}).items()
    }
    parts = placement_preamble(caller.embed, supplied)
    return "\n\n".join(parts) if parts else None
