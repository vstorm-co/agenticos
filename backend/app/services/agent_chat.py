"""Chatting with an agent someone published.

The chat WebSocket has always talked to the generated template's general
assistant. That left the Builder half-connected: you could publish an agent,
bind collections, skills and a budget to it, and then the only place to talk to
it was the Playground or the API.

A frame carrying `agent_id` runs that agent instead. A frame without one keeps
the general assistant, because the two are different products - "the company's
chat" and "the agent Sales published". There is deliberately no per-organization
default: the client names the agent, or it gets the assistant it always got.
Guessing here would mean a user asking one thing and something else answering.

What this module owns is the part a streaming surface must not improvise: who a
run belongs to, and the accounting around it. It goes through
:meth:`AgentRunnerService.prepare` and :meth:`AgentRunnerService.finish` exactly
as the public API and the Slack bot do, so a chat run lands in run history with
its cost, its budget check, its approval gate and its capabilities - stamped
`RunSurface.WEB`. What it does not own is the event loop: the caller iterates
the run and forwards events, because only the caller knows what a frame is.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, UserContent
from pydantic_ai.run import AgentRun, AgentRunResult
from pydantic_ai.tools import DeferredToolRequests
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope
from app.agents.deps import AgentDeps, AskUserCallback
from app.agents.subagent_events import SubagentEventSink
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.chat_file import ChatFile
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_repo, member_repo
from app.services.agent_runner import (
    AgentRunnerService,
    ParkedApproval,
    PausedRunState,
    PreparedRun,
)
from app.services.attachments import AttachmentRouter
from app.services.usage_report import UsageReport, UsageReportService

logger = logging.getLogger(__name__)

# Iterating the run is the caller's job; this is how it is handed back the
# iterator. Typed against the agent the factory builds, so a surface that
# forwards events cannot quietly be given a different kind of run.
type ChatStream = Callable[[AgentRun[AgentDeps, str | DeferredToolRequests]], Awaitable[None]]

# Said to someone chatting in an organization they no longer belong to. Their
# socket was authenticated against that organization at connect time, so this is
# a membership revoked mid-session rather than a spoofed frame - but a run with
# no membership has no role, and a run with no role has none of the checks a
# role implies.
_NOT_A_MEMBER = "You are no longer a member of this organization."

# What the person is told when the run stopped on an approval instead of an
# answer. Silence would read as the agent ignoring them, and the run does not
# continue in this conversation - it continues when somebody decides, from the
# approvals queue.
_AWAITING_APPROVAL = (
    "This run needs approval before it can go further - it is waiting in the approvals queue."
)


def requested_agent_id(frame: Mapping[str, Any]) -> UUID | None:
    """Which published agent a chat frame is addressed to, if any.

    `None` means the general assistant, which is what a client that knows
    nothing about published agents sends. An empty value means the same: the
    client had no agent selected.

    Raises:
        BadRequestError: If the frame names something that is not an agent id.
            Ignoring it would run the general assistant in place of the agent
            the user picked, which is the one outcome worth failing for.
    """
    raw = frame.get("agent_id")
    if raw is None or raw == "":
        return None
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise BadRequestError(
            message="That is not a valid agent id", details={"agent_id": str(raw)}
        ) from exc


def requested_model_profile_id(frame: Mapping[str, Any]) -> UUID | None:
    """Which of the organization's models this turn should run on, if overridden.

    `None` means the agent runs on the model its spec names, which is the
    normal case and what a client that sends nothing gets.

    Raises:
        BadRequestError: If the frame names something that is not a profile id.
            Falling back to the agent's own model would answer on a model the
            person did not choose and say nothing about it.
    """
    raw = frame.get("model_profile_id")
    if raw is None or raw == "":
        return None
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise BadRequestError(
            message="That is not a valid model id", details={"model_profile_id": str(raw)}
        ) from exc


def requested_environment_id(frame: Mapping[str, Any]) -> UUID | None:
    """Which named environment this turn should run, if any.

    `None` means the default environment - what every chat turn has always
    gotten, and what a client that knows nothing about environments sends.

    Raises:
        BadRequestError: If the frame names something that is not an
            environment id. Falling back to the default would run a version
            the person did not pick and say nothing about it.
    """
    raw = frame.get("environment_id")
    if raw is None or raw == "":
        return None
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise BadRequestError(
            message="That is not a valid environment id", details={"environment_id": str(raw)}
        ) from exc


def _outcome(
    agent_run: AgentRun[AgentDeps, str | DeferredToolRequests],
) -> AgentRunResult[str | DeferredToolRequests]:
    """What the iterated run ended with.

    Raises:
        RuntimeError: If it ended without a result. That is not a state the
            agent can reach on its own - it means whoever drove the loop stopped
            early - so it fails loudly and is recorded as a failed run, rather
            than being persisted as an empty answer.
    """
    if agent_run.result is None:
        raise RuntimeError("The agent run ended without a result")
    return agent_run.result


def display_output(output: str | DeferredToolRequests) -> str:
    """The text to show for whatever a run ended with.

    A run can end without an answer: when the approval gate parks a
    side-effecting call, Pydantic AI ends the run with the calls waiting on a
    human. There is no model text to show then, and the object itself is not
    something a client can render.
    """
    return output if isinstance(output, str) else _AWAITING_APPROVAL


@dataclass(frozen=True)
class OpenedRun:
    """The run row, handed to the surface the moment it exists.

    A streaming surface persists the answer itself, and until this existed it
    could only do so for a turn that *finished*: everything it needs arrives on
    `ChatTurn`, and a run that failed, was stopped by a budget or was cancelled
    mid-stream never returns one. So the text the model had already streamed was
    thrown away, and the run row in history pointed at a transcript holding the
    question and nothing else - on exactly the runs somebody opens.

    Three fields rather than the run row itself: a surface has no business
    reaching into a `PreparedRun`, and these are what attributing a partial
    answer takes.
    """

    run_id: UUID
    model_label: str
    agent_version_id: UUID | None


@dataclass(frozen=True)
class ChatTurn:
    """What one published-agent turn produced, for the surface to persist."""

    output: str
    model_label: str
    agent_id: UUID
    agent_version_id: UUID | None
    """The frozen spec that answered. None only for an agent with no version,
    which cannot run - carried rather than assumed so the transcript records
    what actually happened."""

    run_id: UUID | None = None
    """The run these approvals belong to, for resuming it once they are decided."""

    parked: tuple[ParkedApproval, ...] = ()
    """Tool calls this turn stopped on, if it stopped.

    Present so the surface can put the decision in front of whoever is already
    looking, instead of only naming a queue. The queue stays the record - these
    are the same rows - so a decision made here and one made there are the same
    decision.
    """

    usage: UsageReport | None = None
    """What the turn cost, and how full its workspace is.

    Built after `finish`, because that is what writes the tokens and the cost to
    the run row - reading it earlier would report a turn as free. `None` only when
    assembling it failed, which is deliberately not allowed to lose an answer
    somebody is waiting for.
    """


def _as_text(user_input: str | Sequence[UserContent]) -> str:
    """The text half of a prompt a surface may already have assembled.

    Surfaces hand this a plain string today. The signature allows the richer
    shape because Pydantic AI does, and a caller passing one would otherwise
    have its attachments silently appended to a `repr`.
    """
    if isinstance(user_input, str):
        return user_input
    return "".join(part for part in user_input if isinstance(part, str))


class ChatAgentRunner:
    """Runs a published agent for one turn of a streaming chat."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runner = AgentRunnerService(db)
        self.usage = UsageReportService(db)

    async def run(
        self,
        *,
        user: User,
        organization_id: UUID,
        agent_id: UUID,
        user_input: str | Sequence[UserContent],
        message_history: list[ModelMessage],
        attachments: list[ChatFile] | None = None,
        conversation_id: UUID | None,
        prompt_message_id: UUID | None = None,
        ask_user: AskUserCallback,
        stream: ChatStream,
        on_run_open: Callable[[OpenedRun], None] | None = None,
        subagent_events: SubagentEventSink | None = None,
        model_profile_id: UUID | None = None,
        environment_id: UUID | None = None,
    ) -> ChatTurn:
        """Run the named agent for this turn and record what it consumed.

        Args:
            user: The connected account. The run belongs to them.
            organization_id: The organization the socket is active in; the agent
                is resolved here and nowhere else.
            agent_id: The published agent the frame named.
            user_input: The prompt. Attachments are *not* folded in by the
                surface - see `attachments`.
            attachments: Files the user attached, routed once the workspace is
                known. It has to happen here rather than in the surface: where a
                file goes depends on whether this agent has a workspace, and
                that is decided by `prepare`, which has not run yet when a
                surface is assembling its prompt.
            message_history: The conversation so far, in Pydantic AI's format.
            conversation_id: The chat thread, so the run is findable from it.
            prompt_message_id: The row the surface already wrote the prompt to.
                Linked to the run as soon as `prepare` opens one, which is what
                puts the question in the run's own transcript. The surface writes
                it first and hands the id here rather than waiting, because a
                build that refuses must not lose what somebody typed - and that
                refusal happens inside `prepare`.
            ask_user: How the agent puts a question to the person who is sitting
                there. Only a live surface can offer this.
            stream: Iterates the run and forwards its events to the client.
            on_run_open: Told the run row as soon as `prepare` has opened one,
                so a surface can persist what it streamed even when this method
                raises. Everything it would otherwise use arrives on `ChatTurn`,
                and a run that failed, hit its budget or was cancelled produces
                none - which is how a failed chat run came to keep the question
                and lose the half-written answer.
            subagent_events: Where a delegation's frames go, for a surface that
                can draw one. Defaults to `None`, and the default is load-bearing
                rather than convenient: attaching a handler makes the library open
                a *streamed* request for every child, so a delegate whose provider
                cannot stream works from the API and breaks the moment somebody
                watches it. A surface passes this only if it can show the frames.

        Returns:
            The answer to show and persist, and the model that produced it. A
            run parked on an approval returns the queue's explanation instead of
            an answer - it did not fail, and it has not finished either.

        Raises:
            AuthorizationError: If the user is not a member of this organization.
            NotFoundError: If no agent here has that id, or they may not see it.
            BadRequestError: If the agent is unpublished or archived.
            BudgetExceeded: If a limit stopped the run. Surfaced rather than
                swallowed so the client can say why the answer stopped.
        """
        ctx = await self._context(user, organization_id)
        prepared = await self.runner.prepare(
            ctx,
            agent_id,
            surface=RunSurface.WEB,
            conversation_id=conversation_id,
            user_name=user.full_name,
            model_profile_id=model_profile_id,
            # The version this environment pins runs instead of the default -
            # how a dev environment is exercised from the chat before promotion.
            environment_id=environment_id,
        )
        # The approval channel was wired by `prepare`; these are the halves only a
        # live surface can provide. Without `ask_user`, an agent whose instructions
        # tell it to ask first has no way to ask; without `subagent_events`, a
        # delegation is a tool call named `task` that goes quiet for thirty seconds.
        prepared.deps.ask_user = ask_user
        prepared.deps.subagent_events = subagent_events

        # Before the run, not after: this run may fail, park or be cancelled, and
        # a transcript that holds the answer but not the question is the one shape
        # a reader cannot interpret.
        if prompt_message_id is not None and conversation_id is not None:
            await conversation_repo.link_message_to_run(
                self.db,
                message_id=prompt_message_id,
                run_id=prepared.run.id,
                conversation_id=conversation_id,
            )
        if on_run_open is not None:
            on_run_open(
                OpenedRun(
                    run_id=prepared.run.id,
                    model_label=prepared.built.model_label,
                    agent_version_id=prepared.run.agent_version_id,
                )
            )

        if attachments:
            router = AttachmentRouter(
                prepared.workspace.backend if prepared.workspace is not None else None
            )
            user_input = await router.build_prompt(_as_text(user_input), attachments)

        status = RunStatus.FAILED
        error: str | None = None
        paused: PausedRunState | None = None
        budget_scope: BudgetScope | None = None
        output = ""
        try:
            async with prepared.built.agent.iter(
                user_input,
                deps=prepared.deps,
                message_history=message_history,
                usage_limits=prepared.built.usage_limits,
            ) as agent_run:
                await stream(agent_run)

            result = _outcome(agent_run)
            if isinstance(result.output, DeferredToolRequests):
                paused = PausedRunState(
                    messages=ModelMessagesTypeAdapter.dump_python(
                        result.all_messages(), mode="json"
                    ),
                    tool_call_ids=prepared.approvals.parked,
                )
                status = RunStatus.AWAITING_APPROVAL
            else:
                status = RunStatus.COMPLETED
            output = display_output(result.output)
        except asyncio.CancelledError:
            # The user pressed stop, or the socket went away mid-run. Cancelled
            # is not failed, and the tokens spent up to here were still spent.
            status = RunStatus.CANCELLED
            raise
        except BudgetExceeded as exc:
            # Not a malfunction - the platform working - and recorded as its own
            # status so an operator filtering for problems does not wade through
            # it. Raised on rather than swallowed because somebody is sitting
            # there waiting, and they are owed the reason the answer stopped.
            status = RunStatus.BUDGET_EXCEEDED
            error = str(exc)
            budget_scope = exc.scope
            logger.info("Chat run %s stopped by budget: %s", prepared.run.id, exc)
            raise
        except Exception as exc:
            error = str(exc)
            logger.exception("Chat run %s failed", prepared.run.id)
            raise
        finally:
            await self.runner.finish(
                prepared,
                status=status,
                error=error,
                paused_state=paused,
                budget_scope=budget_scope,
            )
            # Committed here rather than left to the session context: that exit
            # rolls back on any exception, and cancellation never reaches it at
            # all, since `CancelledError` is not an `Exception`. A run that
            # failed, was stopped or ran out of budget still spent money, and a
            # run missing from history is a run nobody is accountable for.
            await self.db.commit()

        return ChatTurn(
            output=output,
            model_label=prepared.built.model_label,
            agent_id=prepared.agent.id,
            agent_version_id=prepared.run.agent_version_id,
            run_id=prepared.run.id,
            parked=tuple(prepared.approvals.requested),
            usage=await self._usage(ctx, prepared),
        )

    async def _usage(self, ctx: AuthContext, prepared: PreparedRun) -> UsageReport | None:
        """What this turn cost, for the chat to show.

        Always includes the workspace: a person watching an agent work is exactly
        who wants to know the scratch space is nearly full, and unlike a channel
        there is no noise argument against saying so - the client decides whether
        to draw it.

        Never raises. The answer has already been produced and committed; losing
        it to a failed accounting read would be the worst possible trade.
        """
        try:
            return await self.usage.for_run(
                ctx,
                prepared.run,
                period_spend_usd=await self.runner.monthly_spend(ctx),
                budget_usd=await self._budget(ctx),
                # The agent's own cap as well: it is the one whoever is looking at
                # this agent can actually raise, and reporting only the
                # organization's tells an author nothing they can act on.
                agent_spend_usd=await self.runner.monthly_spend(ctx, agent_id=prepared.agent.id),
                agent_budget_usd=(
                    None
                    if prepared.spec.budget is None
                    else self._as_decimal(prepared.spec.budget.monthly_usd)
                ),
                include_sandbox=True,
            )
        except Exception:
            logger.warning("chat_usage_report_failed", extra={"run_id": str(prepared.run.id)})
            return None

    @staticmethod
    def _as_decimal(value: float | None) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    async def _budget(self, ctx: AuthContext) -> Decimal | None:
        organization = await self.db.get(Organization, ctx.organization_id)
        return None if organization is None else organization.monthly_budget_usd

    async def _context(self, user: User, organization_id: UUID) -> AuthContext:
        """The connected user's standing in the organization they are chatting in.

        Read from the membership row for the same reason the Slack router reads
        it: a run takes a subject, and the subject is the person who typed -
        never the organization and never nobody. A socket that outlives the
        membership stops being able to run agents at that moment.
        """
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=user.id
        )
        if membership is None:
            raise AuthorizationError(
                message=_NOT_A_MEMBER, details={"org_id": str(organization_id)}
            )
        return AuthContext(
            user_id=user.id,
            organization_id=organization_id,
            role=membership.role,
        )
