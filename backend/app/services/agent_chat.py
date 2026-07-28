"""Chatting with an agent someone published.

The chat WebSocket has always talked to the generated template's general
assistant. That left the Builder half-connected: you could publish an agent,
bind collections, skills and a budget to it, and then the only place to talk to
it was the Playground or the API.

A frame carrying ``agent_id`` runs that agent instead. A frame without one keeps
the general assistant, because the two are different products — "the company's
chat" and "the agent Sales published". There is deliberately no per-organization
default: the client names the agent, or it gets the assistant it always got.
Guessing here would mean a user asking one thing and something else answering.

What this module owns is the part a streaming surface must not improvise: who a
run belongs to, and the accounting around it. It goes through
:meth:`AgentRunnerService.prepare` and :meth:`AgentRunnerService.finish` exactly
as the public API and the Slack bot do, so a chat run lands in run history with
its cost, its budget check, its approval gate and its capabilities — stamped
``RunSurface.WEB``. What it does not own is the event loop: the caller iterates
the run and forwards events, because only the caller knows what a frame is.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, UserContent
from pydantic_ai.run import AgentRun, AgentRunResult
from pydantic_ai.tools import DeferredToolRequests
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetExceeded
from app.agents.deps import AgentDeps, AskUserCallback
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.user import User
from app.repositories import member_repo
from app.services.agent_runner import AgentRunnerService, PausedRunState

logger = logging.getLogger(__name__)

# Iterating the run is the caller's job; this is how it is handed back the
# iterator. Typed against the agent the factory builds, so a surface that
# forwards events cannot quietly be given a different kind of run.
type ChatStream = Callable[[AgentRun[AgentDeps, str | DeferredToolRequests]], Awaitable[None]]

# Said to someone chatting in an organization they no longer belong to. Their
# socket was authenticated against that organization at connect time, so this is
# a membership revoked mid-session rather than a spoofed frame — but a run with
# no membership has no role, and a run with no role has none of the checks a
# role implies.
_NOT_A_MEMBER = "You are no longer a member of this organization."

# What the person is told when the run stopped on an approval instead of an
# answer. Silence would read as the agent ignoring them, and the run does not
# continue in this conversation — it continues when somebody decides, from the
# approvals queue.
_AWAITING_APPROVAL = (
    "This run needs approval before it can go further — it is waiting in the approvals queue."
)


def requested_agent_id(frame: Mapping[str, Any]) -> UUID | None:
    """Which published agent a chat frame is addressed to, if any.

    ``None`` means the general assistant, which is what a client that knows
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

    ``None`` means the agent runs on the model its spec names, which is the
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


def _outcome(
    agent_run: AgentRun[AgentDeps, str | DeferredToolRequests],
) -> AgentRunResult[str | DeferredToolRequests]:
    """What the iterated run ended with.

    Raises:
        RuntimeError: If it ended without a result. That is not a state the
            agent can reach on its own — it means whoever drove the loop stopped
            early — so it fails loudly and is recorded as a failed run, rather
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
class ChatTurn:
    """What one published-agent turn produced, for the surface to persist."""

    output: str
    model_label: str
    agent_id: UUID
    agent_version_id: UUID | None
    """The frozen spec that answered. None only for an agent with no version,
    which cannot run — carried rather than assumed so the transcript records
    what actually happened."""


class ChatAgentRunner:
    """Runs a published agent for one turn of a streaming chat."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runner = AgentRunnerService(db)

    async def run(
        self,
        *,
        user: User,
        organization_id: UUID,
        agent_id: UUID,
        user_input: str | Sequence[UserContent],
        message_history: list[ModelMessage],
        conversation_id: UUID | None,
        ask_user: AskUserCallback,
        stream: ChatStream,
        model_profile_id: UUID | None = None,
    ) -> ChatTurn:
        """Run the named agent for this turn and record what it consumed.

        Args:
            user: The connected account. The run belongs to them.
            organization_id: The organization the socket is active in; the agent
                is resolved here and nowhere else.
            agent_id: The published agent the frame named.
            user_input: The prompt, images and file text already assembled by
                the surface.
            message_history: The conversation so far, in Pydantic AI's format.
            conversation_id: The chat thread, so the run is findable from it.
            ask_user: How the agent puts a question to the person who is sitting
                there. Only a live surface can offer this.
            stream: Iterates the run and forwards its events to the client.

        Returns:
            The answer to show and persist, and the model that produced it. A
            run parked on an approval returns the queue's explanation instead of
            an answer — it did not fail, and it has not finished either.

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
        )
        # The approval channel was wired by ``prepare``; this is the half only a
        # live surface can provide. Without it, an agent whose instructions tell
        # it to ask first has no way to ask.
        prepared.deps.ask_user = ask_user

        status = RunStatus.FAILED
        error: str | None = None
        paused: PausedRunState | None = None
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
            # Not a malfunction — the platform working — and recorded as its own
            # status so an operator filtering for problems does not wade through
            # it. Raised on rather than swallowed because somebody is sitting
            # there waiting, and they are owed the reason the answer stopped.
            status = RunStatus.BUDGET_EXCEEDED
            error = str(exc)
            logger.info("Chat run %s stopped by budget: %s", prepared.run.id, exc)
            raise
        except Exception as exc:
            error = str(exc)
            logger.exception("Chat run %s failed", prepared.run.id)
            raise
        finally:
            await self.runner.finish(prepared, status=status, error=error, paused_state=paused)
            # Committed here rather than left to the session context: that exit
            # rolls back on any exception, and cancellation never reaches it at
            # all, since ``CancelledError`` is not an ``Exception``. A run that
            # failed, was stopped or ran out of budget still spent money, and a
            # run missing from history is a run nobody is accountable for.
            await self.db.commit()

        return ChatTurn(
            output=output,
            model_label=prepared.built.model_label,
            agent_id=prepared.agent.id,
            agent_version_id=prepared.run.agent_version_id,
        )

    async def _context(self, user: User, organization_id: UUID) -> AuthContext:
        """The connected user's standing in the organization they are chatting in.

        Read from the membership row for the same reason the Slack router reads
        it: a run takes a subject, and the subject is the person who typed —
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
