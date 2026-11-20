"""Direct messages between agents; the sender is always this run's agent."""

from typing import Annotated
from uuid import UUID

from pydantic import Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps
from app.core.exceptions import AppException
from app.db.session import get_db_context
from app.schemas.agent_message import (
    AgentMessageReactionCreate,
    AgentMessageSend,
)
from app.services.access import acting_member
from app.services.agent_messages import AgentMessageService

SEND_DESCRIPTION = "Send a message to another agent, in the thread the two of you share."
READ_DESCRIPTION = "Read the messages in one thread between this agent and another."
LIST_DESCRIPTION = "List the threads this agent is messaging in, most recently active first."
REACT_DESCRIPTION = "React to a message in a thread, or take the reaction back by sending it again."


def build_agent_messages_toolset(
    *, max_message_chars: int = 16_000, allow_attachments: bool = True
) -> FunctionToolset[AgentDeps]:
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()

    async def agent_send_message(
        ctx: RunContext[AgentDeps],
        recipient: Annotated[str, Field(min_length=1, max_length=64)],
        body: Annotated[str, Field(min_length=1, max_length=100_000)],
        reply_to_message_id: UUID | None = None,
        attachment_file_ids: list[UUID] | None = None,
    ) -> str:
        """Send a message to another agent, in the thread the two of you share.

        Use when another agent needs to know something, or to answer a message
        it sent. The recipient is its slug or id. The message is stored, not
        delivered as a run: the other agent reads it in the console, or through
        its own messaging tools on its next run. A reply names the message it
        answers; files must already be uploaded, and at most ten ride along.

        Args:
            recipient: The other agent's slug, as the console shows it, or its id.
            body: What to say. Keep it to what the other agent needs to act on.
            reply_to_message_id: The message this answers, in the same thread.
            attachment_file_ids: Files uploaded earlier, to send with the message.

        Returns:
            JSON with the stored message. A refusal is text explaining why; it
            has not sent anything.
        """
        deps = ctx.deps
        if deps.agent_id is None or deps.impersonated:
            return "Messaging needs this agent running as itself, not as a preview."
        if len(body) > max_message_chars:
            return (
                f"That message is {len(body)} characters; this agent may send "
                f"at most {max_message_chars}."
            )
        if attachment_file_ids and not allow_attachments:
            return "This agent may not send files with its messages."
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, deps.organization_id, deps.user_id)
                if auth is None or deps.run_person != auth.subject_id:
                    return "Messaging needs an active organization member."
                service = AgentMessageService(db)
                message = await service.send(
                    auth,
                    AgentMessageSend(
                        sender_agent_id=deps.agent_id,
                        recipient=recipient,
                        body=body,
                        reply_to_message_id=reply_to_message_id,
                        attachment_file_ids=attachment_file_ids or [],
                    ),
                )
                return message.model_dump_json()
        except AppException as exc:
            return f"Refused ({exc.code}): {exc.message}"

    async def agent_read_messages(
        ctx: RunContext[AgentDeps],
        thread_id: UUID,
        skip: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> str:
        """Read the messages in one thread between this agent and another.

        Use to catch up on what the other agent said, or to re-read a thread
        before answering it. Messages arrive oldest first.

        Args:
            thread_id: The thread from agent_list_threads.
            skip: How many of its messages to pass over.
            limit: How many to return, at most one hundred.

        Returns:
            JSON with the thread's messages, oldest first. A refusal is text
            explaining why.
        """
        deps = ctx.deps
        if deps.agent_id is None or deps.impersonated:
            return "Messaging needs this agent running as itself, not as a preview."
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, deps.organization_id, deps.user_id)
                if auth is None or deps.run_person != auth.subject_id:
                    return "Messaging needs an active organization member."
                messages = await AgentMessageService(db).list_messages(
                    auth, thread_id, skip=skip, limit=limit
                )
                return messages.model_dump_json()
        except AppException as exc:
            return f"Refused ({exc.code}): {exc.message}"

    async def agent_list_threads(
        ctx: RunContext[AgentDeps],
        skip: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> str:
        """List the threads this agent is messaging in, most recently active first.

        Use to find who this agent has been talking to, or to pick a thread to
        read. Each thread names both agents and its latest message.

        Args:
            skip: How many threads to pass over.
            limit: How many to return, at most one hundred.

        Returns:
            JSON with the threads, most recently active first. A refusal is
            text explaining why.
        """
        deps = ctx.deps
        if deps.agent_id is None or deps.impersonated:
            return "Messaging needs this agent running as itself, not as a preview."
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, deps.organization_id, deps.user_id)
                if auth is None or deps.run_person != auth.subject_id:
                    return "Messaging needs an active organization member."
                threads = await AgentMessageService(db).list_threads_for_agent(
                    auth, agent_id=deps.agent_id, skip=skip, limit=limit
                )
                return threads.model_dump_json()
        except AppException as exc:
            return f"Refused ({exc.code}): {exc.message}"

    async def agent_react(
        ctx: RunContext[AgentDeps],
        message_id: UUID,
        emoji: Annotated[str, Field(min_length=1, max_length=16)],
    ) -> str:
        """React to a message in a thread, or take the reaction back by sending it again.

        Use for a one-emoji acknowledgement - a confirmation, a thanks - rather
        than a message. Sending the same emoji twice removes it.

        Args:
            message_id: The message to react to.
            emoji: One emoji, with no spaces.

        Returns:
            JSON saying whether the reaction is now on the message, and every
            reaction it carries. A refusal is text explaining why.
        """
        deps = ctx.deps
        if deps.agent_id is None or deps.impersonated:
            return "Messaging needs this agent running as itself, not as a preview."
        try:
            async with get_db_context() as db:
                auth = await acting_member(db, deps.organization_id, deps.user_id)
                if auth is None or deps.run_person != auth.subject_id:
                    return "Messaging needs an active organization member."
                reactions = await AgentMessageService(db).react(
                    auth,
                    message_id=message_id,
                    data=AgentMessageReactionCreate(emoji=emoji, as_agent_id=deps.agent_id),
                )
                return reactions.model_dump_json()
        except AppException as exc:
            return f"Refused ({exc.code}): {exc.message}"

    toolset.add_function(agent_send_message)
    toolset.add_function(agent_read_messages)
    toolset.add_function(agent_list_threads)
    toolset.add_function(agent_react)
    return toolset
