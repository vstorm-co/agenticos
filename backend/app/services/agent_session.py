# Thin session wrapper - the route is lifecycle plumbing only; orchestration lives here.
import asyncio
import contextlib
import logging
import time
from collections.abc import Mapping
from typing import Any, NamedTuple
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic_ai.exceptions import CallDeferred, ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage
from pydantic_ai_harness.ask_user import AskUserRequest, AskUserResponse

from app.agents.ask_user import (
    QuestionChoice,
    QuestionItem,
    answers_to_response,
    asking_delegate,
    render_answer,
    wire_questions,
)
from app.agents.browser_events import BrowserEvent
from app.agents.capabilities.budget import BudgetExceeded
from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.compaction_events import CompactionEvent
from app.agents.connect_on_use import ConnectionRequest
from app.agents.failures import run_failure_summary
from app.agents.loop_guard import ToolLoopStopped
from app.agents.steering import SteeringInbox
from app.agents.subagent_events import SubagentEvent
from app.agents.visual_reports import VisualReports
from app.core.config import settings
from app.core.exceptions import AppException, AuthenticationError, NotFoundError
from app.db.models.chat_file import ChatFile
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db_context
from app.repositories import agent_repo, agent_run_repo, conversation_repo, member_repo
from app.schemas.conversation import ChatPerson, MessagePart
from app.services import chat_room, live_turn
from app.services.agent import (
    persist_assistant_turn,
    persist_user_turn,
    send_event,
)
from app.services.agent_chat import (
    ChatAgentRunner,
    ChatTurn,
    OpenedRun,
    requested_agent_id,
    requested_approval_mode,
    requested_environment_id,
    requested_mentions,
    requested_model_profile_id,
    requested_testing,
    requested_time_zone,
)
from app.services.agent_runner import PersonalServiceGap
from app.services.attachments import load_turn_attachments
from app.services.chat_timeline import TurnTimeline
from app.services.conversation import ConversationService
from app.services.notifications import NotificationService
from app.services.run_stream import RunFrames
from app.services.usage_report import usage_frame
from app.services.ws_auth import authenticate_socket_token

logger = logging.getLogger(__name__)

RECHECK_SECONDS = 30.0
"""How often a turn being followed asks again whether its reader may still read it."""

ROOM_READS_FOR_SECONDS = 5.0
"""How long a room's reader, once asked, is taken to still read it.

Every piece of a room's news asks again - each keystroke announced, each
arrival - and in a busy room that was a credential, membership and conversation
query per reader per announcement. A reader removed is still cut off within
this long."""

ROOM_RETRY_SECONDS = 5.0
"""How long a socket whose room subscription failed waits before listening again."""

TYPING_EVERY_SECONDS = 2.0
"""The least time between two "typing" announcements from one socket; the console sends one every three."""

# Said to a frame that names no agent. There is nothing else a frame could run:
# the general assistant the template shipped is gone, and guessing an agent on
# the user's behalf would mean something they never picked answering them.
_PICK_AN_AGENT = "Pick an agent to chat with. If none is listed, publish one in the Builder first."

# Closed with the same 4001 the handshake uses for a bad credential: the client
# treats it as a no-retry auth close rather than a dropped connection to
# reconnect (`use-websocket.ts` NO_RETRY_CLOSE_CODES), which is what a revoked
# session should get (#1437).
_REVOKED_CLOSE_CODE = 4001
_REVOKED_CLOSE_REASON = "Session revoked"

HISTORY_MESSAGES = 200
"""How many of a thread's turns the model is reminded of.

The channel router's number, not the widget's 40: both surfaces are signed-in
members working in a thread that never rolls over, where the widget's is a
public visitor whose session is a page view. See `channels.router.HISTORY_MESSAGES`
and `embed_session.HISTORY_MESSAGES`.

This is a count of messages, not of tokens, and nothing here compacts it: the
`compaction` capability rewrites the messages of one *run*, and a conversation
is replayed as text.
"""


def _detached_grace_s() -> float:
    """How long a turn may go on after the socket watching it has gone.

    A dropped socket is not a decision to abandon the answer. `send_event` already
    answers a closed socket with `False` rather than raising, which is the contract
    `run_stream.FrameSink` states - *a visitor who closed the tab must not take the
    run with them* - and `process_message`'s own `finally` writes down whatever the
    model produced either way. So a turn allowed to reach its end is a `COMPLETED`
    run with its answer in the transcript, which is what the reader finds when they
    come back. Cancelling on the disconnect instead wrote `CANCELLED` against a
    half-finished reply and labelled it *stopped*, for a browser that had done
    nothing but refresh its access token.

    Bounded, because an agent left iterating spends the organization's budget on an
    answer that may never be read. It was ten minutes, which cut off exactly the
    turns somebody walks away from - a research task, a long browse - and an hour
    by default now that the person is told when it lands (#2108):
    `CHAT_DETACHED_TURN_MINUTES`. The budget capability is the real ceiling; this
    is the one that applies when the reason to stop is that the reader has gone.
    """
    return settings.CHAT_DETACHED_TURN_MINUTES * 60


def _turn_failed(exc: Exception) -> str:
    """What a crashed turn is allowed to tell the client.

    The `error` frame used to carry `str(exc)` of whatever came out of the run.
    A provider SDK puts the failing request in its message, so that routinely
    means an endpoint, an internal host, or a URL with a key still in its query
    string - the leak #342 fixed in an HTTP body, reaching a member's chat panel
    and their browser console instead (#659).

    So the exception's own text stays in the `logger.exception` beside the send
    and goes no further, and the frame names only what the reader can act on.
    The class still goes out: it separates an upstream that timed out from one
    that refused a credential, and a class name has never carried a URL. Our own
    refusals do not come here at all - an `AppException`, a `BudgetExceeded` and a
    `GuardrailBlocked` are caught above and passed through whole, because their
    messages are written in this repository.
    """
    # A provider that answered with a status says something the reader can act
    # on - a key out of credit, a refused credential, a rate limit - and
    # `run_failure_summary` is where that sentence is written for the run's row,
    # so the chat says the same thing rather than only the class name.
    cause: BaseException = exc
    while isinstance(cause, BaseExceptionGroup):
        cause = cause.exceptions[0]
    if isinstance(cause, ModelHTTPError | UsageLimitExceeded):
        return run_failure_summary(cause)
    return (
        f"The agent could not finish this turn ({type(exc).__name__}). "
        "Try again; the server log has the full error."
    )


_ANSWER_NOT_SAVED = "the answer could not be saved."
"""What the away notice says when the run finished and its answer's write failed."""


class _Outcome(NamedTuple):
    """How a turn ended, for telling somebody who was not there to see it."""

    run_id: UUID
    agent_id: UUID
    error: str | None


class _LeftUnanswered(Exception):
    """The socket went away while the run's own question card was open."""


class AgentSession:
    """One WebSocket session with the AI agent."""

    def __init__(
        self,
        websocket: WebSocket,
        user: User,
        organization: Organization,
        auth_token: str | None = None,
    ) -> None:
        self.websocket = websocket
        self.user = user
        self.organization_id = organization.id
        # The credential the socket was opened with, re-checked before every
        # frame so a revoked session cannot keep running (#1437). None only when
        # the socket carried no token to re-check - which the handshake refuses,
        # so it happens in tests alone; such a session is left to run.
        self._auth_token = auth_token
        self.current_conversation_id: str | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._ask_user_future: asyncio.Future[list[dict[str, Any]]] | None = None
        # A run waiting for the person to connect one of their own services;
        # completed by `connect_account_response`, one at a time under `_ask_lock`.
        self._connect_future: asyncio.Future[bool] | None = None
        # The running turn's timeline, so `_ask_one` can record a mid-turn
        # question and its answer as a part of the turn it happened in (#502).
        # None between turns; set and cleared by `process_message`.
        self._current_timeline: TurnTimeline | None = None
        # The questions awaiting answers, so the frame handler can record each
        # answered pair the moment they arrive - before a `stop` frame behind them
        # can cancel the turn and lose them (#502). One round at a time, under
        # `_ask_lock`: a delegate's single question, or an `ask_user` card.
        self._pending_questions: list[str] | None = None
        # Which delegate that question came from, read where the question is put
        # rather than where its answer lands: the delegation's state is bound for
        # the duration of the delegation, so it is bound inside `_ask_one` and
        # gone by the time the answer arrives on the receive loop (#1042).
        self._pending_asked_by: str | None = None
        # Whether the open round is the run's own `ask_user` card, which outlives
        # the socket: left unanswered, it parks the run rather than being read as
        # declined (#2064). A delegate's question has no such afterlife.
        self._round_parks = False
        # One question round on the wire at a time. The client renders a single
        # `ask_user` form and its `ask_user_response` carries no correlation, and
        # `_ask_user_future` is one slot - so two delegates asking at once (a
        # fan-out of sync delegates, each reaching `ask_parent`) would otherwise
        # have the second overwrite the first's future and strand it. The lock
        # holds each round until its answer arrives, so questions queue rather
        # than collide.
        self._ask_lock = asyncio.Lock()
        # What the person adds to the running turn (#2087). Set for the length of
        # a turn by `process_message`, None between turns.
        self._steering: SteeringInbox | None = None
        # How the turn's drawings rendered in this tab (#2171), for the same span.
        self._visual_reports: VisualReports | None = None
        # The running turn's agent and run, and how the turn ended - read by
        # `shutdown` to tell a person who left before the answer came (#2108).
        self._turn_agent_id: UUID | None = None
        self._turn_runs: list[OpenedRun] = []
        self._outcome: _Outcome | None = None
        # The conversation whose running turn this socket is writing, and that
        # turn's handle, which every frame is also kept under for a person who
        # comes back to it; and the turn this socket is following instead, from
        # another socket (`attach`).
        self._live: str | None = None
        self._live_turn: live_turn.Turn | None = None
        self._follower: asyncio.Task[None] | None = None
        # The conversation this socket has open, as one of the people in its
        # room (`chat_room`), and the task keeping it there.
        self._room: str | None = None
        # This socket's own entry in the room, beside the person's other tabs.
        self._socket = uuid4().hex
        self._room_task: asyncio.Task[None] | None = None
        # Until when the room this socket is in was last found readable - see
        # `ROOM_READS_FOR_SECONDS`.
        self._reads_until = float("-inf")
        # When this socket last told its room the person is typing - see `typing`.
        self._typed_at = float("-inf")
        # Set by `shutdown`. A room joined or a turn followed after it - by a turn
        # still running past the socket, or an `attach` that was mid-query when
        # the socket went - would count a closed tab as present until it expired.
        self._closed = False

    async def handle_frame(self, data: dict[str, Any]) -> None:
        """Dispatch one incoming WebSocket frame.

        A `stop` cancels the running turn; an `ask_user_response` or a
        `connect_account_response` unblocks a paused run; any other control frame is ignored; a bare message starts a
        new turn as a cancellable background task.

        A frame that will *act* on the session is refused first if that session
        has been revoked (#1437), so nothing - not a new turn, not the answer
        that resumes a parked one, not cancelling a turn that is still running -
        happens on a dead credential. A frame that would do nothing - an unknown
        control type, or a message arriving while a turn is already in progress -
        is dropped before that check, so it costs no credential query: an
        authenticated client cannot turn a stream of no-op frames into a stream
        of database reads (found reviewing #1437).
        """
        msg_type = data.get("type")

        if msg_type == "stop":
            if self._turn_task is None or self._turn_task.done():
                return
            if not await self._reauthorize():
                return
            await self._cancel_turn()
            return

        if msg_type == "ask_user_response":
            fut = self._ask_user_future
            if fut is None or fut.done():
                return
            if not await self._reauthorize():
                return
            raw = data.get("answers")
            answers = raw if isinstance(raw, list) else []
            fut.set_result(answers)
            # Recorded here, in the receive loop, rather than after the run
            # resumes past its await: a `stop` sent right behind the answer is
            # the next frame, so completing the pair now is what keeps a turn
            # cancelled a microtask later from losing the answered question
            # (#502).
            if self._pending_questions is not None and self._current_timeline is not None:
                for index, question in enumerate(self._pending_questions):
                    self._current_timeline.add_ask_user(
                        question,
                        render_answer(answers[index] if index < len(answers) else None),
                        asked_by=self._pending_asked_by,
                    )
            return

        if msg_type == "steer":
            text = str(data.get("text") or "").strip()
            if not text:
                return
            inbox = self._steering
            if inbox is None or self._turn_task is None or self._turn_task.done():
                # The turn ended between the click and the frame: nothing left to
                # steer, so the client sends it as an ordinary message instead.
                await self._emit("steer_unapplied", {"texts": [text]})
                return
            if not await self._reauthorize():
                return
            inbox.add(text)
            return

        if msg_type == "visual_report":
            reports = self._visual_reports
            call_id = data.get("tool_call_id")
            raw = data.get("errors")
            if reports is None or not isinstance(call_id, str) or not isinstance(raw, list):
                return
            if self._turn_task is None or self._turn_task.done():
                return
            if not await self._reauthorize():
                return
            reports.resolve(call_id, [str(error) for error in raw])
            return

        if msg_type == "connect_account_response":
            waiting = self._connect_future
            if waiting is None or waiting.done():
                return
            if not await self._reauthorize():
                return
            waiting.set_result(data.get("connected") is True)
            return

        if msg_type == "attach":
            if not await self._reauthorize():
                return
            await self._attach(data.get("conversation_id"))
            return

        if msg_type == "unfollow":
            # Stop on a turn this socket only follows: it is somebody else's to
            # stop, so this tab stops drawing it and stays in the room.
            self._stop_following()
            return

        if msg_type == "typing":
            # Only into the room this socket is in, which `attach` checked; no
            # credential query, since a keystroke is not an action, and the
            # people hearing it are re-checked before it reaches them. At most
            # one per `TYPING_EVERY_SECONDS`, whatever the client sends: each
            # costs everybody else in the room a lookup of who is typing.
            now = time.monotonic()
            if self._room is not None and now - self._typed_at >= TYPING_EVERY_SECONDS:
                self._typed_at = now
                await chat_room.typing(self._room, self.user.id)
            return

        if msg_type is not None:
            return

        if self._turn_task is not None and not self._turn_task.done():
            logger.warning("Ignoring message received while a turn is already in progress")
            return

        if not await self._reauthorize():
            return
        # Asking something here is watching this socket's own turn, not another's.
        self._stop_following()
        task = asyncio.create_task(self._run_turn(data))
        self._turn_task = task
        task.add_done_callback(self._on_turn_done)

    async def _reauthorize(self) -> bool:
        """Re-check the socket's credential before acting on a frame.

        The handshake authenticates once and the socket is then held open for
        its whole life, so a session revoked afterwards - an impersonation ended
        (#1044), an account suspended, a signed-out administrator behind an
        impersonation - would keep being served turn after turn if nothing
        re-checked it (#1437). Re-run the handshake's own check
        (`authenticate_socket_token`) on each inbound frame: on refusal, cancel
        any running turn and close the socket, so the next turn is never served
        on a dead session.

        The check is at the frame boundary, not mid-turn: a turn already
        streaming is left to finish, and the revocation lands on the next frame
        the client sends - which is what stops a legitimate long turn being cut
        off by it.

        `allow_expired=True`: the socket is authenticated once, at the handshake,
        and then held open past its access token's 30-minute lifetime - the
        connection outlives the token, and the client re-credentials by
        reconnecting, not per frame. So a token that has merely aged out is not a
        revocation and must not close a live socket; what closes it is a session
        or account state that says the access is gone, which this still reads.

        A session opened without a token has nothing to re-check (the handshake
        refuses a tokenless socket, so this is a test-only construction) and is
        left to run.
        """
        if self._auth_token is None:
            return True
        async with get_db_context() as db:
            try:
                await authenticate_socket_token(db, self._auth_token, allow_expired=True)
            except AuthenticationError:
                await self._cancel_turn()
                with contextlib.suppress(RuntimeError):
                    await self.websocket.close(
                        code=_REVOKED_CLOSE_CODE, reason=_REVOKED_CLOSE_REASON
                    )
                return False
        return True

    def _on_turn_done(self, task: asyncio.Task[None]) -> None:
        """Clear the turn slot and surface unexpected crashes."""
        if self._turn_task is task:
            self._turn_task = None
        if not task.cancelled():
            exc = task.exception()
            if isinstance(exc, WebSocketDisconnect):
                logger.info("Client disconnected during agent turn")
            elif exc is not None:
                logger.error("Agent turn task crashed", exc_info=exc)

    async def _run_turn(self, data: dict[str, Any]) -> None:
        """Run one turn, emitting a terminal `complete` even when stopped."""
        try:
            await self.process_message(data)
        except asyncio.CancelledError:
            await self._emit(
                "complete",
                {
                    "conversation_id": self.current_conversation_id,
                    "stopped": True,
                },
            )
            raise

    async def _cancel_turn(self) -> None:
        """Cancel the in-flight turn task and wait for it to unwind."""
        task = self._turn_task
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def shutdown(self) -> None:
        """Let the in-flight turn finish without its socket, then stop it.

        Called when the socket has gone - a closed tab, a dropped connection, a
        refreshed credential - and deliberately not the same act as `stop`.
        Nobody is waiting on the frames any more, but the answer is still worth
        having: it is written to the transcript by `process_message`, not to the
        socket, so the reader who comes back finds a finished turn rather than a
        half-written one marked *stopped*. See `_detached_grace_s`.

        `stop` is untouched. `handle_frame` still cancels immediately there,
        because somebody asked.
        """
        self._closed = True
        self._stop_following()
        await self._leave_room()
        task = self._turn_task
        if task is None or task.done():
            return
        # Released before the wait. A run paused on `ask_user` is waiting for an
        # answer from somebody who is no longer there and cannot reach its own
        # end while it waits, so the grace would be spent doing nothing and the
        # turn cancelled anyway. Answered as nothing, which `_ask_one` already
        # renders and which its docstring already names as one of the ways the
        # wait ends.
        fut = self._ask_user_future
        if fut is not None and not fut.done():
            if self._round_parks:
                fut.set_exception(_LeftUnanswered())
            else:
                fut.set_result([])
        # The same for a run waiting on a connection: nobody is there to make it.
        waiting = self._connect_future
        if waiting is not None and not waiting.done():
            waiting.set_result(False)
        # `shield` is what makes the two endings distinguishable: without it
        # `wait_for`'s timeout cancels the turn *through* the wait, and the
        # explicit cancellation below - the path every existing test covers, and
        # the one that unwinds delegations - would never run.
        try:
            await asyncio.wait_for(asyncio.shield(task), _detached_grace_s())
        except TimeoutError:
            logger.info("Turn ran past its detached grace with nobody watching; stopping it")
            await self._cancel_turn()
            if self._turn_runs and self._turn_agent_id is not None:
                minutes = round(settings.CHAT_DETACHED_TURN_MINUTES)
                await self._tell_the_absent(
                    _Outcome(
                        self._turn_runs[0].run_id,
                        self._turn_agent_id,
                        f"it was still working after {minutes} minutes with nobody "
                        "watching, so it was stopped",
                    )
                )
            return
        except asyncio.CancelledError:
            # This session's own task tree is being torn down - a redeploy, or
            # uvicorn draining. Stop the turn, then let the cancellation carry on
            # unwinding rather than swallowing it here.
            await self._cancel_turn()
            raise
        # The turn reached its end with nobody watching: say how, where they
        # will see it. A turn that parked on an approval or a question has
        # already told them through `approval_requested` or the question's park.
        await self._tell_the_absent(self._outcome)

    async def process_message(self, data: dict[str, Any]) -> None:
        """Process one user turn: persist input, run the agent, stream events, persist output."""
        self._outcome = None
        user_message = data.get("message", "")
        file_ids = data.get("file_ids", [])

        if not user_message and not file_ids:
            await self._emit("error", {"message": "Empty message"})
            return
        # Refused before the user turn is persisted: a message nothing will
        # answer does not belong in the transcript.
        try:
            agent_id = requested_agent_id(data)
        except AppException as exc:
            await self._emit("error", {"message": exc.message})
            return
        if agent_id is None:
            await self._emit("error", {"message": _PICK_AN_AGENT})
            return
        # What the person pointed at with `@`, resolved as them against what the
        # agent can reach (#2189). It never changes which agent answers.
        try:
            mention_refs = requested_mentions(data)
            if mention_refs:
                async with get_db_context() as db:
                    resolved = await ChatAgentRunner(db).mentions(
                        user=self.user,
                        organization_id=self.organization_id,
                        agent_id=agent_id,
                        refs=mention_refs,
                        # The test panel's draft, so a mention resolves against
                        # what that run reaches rather than the published version.
                        draft=requested_testing(data).draft,
                    )
                mentioned, mention_note = resolved.mentions, resolved.note
            else:
                mentioned, mention_note = [], None
        except AppException as exc:
            await send_event(self.websocket, "error", {"message": exc.message})
            return
        # `conversation_id: null` is the console's new chat, and it starts one. The
        # session used to read it as "no id given" and carry on in the conversation
        # this socket had open, so after New chat - or after deleting the open
        # conversation - the next message was written into the old thread, or
        # refused because that thread no longer existed. A frame without the key
        # still continues the session's conversation.
        if "conversation_id" in data and data["conversation_id"] is None:
            self.current_conversation_id = None
        try:
            prompt = await persist_user_turn(
                self.user,
                user_message,
                file_ids,
                requested_conversation_id=data.get("conversation_id"),
                current_conversation_id=self.current_conversation_id,
                organization_id=self.organization_id,
                # Read only when the turn starts a conversation: a chat is in
                # the project it was started in, and stays there.
                project_id=_wire_text(data.get("project_id")),
                # The message this turn answers, where the person replied to one.
                reply_to=_wire_text(data.get("reply_to")),
                mentions=mentioned,
            )
        except AppException as e:
            # Every refusal the write can raise, not only the cross-org one:
            # an archived conversation and an id that is not a UUID reach here
            # too, and both used to be logged inside `persist_user_turn` and
            # answered as though the turn had been recorded.
            await self._emit("error", {"message": e.message})
            return
        self.current_conversation_id = prompt.conversation_id
        if self.current_conversation_id:
            self._live = self.current_conversation_id
            self._live_turn = await live_turn.begin(self._live)
            await self._enter_room(self._live)
            if self._live_turn is not None:
                # Who asked, and what: the others in the room follow this turn
                # from its trace, and have no other way to see the question.
                await live_turn.publish(
                    self._live_turn,
                    "turn_prompt",
                    {
                        "conversation_id": self._live,
                        "message_id": None if prompt.message_id is None else str(prompt.message_id),
                        "content": user_message,
                        "sender": ChatPerson.of(self.user).model_dump(mode="json"),
                        # The message it answers: "yes, do that" means nothing to
                        # a teammate without the quote above it.
                        "reply_to": None
                        if prompt.reply is None
                        else prompt.reply.model_dump(mode="json"),
                        # Which agent answers, so a follower draws its face and name
                        # on the answer from the first word rather than at the end.
                        "agent_id": str(agent_id),
                    },
                )
            await chat_room.turn_begun(self._live, self.user.id)
        if prompt.newly_created and self.current_conversation_id:
            await self._emit(
                "conversation_created",
                {"conversation_id": self.current_conversation_id},
            )

        await self._emit("user_prompt", {"content": user_message})

        collected_tool_calls: list[dict[str, Any]] = []
        # Everything the model produces, in the order it produces it - the text,
        # the reasoning and where the tool calls sat between them. It is what gets
        # stored, so a reloaded conversation is the one somebody watched rather
        # than a reconstruction of it; see `chat_timeline.TurnTimeline`.
        #
        # It also holds what the model has said so far, for every turn that does
        # not end with an answer: one that failed, was stopped or lost its socket,
        # and one that parked on an approval. `turn.output` is the answer where
        # there is one and empty where there is not; nothing can tell in advance
        # which path a turn is on, and the alternative is throwing away a
        # half-written answer on exactly the runs somebody opens afterwards.
        timeline = TurnTimeline()
        self._current_timeline = timeline

        async def steered(text: str) -> None:
            # Where it reached the model is where the transcript shows it.
            timeline.add_steer(text)
            await self._emit("steer_applied", {"text": text})

        steering = SteeringInbox(on_applied=steered)
        self._steering = steering
        visual_reports = VisualReports(send_images=self._visual_images)
        self._visual_reports = visual_reports
        # The run row, as soon as `prepare` opens one. A list because the
        # callback is `list.append` and a turn opens at most one run - it is
        # empty when the run was refused before it existed.
        opened: list[OpenedRun] = []
        self._turn_agent_id = agent_id
        self._turn_runs = opened
        # Whether the assistant turn reached the database. Read by the `finally`,
        # which exists for the paths where `turn` was never assigned and so
        # cannot be consulted.
        answered = False

        # Declared above the `try` because the `finally` reads all five, and a
        # failure inside it - the history, the attachment lookup - must not turn
        # a lost answer into a `NameError`.
        try:
            model_history = await self._history(prompt.message_id)
            # The files, not a prompt built from them. Where an attachment goes
            # depends on whether the agent has a workspace, and only `prepare`
            # knows that - so the routing happens one layer down.
            # `prompt.message_id` may be None when `persist_user_turn` swallowed a
            # transient write failure so the turn could still run. The load path
            # keeps the caller's still-unlinked uploads in that case (a None message
            # matches unlinked rows), so a lost prompt row does not silently drop
            # the files the user submitted and paid for (#1654 review).
            attachments = (
                await self._attached_files(prompt.message_id, file_ids) if file_ids else []
            )

            frames = RunFrames(
                emit=self._frame,
                timeline=timeline,
                tool_calls=collected_tool_calls,
                prompt=user_message,
            )

            # One session for the whole turn: the run row, the approvals it
            # parks and the cost it books are a single unit of work, and
            # `finish` writes back to the row `prepare` opened.
            async with get_db_context() as db:
                turn = await ChatAgentRunner(db).run(
                    user=self.user,
                    organization_id=self.organization_id,
                    agent_id=agent_id,
                    user_input=(
                        prompt.for_model or user_message
                        if mention_note is None
                        else f"{prompt.for_model or user_message}\n\n{mention_note}"
                    ),
                    message_history=model_history,
                    attachments=attachments,
                    conversation_id=(
                        UUID(self.current_conversation_id) if self.current_conversation_id else None
                    ),
                    prompt_message_id=prompt.message_id,
                    ask_user=self._ask_one,
                    ask_questions=self._ask_questions,
                    stream=frames.drive,
                    on_run_open=opened.append,
                    subagent_events=self._subagent_event,
                    on_compaction=self._compaction_event,
                    browser_events=self._browser_event,
                    on_sandbox_wait=self._sandbox_wait_event,
                    on_personal_gaps=self._personal_gaps_event,
                    request_connection=self._request_connection,
                    # The chat may run a published agent on another of the
                    # organization's models. Only the model changes; the run
                    # records which one, and the budget is the agent's.
                    model_profile_id=requested_model_profile_id(data),
                    environment_id=requested_environment_id(data),
                    # How much this session wants to be asked. Validated inside
                    # `prepare` against the caller's `approvals:decide` and the
                    # organization's ceiling, and *refused* there rather than
                    # downgraded (#925).
                    approval_mode=requested_approval_mode(data),
                    person_time_zone=requested_time_zone(data),
                    # The Builder's test panel: the draft, or a version, marked
                    # as a test either way (#2074).
                    testing=requested_testing(data),
                    steering=steering,
                    visual_reports=visual_reports,
                )
            # `turn.output` is what the run *ended* with; a turn that parked ended
            # with nothing, so its words are on the timeline (#509).
            output = turn.output or timeline.text
            model_label = turn.model_label
            agent_version_id = turn.agent_version_id

            assistant_msg_id: str | None = None
            if self.current_conversation_id:
                assistant_msg_id = await persist_assistant_turn(
                    self.current_conversation_id,
                    output,
                    model_label,
                    collected_tool_calls,
                    organization_id=self.organization_id,
                    thinking=timeline.thinking,
                    parts=timeline.stored(),
                    agent_id=agent_id,
                    agent_version_id=agent_version_id,
                    usage=turn.usage,
                    run_id=turn.run_id,
                    # Stored as `awaiting_approval`, so reloading the page keeps
                    # saying the step is waiting on a person (#601). The frame
                    # below carries the same calls to whoever is watching live.
                    parked_tool_call_ids={parked.tool_call_id for parked in turn.parked}
                    | set(turn.questions),
                    mcp_origins=turn.mcp_origins,
                )
                # Written, so the `finally` below has nothing left to save. It
                # cannot read `turn` to work that out - the whole point of it is
                # the paths where `turn` was never assigned.
                answered = True
                await self._remember_context(turn)
                if turn.run_id is not None and not turn.parked and not turn.questions:
                    # Only an answer that is there to come back to. A write that
                    # failed returns no id, and "answered while you were away"
                    # would link to a conversation ending in the question.
                    self._outcome = _Outcome(
                        turn.run_id, agent_id, None if assistant_msg_id else _ANSWER_NOT_SAVED
                    )

            if assistant_msg_id:
                await self._emit(
                    "message_saved",
                    {
                        "message_id": assistant_msg_id,
                        "conversation_id": self.current_conversation_id,
                    },
                )

            # Before `complete`, so a client that draws the panel has it while the
            # turn is still on screen. The queue and the email carry the same rows;
            # this is a shortcut for whoever is already looking at the tab.
            if turn.parked:
                await self._emit(
                    "tool_approval_required",
                    {
                        "run_id": str(turn.run_id),
                        "action_requests": [
                            {
                                "id": str(parked.approval_id),
                                "tool_call_id": parked.tool_call_id,
                                "tool_name": parked.tool_name,
                                "args": parked.tool_args,
                                "account": parked.account,
                            }
                            for parked in turn.parked
                        ],
                        # Editing a parked call is not offered: the arguments were
                        # already recorded on the row the approver is deciding
                        # about, and letting the chat rewrite them would mean
                        # approving something other than what was asked.
                        "review_configs": [
                            {"tool_name": parked.tool_name, "allow_edit": False}
                            for parked in turn.parked
                        ],
                    },
                )

            await self._emit(
                "complete",
                {
                    "conversation_id": self.current_conversation_id,
                    # What the turn cost, on the frame that says it is over.
                    # Its own event would be one the client could receive after
                    # `complete` and draw against the next turn.
                    "usage": usage_frame(turn.usage),
                },
            )
        except WebSocketDisconnect:
            raise
        except (AppException, BudgetExceeded, GuardrailBlocked, ToolLoopStopped) as exc:
            # A refusal - an agent that is unpublished, archived, or not theirs
            # to see - a budget stop, and a guardrail block are the platform
            # working, not a crash. The client is told plainly; nothing answers
            # in the named agent's place.
            logger.info("Agent turn refused: %s", exc)
            await self._emit("error", {"message": str(exc)})
            if opened:
                self._outcome = _Outcome(opened[0].run_id, agent_id, str(exc))
        except Exception as exc:
            logger.exception("Error processing agent request")
            await self._emit("error", {"message": _turn_failed(exc)})
            if opened:
                self._outcome = _Outcome(opened[0].run_id, agent_id, _turn_failed(exc))
        finally:
            try:
                # Before the trace ends: its end is what tells the others in the
                # room to re-read the transcript, which must already hold this.
                if not answered:
                    await self._persist_partial_turn(
                        opened,
                        agent_id=agent_id,
                        output=timeline.text,
                        tool_calls=collected_tool_calls,
                        thinking=timeline.thinking,
                        parts=timeline.stored(),
                    )
            finally:
                await self._end_live_turn(steering)

    async def _end_live_turn(self, steering: SteeringInbox) -> None:
        """Close the turn this socket was writing: its trace, and what it held for it."""
        if self._live_turn is not None:
            await live_turn.end(self._live_turn)
        finished, self._live = self._live, None
        self._live_turn = None
        self._current_timeline = None
        self._steering = None
        self._visual_reports = None
        late = steering.unapplied()
        if late:
            # Sent after the agent's last request, so no request carried them.
            # Handed back rather than dropped: the client sends them as the
            # next message.
            with contextlib.suppress(Exception):
                await self._emit("steer_unapplied", {"texts": late})
        if finished is not None and finished == self._room:
            # A teammate's turn begun while this socket wrote its own was
            # not followed then; it is now, from its start.
            await self._follow_if_running(finished)

    async def _tell_the_absent(self, outcome: _Outcome | None) -> None:
        """Notify the person a turn ended without, in the inbox and by email (#2108).

        Nothing when the turn ended with nothing to say - refused before its run
        existed, or parked waiting on somebody - or outside a conversation.
        """
        if outcome is None or self.current_conversation_id is None:
            return
        async with get_db_context() as db:
            run = await agent_run_repo.get_run(
                db, outcome.run_id, organization_id=self.organization_id
            )
            agent = await agent_repo.get(db, outcome.agent_id, organization_id=self.organization_id)
            if run is None or agent is None:  # pragma: no cover - the turn just wrote both
                return
            await NotificationService(db).answered_while_away(
                run,
                agent=agent,
                conversation_id=UUID(self.current_conversation_id),
                error=outcome.error,
            )

    async def _persist_partial_turn(
        self,
        opened: list[OpenedRun],
        *,
        agent_id: UUID,
        output: str,
        tool_calls: list[dict[str, Any]],
        thinking: str | None,
        parts: list[MessagePart] | None,
    ) -> None:
        """Keep what the agent produced on a turn that did not finish.

        A run that failed, hit its budget, was stopped or lost its socket never
        returns a `ChatTurn`, so the write on the success path is skipped and
        everything the model had already streamed was discarded - leaving the run
        in history pointing at a transcript with the question and nothing else.
        That is the run somebody opens.

        Written from the collectors rather than from a result, because there is no
        result: this is the text that reached the client. `usage` is deliberately
        absent - the accounting is on the run row, written by `finish`, and a
        partial figure invented here would disagree with it.

        Nothing is written when nothing was produced. A turn refused before its
        run existed - an unpublished agent, a membership revoked mid-session - has
        an empty `opened` and no output, and a blank assistant message would read
        as the agent having answered with silence.

        A stored timeline counts as produced content: a turn that only asked a
        question and was then stopped before answering has no `output` and no
        tool call, but its `ask_user` part is the whole of what happened and has
        no column to fall back to - so leaving it out of this guard loses it on
        reload (#502).
        """
        if not opened or not (output or tool_calls or parts):
            return
        run = opened[0]
        if self.current_conversation_id is None:
            return
        await persist_assistant_turn(
            self.current_conversation_id,
            output,
            run.model_label,
            tool_calls,
            organization_id=self.organization_id,
            thinking=thinking,
            parts=parts,
            agent_id=agent_id,
            agent_version_id=run.agent_version_id,
            run_id=run.run_id,
            mcp_origins=run.mcp_origins,
        )

    async def _ask_one(self, question: str, options: list[str]) -> str:
        """Put one question to the client and return the answer as a string.

        The shape `AgentDeps.ask_user` promises, and what a delegate's `ask_parent`
        calls. It adapts the one-question protocol to this surface's batch channel -
        a list of one - so the WebSocket keeps a single wire format for one question
        and several, and the delegate reads back the rendered answer.

        **Which delegate asked is read here and nowhere else.** `ask_parent` hands
        over the question and nothing else, but the delegation's state is bound for
        the duration of the delegation - so it is bound in this call, made from
        inside it, and unbound again by the time the answer comes back on the
        receive loop. `None` is the main agent asking the question itself (#1042).
        """
        item = QuestionItem(
            question=question, options=[QuestionChoice(label=option) for option in options]
        )
        asked_by = asking_delegate()
        # **Under the lock, with the round it belongs to.** The frame handler
        # records the answered pair onto the turn's timeline the moment the
        # answer arrives (#502), reading whichever question is marked open - so
        # marking one outside the lock let a second delegate reaching here while
        # the first was still waiting overwrite both fields, and the first
        # delegate's answer was then persisted as the second's question, asked by
        # the second's name. The lock already held the wire round; it holds what
        # names it now too.
        async with self._ask_lock:
            self._pending_questions = [question]
            self._pending_asked_by = asked_by
            try:
                answers = await self._send_and_wait([item.model_dump()])
            finally:
                self._pending_questions = None
                self._pending_asked_by = None
        return render_answer(answers[0] if answers else None)

    async def _ask_questions(self, request: AskUserRequest) -> AskUserResponse:
        """Put an `ask_user` card to the client and return the picks (#2064).

        The same frame and the same lock as a delegate's question, so a card and a
        delegate asking at once queue rather than draw over each other, and the
        answered pairs land on the turn's timeline the moment they arrive.
        """
        async with self._ask_lock:
            self._pending_questions = [question.question for question in request.questions]
            self._pending_asked_by = asking_delegate()
            self._round_parks = self._pending_asked_by is None
            try:
                answers = await self._send_and_wait(wire_questions(request))
            except _LeftUnanswered:
                # The person went away with the card open: the run parks on the
                # call, and answering it later - here or on another device -
                # continues it.
                raise CallDeferred from None
            finally:
                self._pending_questions = None
                self._pending_asked_by = None
                self._round_parks = False
        return answers_to_response(request, answers)

    async def _ask_user(self, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pause the run: ask the client questions and block until they answer.

        Emits an `ask_user` event with the whole batch, then awaits a future the
        frame dispatcher completes when the matching `ask_user_response` arrives.
        The client returns a list of answers parallel to the questions.

        Held under `_ask_lock` so a second round - another delegate's question -
        waits for this one's answer rather than overwriting its future.
        """
        async with self._ask_lock:
            return await self._send_and_wait(questions)

    async def _send_and_wait(self, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """One round on the wire, with `_ask_lock` already held by the caller.

        Split from `_ask_user` so `_ask_one` can take the lock itself and mark
        which question is open *inside* it - the attribution has to be
        serialized with the round it names, and a nested acquire would deadlock.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[list[dict[str, Any]]] = loop.create_future()
        self._ask_user_future = fut
        try:
            await self._emit("ask_user", {"questions": questions})
            return await fut
        finally:
            self._ask_user_future = None

    async def _request_connection(self, request: ConnectionRequest) -> bool:
        """Pause the run: ask the client to connect a service, and wait for the answer.

        Emits `connect_account`, then awaits the future the frame dispatcher
        completes when `connect_account_response` arrives - `connected` true once
        the person says they connected it, false when they skip it. A socket that
        goes away answers false. Under `_ask_lock`, like a question, so a prompt
        from a delegate waits for this one rather than being drawn over it.
        """
        async with self._ask_lock:
            waiting: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._connect_future = waiting
            try:
                await self._emit(
                    "connect_account",
                    {"catalog_key": request.catalog_key, "name": request.name, "gap": request.gap},
                )
                return await waiting
            finally:
                self._connect_future = None

    async def _subagent_event(self, event: SubagentEvent) -> None:
        """Forward one frame from inside a delegation, under the frame's own name.

        The wire `type` *is* the frame's `kind` rather than a name chosen here.
        Two spellings of one frame - the literal in the union and a string in this
        method - is a drift nothing would catch: the client would keep switching on
        a case the server had stopped sending, and a delegation would simply not
        appear. `kind` stays in the payload as well, so the client narrows the
        object it already parsed instead of re-deriving the discriminator from the
        envelope.

        `cost_usd` crosses as the Decimal string Pydantic serialises it to in JSON
        mode - the same shape `usage_report.usage_frame` and every REST surface
        report a cost in, so a delegation's share arrives in the shape the client
        already parses everywhere else (#545).

        Nothing is awaited on the client's behalf: `send_event` answers `False` on
        a closed socket rather than raising, so a background delegation whose
        frames outlive the tab does not take the run down with it.
        """
        await self._emit(event.kind, event.model_dump(mode="json"))

    async def _compaction_event(self, event: CompactionEvent) -> None:
        """Forward one frame from a summary in progress, under the frame's own name.

        The wire `type` *is* the frame's `kind`, for the reason
        :meth:`_subagent_event` gives: two spellings of one frame is a drift
        nothing catches, and the client would keep waiting on a case the server
        had stopped sending.

        Nothing is awaited on the client's behalf - `send_event` answers `False`
        on a closed socket rather than raising, so a tab that went away mid-summary
        does not take the run down with it.
        """
        frame = event.model_dump(mode="json")
        await self._emit(event.kind, frame)

    async def _visual_images(self, tool_call_id: str, images: Mapping[str, str]) -> None:
        """A drawing's images, for the tab about to render it (#2171)."""
        await send_event(
            self.websocket, "visual_images", {"tool_call_id": tool_call_id, "images": dict(images)}
        )

    async def _browser_event(self, event: BrowserEvent) -> bool:
        """Forward one frame from a browse in progress, under the frame's own name.

        The wire `type` *is* the frame's `kind`, for the reason
        :meth:`_subagent_event` gives.

        A `browser_frame` carries a JPEG as a data URL and is the largest thing
        this socket sends. It is still sent one frame at a time and awaited, which
        is deliberate back-pressure: a socket that cannot keep up slows the browse
        rather than growing a queue of screenshots behind it.

        **The answer is returned rather than discarded.** `send_event` reports
        `False` on a closed socket instead of raising, and a detached turn keeps
        running on purpose - so a browse whose reader closed the tab would go on
        capturing and encoding a picture per step for nobody. Handing the `False`
        back is what lets the loop stop taking them and carry on browsing.

        Returns:
            Whether the frame reached the client.
        """
        return await self._emit(event.kind, event.model_dump(mode="json"))

    async def _sandbox_wait_event(self, preparing: bool) -> None:
        """Say the run's sandbox is still being opened, and then that it is not (#2222).

        The first session after an update builds the runtime's image on the host,
        minutes in which nothing streams. The console shows a notice above the
        composer from `sandbox_preparing` until `sandbox_ready`, an error or the
        end of the turn.
        """
        await self._emit("sandbox_preparing" if preparing else "sandbox_ready", {})

    async def _personal_gaps_event(self, gaps: list[PersonalServiceGap]) -> None:
        """Say which of the agent's personal services this person cannot reach yet.

        Sent once per turn, before the model answers, so the chat can draw a card
        with the button that connects the account while the agent is still
        saying it cannot. The model is told the same thing in its instructions;
        this is the half a person can click. Not persisted: it is true of this
        person at this moment, and a transcript reopened after they connected
        would be wrong to repeat it.
        """
        frame = {"services": [gap.model_dump(mode="json") for gap in gaps]}
        await self._emit("personal_services_unavailable", frame)

    async def _remember_context(self, turn: ChatTurn) -> None:
        """Record what this turn learned about the thread's own context.

        The summary it produced, so the next turn starts from it rather than
        buying another; and what a request here carries before a single message,
        so the next turn can tell a window with no room for a summary from one
        that works before it has a response of its own to measure.

        After the turn's own rows, never before: what is stored beside the
        history is how far it reaches, and reaching short of the answer would
        replay that answer twice.

        Its own session because the turn's has been committed and closed by the
        time this runs, and its own for a second reason - a failure to record
        either must cost the record, not the answer somebody is reading.
        """
        if turn.summarized_history is None and turn.overhead_tokens is None:
            return
        # Called from inside the branch that has one, which is also the branch
        # that has just written the rows this is measured against.
        conversation_id = UUID(str(self.current_conversation_id))
        async with get_db_context() as db:
            conversations = ConversationService(db)
            if turn.summarized_history is not None:
                await conversations.keep_summary(conversation_id, turn.summarized_history)
            if turn.overhead_tokens is not None:
                await conversations.keep_overhead(conversation_id, turn.overhead_tokens)

    async def _history(self, prompt_message_id: UUID | None) -> list[ModelMessage]:
        """What has already been said in this thread, without the turn being run.

        **The summary counts as what was said.** Where one has run, the thread
        starts from the history it reduced the older turns to rather than from
        the transcript, which is what stops the next turn buying the same summary
        again (#49) - see `ConversationService.model_history`.

        **Read from the database, not from this session.** It used to be a list on
        the socket, appended to as turns went by and loaded from nowhere - so a
        conversation the socket did not itself produce had no history at all. A
        page reload, a second tab, or a dropped connection was enough: the person
        was looking at the whole thread on screen while the model was handed an
        empty one, and the agent answered the follow-up as though the
        conversation had started with it. Nothing errored, and the symptom reads
        as the agent forgetting rather than as the platform not telling it (#771).

        The prompt is excluded by id because it is already a row by the time this
        runs - `persist_user_turn` writes it before the run so a message nothing
        answers is still in the transcript. Handing it back as history *and* as
        the prompt would ask the model the same question twice.

        Read on its own session, like `_attached_files`: the turn's session is
        opened later and held for the run, and this is a lookup rather than part
        of that unit of work.

        The repository call carries no tenant predicate, which is safe here for
        one reason only: `current_conversation_id` is what `persist_user_turn`
        resolved a moment ago, and that refuses a conversation belonging to
        another organization before anything is written. The id never arrives
        here as the client sent it. The channel router and the embed session read
        their history unscoped on the same grounds.
        """
        if self.current_conversation_id is None:
            return []
        async with get_db_context() as db:
            return await ConversationService(db).model_history(
                UUID(self.current_conversation_id),
                limit=HISTORY_MESSAGES,
                exclude_message_id=prompt_message_id,
            )

    async def _attached_files(self, message_id: UUID | None, file_ids: list[Any]) -> list[ChatFile]:
        """The rows for the files this turn attached (#1756).

        Read on their own session: the turn's own session is opened later and
        held for the run, and this is a lookup rather than part of that unit of
        work. Read by id and kept where the row is linked to this turn's message
        or still unlinked: `persist_user_turn` has already linked the frame's ids
        (and enforced ownership, #706), so re-validating them as unlinked would
        reject the turn's own just-linked files - while a file its best-effort
        link left unlinked must still reach the model rather than be dropped.
        """
        async with get_db_context() as file_db:
            return await load_turn_attachments(
                file_db, message_id, [str(file_id) for file_id in file_ids], user_id=self.user.id
            )

    async def _emit(self, kind: str, payload: Any) -> bool:
        """Send one frame to this socket, and keep it for whoever follows the turn.

        Kept even when the socket is gone, which is the point: a person who left
        and came back follows the rest of the turn from another socket. Answers
        whether this socket took it, as `send_event` does.
        """
        sent = await send_event(self.websocket, kind, payload)
        if self._live_turn is not None:
            await live_turn.publish(self._live_turn, kind, payload)
        return sent

    async def _attach(self, raw: object) -> None:
        """Follow the turn running in a conversation the person may read, from its start.

        The person came back to a conversation whose agent is still answering -
        from another chat, another tab, a reloaded page. The turn's frames so far
        are sent as they were, then the rest as they come, so the answer is drawn
        exactly as it would have been. Nothing happens for a conversation with no
        turn running, one this socket is itself answering, or one they may not
        read - which is answered as nothing rather than as a refusal, so it says
        nothing about a conversation they cannot see.
        """
        self._stop_following()
        conversation_id = _conversation_id(raw)
        if conversation_id is None:
            await self._leave_room()
            return
        async with get_db_context() as db:
            try:
                await ConversationService(db).get_conversation(
                    UUID(conversation_id),
                    organization_id=self.organization_id,
                    user_id=self.user.id,
                    include_favourite=False,
                )
            except NotFoundError:
                await self._leave_room()
                return
        await self._enter_room(conversation_id)
        await self._follow_if_running(conversation_id)

    async def _follow_if_running(self, conversation_id: str) -> None:
        """Follow the turn being written in the conversation, unless this socket writes it.

        One follower at a time: a turn somebody begins while another is followed
        is taken up when that one ends, by `_follow` itself.
        """
        if self._closed or conversation_id == self._live or self._following():
            return
        token = await live_turn.live_token(conversation_id)
        # Asked again past the await: the socket may have closed, this socket
        # begun its own turn there, or another path started a follower meanwhile -
        # two followers would draw the same turn twice.
        if token is None or self._closed or conversation_id == self._live or self._following():
            return
        if conversation_id != self._room:
            # Left for another conversation, or for none, while asking.
            return
        self._follower = asyncio.create_task(self._follow(conversation_id, token))

    def _following(self) -> bool:
        return self._follower is not None and not self._follower.done()

    async def _enter_room(self, conversation_id: str) -> None:
        """Be one of the people with this conversation open, and hear what happens in it."""
        if self._closed or self._room == conversation_id:
            return
        await self._leave_room()
        self._room = conversation_id
        # Found readable for the last room, not this one.
        self._reads_until = float("-inf")
        await chat_room.join(conversation_id, self.user.id, self._socket)
        if self._closed or self._room != conversation_id:
            # `shutdown` - or another room - came in while joining, and its leave
            # ran before this join landed: undo it rather than stay counted.
            await chat_room.leave(conversation_id, self.user.id, self._socket)
            return
        self._room_task = asyncio.create_task(self._in_room(conversation_id))

    async def _leave_room(self) -> None:
        # A turn followed in the room is the room's: leaving stops drawing it.
        self._stop_following()
        room, task = self._room, self._room_task
        self._room, self._room_task = None, None
        if task is not None and not task.done():
            task.cancel()
        if room is not None:
            await chat_room.leave(room, self.user.id, self._socket)

    async def _in_room(self, conversation_id: str) -> None:
        """Keep this socket counted as here, and pass on the room's news.

        Who is here goes to the person as a `presence` frame; a turn somebody
        else began is followed like one they came back to, so a teammate's
        question and its answer appear as they are written.

        Access is asked again before each piece of news is passed on: the check
        at `attach` ran once, and a person removed from the organization or the
        project since must stop hearing the room - the socket of somebody idle
        sends no frame that would re-check it otherwise.
        """
        heartbeat = asyncio.create_task(self._heartbeat(conversation_id))
        try:
            while True:
                try:
                    await self._hear_room(conversation_id)
                except Exception:
                    # Redis went away under the subscription. The socket stays
                    # open and still in this room, so it listens again rather
                    # than stay deaf - and uncounted - until a reload.
                    logger.warning("chat_room_listen_failed", exc_info=True)
                    await asyncio.sleep(ROOM_RETRY_SECONDS)
                    # Asked again before going back in: access may have gone while
                    # Redis was away, and rejoining shows who is here at once.
                    if not await self._still_reads(conversation_id):
                        self._stop_following()
                        self._room = self._room_task = None
                        with contextlib.suppress(Exception):
                            await chat_room.leave(conversation_id, self.user.id, self._socket)
                        return
                    with contextlib.suppress(Exception):
                        await chat_room.join(conversation_id, self.user.id, self._socket)
                else:
                    return
        finally:
            heartbeat.cancel()

    async def _hear_room(self, conversation_id: str) -> None:
        """Pass on the room's news until it ends or this person may no longer read it."""
        await self._send_presence(conversation_id)
        async for event in chat_room.events(conversation_id):
            if not await self._reads_lately(conversation_id):
                self._stop_following()
                self._room = self._room_task = None
                await chat_room.leave(conversation_id, self.user.id, self._socket)
                return
            if event["type"] == chat_room.PRESENCE:
                await self._send_presence(conversation_id)
            elif event["type"] == chat_room.TYPING:
                await self._send_typing(conversation_id, event.get("by"))
            else:
                await self._follow_if_running(conversation_id)

    async def _reads_lately(self, conversation_id: str) -> bool:
        """`_still_reads`, answered from the last time it said yes when that was lately."""
        if time.monotonic() < self._reads_until:
            return True
        if not await self._still_reads(conversation_id):
            return False
        self._reads_until = time.monotonic() + ROOM_READS_FOR_SECONDS
        return True

    async def _still_reads(self, conversation_id: str) -> bool:
        """Whether this person may still read the conversation, as of now.

        Their credential first: a revoked session or a suspended account keeps
        its membership and its access, and an idle socket sends no frame that
        would re-check it - so the room's news re-checks it, and closes the
        socket on refusal as an inbound frame would.
        """
        if not await self._reauthorize():
            return False
        async with get_db_context() as db:
            if (
                await member_repo.get(
                    db, organization_id=self.organization_id, user_id=self.user.id
                )
                is None
            ):
                return False
            try:
                await ConversationService(db).get_conversation(
                    UUID(conversation_id),
                    organization_id=self.organization_id,
                    user_id=self.user.id,
                    include_favourite=False,
                )
            except NotFoundError:
                return False
        return True

    async def _heartbeat(self, conversation_id: str) -> None:
        while True:
            await asyncio.sleep(chat_room.HEARTBEAT_SECONDS)
            await chat_room.join(conversation_id, self.user.id, self._socket)

    async def _send_typing(self, conversation_id: str, by: object) -> None:
        """Say somebody else in the room is writing a message - never this person."""
        try:
            person_id = UUID(str(by))
        except ValueError:
            return
        if person_id == self.user.id:
            return
        async with get_db_context() as db:
            people = await conversation_repo.users_by_id(db, {person_id})
        person = people.get(person_id)
        if person is None:
            return
        await send_event(
            self.websocket,
            "typing",
            {
                "conversation_id": conversation_id,
                "person": ChatPerson.of(person).model_dump(mode="json"),
            },
        )

    async def _send_presence(self, conversation_id: str) -> None:
        here = await chat_room.present(conversation_id)
        if not here:
            # Not even this socket: no Redis to count anybody, so nothing to say.
            return
        async with get_db_context() as db:
            people = await conversation_repo.users_by_id(db, here)
        await send_event(
            self.websocket,
            "presence",
            {
                "conversation_id": conversation_id,
                "people": [
                    ChatPerson.of(person).model_dump(mode="json")
                    for person in sorted(people.values(), key=lambda p: str(p.full_name or p.email))
                ],
            },
        )

    async def _follow(self, conversation_id: str, token: str) -> None:
        """Forward the conversation's running turns, one after another, until none is.

        A teammate's turn begun while another was followed found this follower
        busy and was not taken up then; so when a turn ends, the conversation is
        asked again, and the newer turn is followed from its start.

        A failure ends the following, not the socket: it is logged, and the tab
        is told the turn is over so it re-reads the transcript rather than spin.
        """
        try:
            while await self._follow_one(conversation_id, token):
                newer = await live_turn.live_token(conversation_id)
                if newer is None or newer == token or conversation_id == self._live:
                    return
                token = newer
        except Exception:
            logger.warning("chat_follow_failed", exc_info=True)
            await send_event(self.websocket, live_turn.END, {"conversation_id": conversation_id})

    async def _follow_one(self, conversation_id: str, token: str) -> bool:
        """Forward one turn's frames until it ends, then say it has.

        Whether to go on following the conversation: not when the socket closed
        or the person may no longer read it.
        """
        await send_event(self.websocket, "turn_attached", {"conversation_id": conversation_id})
        ended = False
        recheck = time.monotonic() + RECHECK_SECONDS
        async for frame in live_turn.follow(conversation_id, token):
            ended = frame["type"] == live_turn.END
            # A long turn is asked about again as it goes: somebody removed from
            # the project mid-answer must not read the rest of it.
            if time.monotonic() >= recheck and not ended:
                if not await self._still_reads(conversation_id):
                    await send_event(
                        self.websocket, live_turn.END, {"conversation_id": conversation_id}
                    )
                    return False
                recheck = time.monotonic() + RECHECK_SECONDS
            if not await send_event(self.websocket, frame["type"], frame["data"]):
                return False
        if not ended:
            # The turn ended between the check and the subscription: the
            # follower still needs to hear it is over.
            return await send_event(
                self.websocket, live_turn.END, {"conversation_id": conversation_id}
            )
        return True

    def _stop_following(self) -> None:
        follower = self._follower
        self._follower = None
        if follower is not None and not follower.done():
            follower.cancel()

    async def _frame(self, kind: str, payload: dict[str, Any]) -> None:
        """Where this surface's frames go: to the member who is watching.

        The sink `RunFrames` is handed. Unfiltered, because a signed-in member of
        the organization that owns the agent may see everything it did - which is
        exactly the decision a public surface makes differently.
        """
        await self._emit(kind, payload)


def _conversation_id(raw: object) -> str | None:
    """A conversation id off the wire, canonical, or `None` for anything that is not one."""
    if not isinstance(raw, str):
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


def _wire_text(raw: object) -> str | None:
    """A frame's id field as text, or `None` for an empty or non-text one.

    Checked before anything parses it: a number or an object where an id
    belongs raised past the turn's refusal handling, and the client waited for
    an answer that was never coming.
    """
    return raw if isinstance(raw, str) and raw else None
