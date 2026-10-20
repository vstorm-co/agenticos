"""Serving this organization's agents over A2A (#2092).

An agent its organization chose to serve has an **agent card** anybody may read -
its name, what it does, where to send work and how to authenticate - and a
JSON-RPC endpoint that takes `message/send`. Every task is an ordinary run: the
caller is an organization key or an OAuth grant on this deployment, narrowed to
its scopes, and the run goes through the same runner as every other surface, so
the budget, the approval gate, the audit trail and Activity all apply. A task's
id is the run's id, and its `contextId` is the conversation the run files under,
so the next message continues it.

Answered synchronously. `message/stream` and push notifications are not offered,
and the card says so: a run that stops for a person comes back `input-required`
and is continued in the console, and `tasks/get` reads where it stands since.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.repositories import agent_repo, conversation_repo
from app.schemas.a2a import (
    CONTENT_TYPE_NOT_SUPPORTED,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    TASK_NOT_CANCELABLE,
    TASK_NOT_FOUND,
    UNSUPPORTED_OPERATION,
    AgentCard,
    AgentSkill,
    Artifact,
    JsonRpcError,
    JsonRpcRequest,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
)
from app.schemas.agent import ParkedCall
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.conversation import ConversationService

logger = logging.getLogger(__name__)

UNSUPPORTED_METHODS = frozenset(
    {
        "message/stream",
        "tasks/resubscribe",
        "tasks/pushNotificationConfig/set",
        "tasks/pushNotificationConfig/get",
        "tasks/pushNotificationConfig/list",
        "tasks/pushNotificationConfig/delete",
    }
)
"""A2A methods the card says this server does not offer, refused by name."""

_STATES: dict[str, TaskState] = {
    RunStatus.RUNNING.value: "working",
    RunStatus.COMPLETED.value: "completed",
    RunStatus.AWAITING_APPROVAL.value: "input-required",
    RunStatus.AWAITING_ANSWER.value: "input-required",
    RunStatus.CANCELLED.value: "canceled",
}
"""Where a run stands, as A2A names it. Anything else - failed, over budget,
blocked by a guardrail - is a task that `failed`."""


class _RpcError(Exception):
    """A JSON-RPC error answer, raised inside a method and turned into the envelope."""

    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error = JsonRpcError(code=code, message=message, data=data)


def endpoint_url(agent_id: UUID) -> str:
    """Where an agent's A2A requests go."""
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.API_V1_STR}/a2a/{agent_id}"


class A2AServerService:
    """Agent cards and JSON-RPC tasks for the agents an organization serves over A2A."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def card(self, agent_id: UUID) -> AgentCard:
        """The card of an agent its organization serves over A2A.

        Raises:
            NotFoundError: For an agent that is not served - unpublished, archived,
                switched off or unknown answer alike, so a card is not a way to
                learn which agents exist.
        """
        agent = await agent_repo.get_served_over_a2a(self.db, agent_id)
        if agent is None:
            raise NotFoundError(message="No agent is served here", details={"agent_id": agent_id})
        base = settings.PUBLIC_BASE_URL.rstrip("/")
        version = (
            await agent_repo.get_version(
                self.db, agent.current_version_id, organization_id=agent.organization_id
            )
            if agent.current_version_id is not None
            else None
        )
        return AgentCard(
            name=agent.name,
            description=agent.description or "",
            url=endpoint_url(agent.id),
            version=str(version.version) if version is not None else "1",
            skills=[
                AgentSkill(
                    id=agent.slug,
                    name=agent.name,
                    description=agent.description or agent.name,
                    tags=list(agent.tags or []),
                )
            ],
            securitySchemes={
                "bearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "An organization API key, or an OAuth access token this "
                        "deployment issued. Either must be allowed to run this agent."
                    ),
                },
                "oauth": {
                    "type": "oauth2",
                    "oauth2MetadataUrl": f"{base}/.well-known/oauth-authorization-server",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": f"{base}/authorize",
                            "tokenUrl": f"{base}/token",
                            "scopes": {"agents:run": "Run agents"},
                        }
                    },
                },
            },
            security=[{"bearer": []}, {"oauth": ["agents:run"]}],
        )

    async def handle(self, ctx: AuthContext, agent_id: UUID, body: Any) -> dict[str, Any]:
        """Answer one JSON-RPC request to an agent served over A2A.

        Raises:
            NotFoundError: For an agent this caller's organization does not serve -
                another tenant's answers the same as an unknown one - or one this
                caller may not see.
            AuthorizationError: For a caller who may see the agent and not run it.
                A2A leaves who may call to the transport, so both are HTTP
                answers; everything else is a JSON-RPC answer, success or error.
        """
        agent = await agent_repo.get_served_over_a2a(self.db, agent_id)
        if agent is None or agent.organization_id != ctx.organization_id:
            raise NotFoundError(message="No agent is served here", details={"agent_id": agent_id})
        try:
            request = JsonRpcRequest.model_validate(body)
        except ValidationError:
            return _error(
                None, JsonRpcError(code=INVALID_REQUEST, message="Not a JSON-RPC 2.0 request")
            )
        try:
            result = await self._dispatch(ctx, agent, request)
        except _RpcError as refused:
            return _error(request.id, refused.error)
        return {"jsonrpc": "2.0", "id": request.id, "result": result}

    async def _dispatch(
        self, ctx: AuthContext, agent: Agent, request: JsonRpcRequest
    ) -> dict[str, Any]:
        if request.method == "message/send":
            return await self._send(ctx, agent, request.params)
        if request.method == "tasks/get":
            return await self._get(ctx, agent, request.params)
        if request.method == "tasks/cancel":
            raise _RpcError(
                TASK_NOT_CANCELABLE,
                "A task here is a run that has already answered or is waiting for a "
                "person; decline its approval in the console to end it.",
            )
        if request.method in UNSUPPORTED_METHODS:
            raise _RpcError(UNSUPPORTED_OPERATION, f"{request.method} is not offered by this agent")
        raise _RpcError(METHOD_NOT_FOUND, f"Unknown method {request.method}")

    async def _send(self, ctx: AuthContext, agent: Agent, params: dict[str, Any]) -> dict[str, Any]:
        try:
            message = Message.model_validate(params.get("message"))
        except ValidationError as invalid:
            raise _RpcError(INVALID_PARAMS, "params.message is not an A2A message") from invalid
        # Refused rather than read past: a question that came with a file or data
        # the run never sees is answered as though it had not.
        unread = sorted({part.kind for part in message.parts if part.kind != "text"})
        if unread:
            raise _RpcError(
                CONTENT_TYPE_NOT_SUPPORTED,
                f"This agent reads only text parts, not {', '.join(unread)}",
            )
        prompt = message.text().strip()
        if not prompt:
            raise _RpcError(INVALID_PARAMS, "The message has no text part")
        # A task here waits only on a person deciding in the console, so a message
        # cannot carry it further - and taking it as a new one would start a
        # second run beside the one still waiting.
        if message.task_id is not None:
            raise _RpcError(
                UNSUPPORTED_OPERATION,
                "A task here is not continued by a message: one waiting for input is "
                "decided in the console, and tasks/get reads where it stands. Send "
                "without taskId to ask something new in the same contextId.",
            )
        conversation = _uuid(message.context_id, "contextId")
        # Before the conversation opens, not after: refused by the run, the
        # request still committed, and each refusal left an empty thread.
        await AgentRegistryService(self.db).get(ctx, agent.id, perm=Perm.AGENTS_RUN)
        try:
            conversation_id, history = await ConversationService(self.db).for_api_run(
                ctx, conversation, prompt=prompt
            )
        except NotFoundError as unknown:
            raise _RpcError(INVALID_PARAMS, "contextId names no conversation here") from unknown
        except BadRequestError as refused:
            # A conversation of theirs that is not an API one - begun in the
            # console or a channel - is a bad parameter too, not a failed request.
            raise _RpcError(INVALID_PARAMS, refused.message) from refused
        runner = AgentRunnerService(self.db)
        try:
            output, run = await runner.execute(
                ctx,
                agent.id,
                prompt,
                surface=RunSurface.A2A,
                conversation_id=conversation_id,
                message_history=history,
                reports_failure=True,
            )
        except AuthorizationError:
            if conversation is None:
                await self._discard(ctx, conversation_id)
            raise
        except AppException as failed:
            run_id = (failed.details or {}).get("run_id")
            if run_id is None:
                if conversation is None:
                    await self._discard(ctx, conversation_id)
                raise _RpcError(INVALID_REQUEST, failed.message) from failed
            # The run started and failed: A2A's answer is a task that failed,
            # not an error about the request.
            return _task(
                task_id=str(run_id),
                context_id=str(conversation_id),
                state="failed",
                note=failed.message,
            ).model_dump(by_alias=True, exclude_none=True)
        parked = await runner.parked_calls(ctx, run)
        return self._task_for(run, output, parked).model_dump(by_alias=True, exclude_none=True)

    async def _discard(self, ctx: AuthContext, conversation_id: UUID) -> None:
        """Delete a thread this request opened and no run answered.

        Refused before any run began - a budget, an agent not published - it holds
        the question alone, and the caller was answered with an error naming no
        context to come back to.
        """
        await ConversationService(self.db).delete_conversation(
            conversation_id, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )

    async def _get(self, ctx: AuthContext, agent: Agent, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("id") is None:
            raise _RpcError(INVALID_PARAMS, "params.id names the task")
        try:
            run_id = UUID(str(params["id"]))
        except ValueError as unknown:
            # No task of this server's has that id: an unknown task, as any other.
            raise _RpcError(TASK_NOT_FOUND, "No such task") from unknown
        runner = AgentRunnerService(self.db)
        try:
            run = await runner.get_run(ctx, run_id)
        except (NotFoundError, AuthorizationError) as missing:
            raise _RpcError(TASK_NOT_FOUND, "No such task") from missing
        # Whoever asked for the task reads it, and so does anybody who may read
        # every run - not anyone in the organization who learns its id.
        if run.agent_id != agent.id or not (run.user_id == ctx.user_id or ctx.has(Perm.RUNS_VIEW)):
            raise _RpcError(TASK_NOT_FOUND, "No such task")
        answer = await self._answer(run)
        parked = await runner.parked_calls(ctx, run)
        return self._task_for(run, answer, parked).model_dump(by_alias=True, exclude_none=True)

    async def _answer(self, run: AgentRun) -> str:
        """What the run said last - read back off its turns, which is where an answer lives.

        The newest, however long the run: read oldest first and capped, a run
        past the cap answered with something it said early on.
        """
        return await conversation_repo.last_answer_of_run(self.db, run.id) or ""

    @staticmethod
    def _task_for(run: AgentRun, answer: str, parked: list[ParkedCall]) -> Task:
        state = _STATES.get(run.status, "failed")
        note: str | None = None
        if state == "input-required":
            waiting = ", ".join(call.tool_name for call in parked) or "a person's answer"
            note = (
                f"Waiting for a person to decide: {waiting}. It is decided in the console, "
                "and tasks/get reads where it stands."
            )
        elif state == "failed":
            note = run.error or f"The run ended {run.status}."
        return _task(
            task_id=str(run.id),
            context_id=str(run.conversation_id or ""),
            state=state,
            note=note,
            answer=answer,
        )


def _task(
    *, task_id: str, context_id: str, state: TaskState, note: str | None, answer: str = ""
) -> Task:
    message = (
        Message(
            role="agent",
            parts=[Part(kind="text", text=note)],
            messageId=uuid.uuid4().hex,
            contextId=context_id,
            taskId=task_id,
        )
        if note
        else None
    )
    return Task(
        id=task_id,
        contextId=context_id,
        status=TaskStatus(state=state, message=message),
        artifacts=(
            [Artifact(artifactId="answer", name="answer", parts=[Part(kind="text", text=answer)])]
            if answer
            else []
        ),
    )


def _uuid(value: Any, field: str) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError as invalid:
        raise _RpcError(INVALID_PARAMS, f"{field} is not an id this server issued") from invalid


def _error(request_id: str | int | None, error: JsonRpcError) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error.model_dump(exclude_none=True),
    }
