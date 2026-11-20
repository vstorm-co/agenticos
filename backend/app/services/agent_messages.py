"""Agent-to-agent messages: threads between two agents, and what happens in them.

Who may do what is decided against the *agents*, not the thread: a thread has
no owner of its own, so sending as an agent needs `agents:run` on both agents
in it - putting words in one agent's mouth to another - and reading needs
`agents:run` on either one. A grant on an agent widens exactly as it does
everywhere else, because both checks go through `resolve_access`.

A message never starts a run of its recipient. It is stored, and visible in
the console and to the recipient's next run through its capability tools.
Starting work on receipt is a routine or a delegation's job, not a side effect
of being written to.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_message import AgentMessage, AgentMessageThread
from app.db.models.chat_file import ChatFile
from app.repositories import agent_message_repo, agent_repo, chat_file_repo
from app.schemas.agent_message import (
    MAX_ATTACHMENTS,
    AgentMessageAttachmentRead,
    AgentMessageList,
    AgentMessagePreview,
    AgentMessageReactionCreate,
    AgentMessageReactionRead,
    AgentMessageReactionsRead,
    AgentMessageRead,
    AgentMessageRecipientList,
    AgentMessageSend,
    AgentMessageThreadList,
    AgentMessageThreadRead,
    AgentRef,
)
from app.services.access import AGENT, resolve_access, visible_resource_ids

logger = logging.getLogger(__name__)

MAX_BODY_HARD_CHARS = 100_000
"""The service's own ceiling, behind the console's and the capability's: a
caller that skips both validations cannot store a novel as a message."""

PREVIEW_CHARS = 200
"""How much of the last message a thread listing shows."""


class AgentMessageService:
    """Threads between two agents, and the messages, reactions and files in them."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def send(self, ctx: AuthContext, data: AgentMessageSend) -> AgentMessageRead:
        """Send a message as one agent to another, in their thread.

        Resolves the recipient by slug or id, refuses a draft or archived
        agent on either side, and links files the sender already uploaded.
        Returns the message as the thread reads it.
        """
        sender = await self._agent_or_404(data.sender_agent_id, organization_id=ctx.organization_id)
        recipient = await self._resolve_recipient(ctx, data.recipient)
        if sender.id == recipient.id:
            raise BadRequestError(
                message="An agent cannot message itself",
                details={"agent_id": sender.id},
            )
        self._check_published(sender)
        self._check_published(recipient)
        await self._check_can_message(ctx, sender, recipient)
        if len(data.body) > MAX_BODY_HARD_CHARS:
            raise BadRequestError(
                message=f"A message is at most {MAX_BODY_HARD_CHARS} characters",
                details={"body_chars": len(data.body)},
            )

        # Attachments are validated before the thread is touched: a refused
        # send must not leave an empty thread behind.
        files = await self._owned_attachments(ctx, data.attachment_file_ids)
        thread = await agent_message_repo.get_or_create_thread(
            self.db,
            organization_id=ctx.organization_id,
            agent_a_id=sender.id,
            agent_b_id=recipient.id,
        )
        reply_to = await self._reply_target(thread, data.reply_to_message_id)
        message = await agent_message_repo.create_message(
            self.db,
            thread=thread,
            organization_id=ctx.organization_id,
            sender_agent_id=sender.id,
            sender_user_id=ctx.user_id,
            body=data.body,
            reply_to_message_id=reply_to.id if reply_to is not None else None,
        )
        for chat_file in files:
            await agent_message_repo.add_attachment(
                self.db,
                message=message,
                organization_id=ctx.organization_id,
                chat_file_id=chat_file.id,
            )
        await agent_message_repo.touch_thread(self.db, thread=thread, at=message.created_at)
        return await self._read_message(message, sender_agent=sender)

    async def list_threads(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 50
    ) -> AgentMessageThreadList:
        """The threads involving an agent this caller may run, most recent first."""
        agent_ids = await self._runnable_agent_ids(ctx)
        threads, total = await agent_message_repo.list_threads(
            self.db,
            organization_id=ctx.organization_id,
            agent_ids=agent_ids,
            skip=skip,
            limit=limit,
        )
        return AgentMessageThreadList(items=await self._read_threads(ctx, threads), total=total)

    async def list_threads_for_agent(
        self, ctx: AuthContext, *, agent_id: UUID, skip: int = 0, limit: int = 50
    ) -> AgentMessageThreadList:
        """The threads one agent is in - what its capability tools list.

        The caller must be able to run that agent; a run's own agent always
        passes, and a person listing another agent's threads needs the same
        reach the console listing needs for any agent in them.
        """
        agent = await self._agent_or_404(agent_id, organization_id=ctx.organization_id)
        if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT):
            raise AuthorizationError(
                message="This agent is not one you may run",
                details={"agent_id": agent.id},
            )
        threads, total = await agent_message_repo.list_threads(
            self.db,
            organization_id=ctx.organization_id,
            agent_ids={agent.id},
            skip=skip,
            limit=limit,
        )
        return AgentMessageThreadList(items=await self._read_threads(ctx, threads), total=total)

    async def get_thread(self, ctx: AuthContext, thread_id: UUID) -> AgentMessageThreadRead:
        """One thread, with its last message and whether it waits on the reader."""
        thread = await self._thread_or_404(ctx, thread_id)
        await self._check_can_read_thread(ctx, thread)
        return (await self._read_threads(ctx, [thread]))[0]

    async def list_messages(
        self, ctx: AuthContext, thread_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> AgentMessageList:
        """One thread's messages, oldest first."""
        thread = await self._thread_or_404(ctx, thread_id)
        await self._check_can_read_thread(ctx, thread)
        messages, total = await agent_message_repo.list_messages(
            self.db, thread_id=thread.id, skip=skip, limit=limit
        )
        return AgentMessageList(items=await self._read_messages(messages), total=total)

    async def react(
        self,
        ctx: AuthContext,
        *,
        message_id: UUID,
        data: AgentMessageReactionCreate,
        thread_id: UUID | None = None,
    ) -> AgentMessageReactionsRead:
        """React to a message, or take the reaction back by sending it again.

        Reacting as an agent names one of the thread's two agents and needs
        `agents:run` on it; reacting without one is the reader themself. The
        emoji is one grapheme cluster's worth of text, not a word: anything
        with a space in it is a sentence, not a reaction. When `thread_id` is
        given - the route the console calls - the message must be in it.
        """
        emoji = data.emoji.strip()
        if not emoji or any(char.isspace() for char in emoji):
            raise BadRequestError(
                message="A reaction is one emoji, with no spaces",
                details={"emoji": data.emoji},
            )
        message = await self._message_or_404(message_id)
        if thread_id is not None and message.thread_id != thread_id:
            raise NotFoundError(
                message="This message is not in that thread",
                details={"message_id": message.id, "thread_id": thread_id},
            )
        thread = await self._thread_or_404(ctx, message.thread_id)
        await self._check_can_read_thread(ctx, thread)
        reactor_agent_id: UUID | None = None
        reactor_user_id: UUID | None = None
        if data.as_agent_id is not None:
            reactor = await self._agent_or_404(
                data.as_agent_id, organization_id=ctx.organization_id
            )
            if reactor.id not in (thread.agent_a_id, thread.agent_b_id):
                raise BadRequestError(
                    message="Only an agent in this thread may react as itself",
                    details={"agent_id": reactor.id, "thread_id": thread.id},
                )
            if not await resolve_access(
                self.db, ctx, reactor, Perm.AGENTS_RUN, resource_type=AGENT
            ):
                raise AuthorizationError(
                    message="This agent is not one you may run",
                    details={"agent_id": reactor.id},
                )
            reactor_agent_id = reactor.id
        else:
            reactor_user_id = ctx.subject_id
        existing = await agent_message_repo.get_reaction(
            self.db,
            message_id=message.id,
            emoji=emoji,
            reactor_agent_id=reactor_agent_id,
            reactor_user_id=reactor_user_id,
        )
        reacted = False
        if existing is None:
            await agent_message_repo.add_reaction(
                self.db,
                message=message,
                organization_id=ctx.organization_id,
                emoji=emoji,
                reactor_agent_id=reactor_agent_id,
                reactor_user_id=reactor_user_id,
            )
            reacted = True
        else:
            await agent_message_repo.remove_reaction(self.db, reaction=existing)
        reactions = await self._read_reactions([message.id])
        return AgentMessageReactionsRead(reacted=reacted, reactions=reactions.get(message.id, []))

    async def mark_read(self, ctx: AuthContext, thread_id: UUID) -> None:
        """Record that the caller has had this thread open, now."""
        thread = await self._thread_or_404(ctx, thread_id)
        await self._check_can_read_thread(ctx, thread)
        await agent_message_repo.mark_read(
            self.db, thread_id=thread.id, user_id=ctx.subject_id, read_at=datetime.now(UTC)
        )

    async def download_attachment(
        self,
        ctx: AuthContext,
        *,
        message_id: UUID,
        chat_file_id: UUID,
        thread_id: UUID | None = None,
    ) -> ChatFile:
        """The file a message carries, for a caller who may read its thread.

        The row, not the bytes: the route streams them through the same
        response a chat attachment gets, so the disposition and framing rules
        are decided once. When `thread_id` is given - the route the console
        calls - the message must be in it.
        """
        message = await self._message_or_404(message_id)
        if thread_id is not None and message.thread_id != thread_id:
            raise NotFoundError(
                message="This message is not in that thread",
                details={"message_id": message.id, "thread_id": thread_id},
            )
        thread = await self._thread_or_404(ctx, message.thread_id)
        await self._check_can_read_thread(ctx, thread)
        attachment = await agent_message_repo.get_attachment(
            self.db, message_id=message.id, chat_file_id=chat_file_id
        )
        if attachment is None:
            raise NotFoundError(
                message="That file is not attached to this message",
                details={"message_id": message.id, "chat_file_id": chat_file_id},
            )
        chat_file = await chat_file_repo.get_by_id(self.db, chat_file_id)
        if chat_file is None:
            raise NotFoundError(
                message="That file is no longer stored",
                details={"chat_file_id": chat_file_id},
            )
        return chat_file

    async def list_recipients(
        self, ctx: AuthContext, *, skip: int = 0, limit: int = 50
    ) -> AgentMessageRecipientList:
        """The published agents this caller may message, most recent first."""
        agent_ids = await self._runnable_agent_ids(ctx, statuses=(AgentStatus.PUBLISHED.value,))
        agents, total = await agent_repo.list_by_ids(
            self.db,
            organization_id=ctx.organization_id,
            agent_ids=agent_ids,
            skip=skip,
            limit=limit,
        )
        return AgentMessageRecipientList(
            items=[AgentRef(id=agent.id, slug=agent.slug, name=agent.name) for agent in agents],
            total=total,
        )

    async def _runnable_agent_ids(
        self, ctx: AuthContext, *, statuses: tuple[str, ...] = ()
    ) -> set[UUID] | None:
        """The agents this caller may run, or `None` when the role reaches them all.

        The role's scope and the caller's grants are both read here, through
        the same visibility the agent listing uses: a member with a grant on
        one private agent may message it, and nobody else's. A context with
        no subject, or a key the permission was not granted to, reaches no
        agent at all rather than the scope's share of them.
        """
        if ctx.user_id is None or not ctx.key_allows(Perm.AGENTS_RUN):
            return set()
        extra = await visible_resource_ids(self.db, ctx, resource_type=AGENT, perm=Perm.AGENTS_RUN)
        if extra is None:
            return None
        return await agent_repo.list_visible_ids(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=False,
            shared_ids=extra,
            statuses=statuses,
        )

    async def _agent_or_404(self, agent_id: UUID, *, organization_id: UUID) -> Agent:
        agent = await agent_repo.get(self.db, agent_id, organization_id=organization_id)
        if agent is None:
            raise NotFoundError(message="Agent not found", details={"agent_id": agent_id})
        return agent

    async def _resolve_recipient(self, ctx: AuthContext, recipient: str) -> Agent:
        """An agent by id, or by the slug the console and the model both use.

        An id from another organization resolves to nothing here: the lookup
        is by id first because the console already holds one, and the slug
        afterwards because a person types a name, not a UUID - and in both
        cases the row must belong to this organization.
        """
        agent: Agent | None
        try:
            agent = await agent_repo.get(
                self.db, UUID(recipient), organization_id=ctx.organization_id
            )
        except ValueError:
            agent = None
        if agent is None:
            agent = await agent_repo.get_by_slug(
                self.db, recipient, organization_id=ctx.organization_id
            )
        if agent is None or agent.organization_id != ctx.organization_id:
            raise NotFoundError(
                message=f"No agent named '{recipient}' in this organization",
                details={"recipient": recipient},
            )
        return agent

    @staticmethod
    def _check_published(agent: Agent) -> None:
        if agent.status != AgentStatus.PUBLISHED.value:
            raise BadRequestError(
                message=f"Agent '{agent.slug}' is not published, so it cannot be messaged",
                details={"agent_id": agent.id, "status": agent.status},
            )

    async def _check_can_message(self, ctx: AuthContext, sender: Agent, recipient: Agent) -> None:
        for agent in (sender, recipient):
            if not await resolve_access(self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT):
                raise AuthorizationError(
                    message="Messaging needs an agent you may run on both sides",
                    details={"agent_id": agent.id},
                )

    async def _thread_or_404(self, ctx: AuthContext, thread_id: UUID) -> AgentMessageThread:
        thread = await agent_message_repo.get_thread(self.db, thread_id)
        if thread is None or thread.organization_id != ctx.organization_id:
            raise NotFoundError(message="Thread not found", details={"thread_id": thread_id})
        return thread

    async def _message_or_404(self, message_id: UUID) -> AgentMessage:
        message = await agent_message_repo.get_message(self.db, message_id)
        if message is None:
            raise NotFoundError(message="Message not found", details={"message_id": message_id})
        return message

    async def _check_can_read_thread(self, ctx: AuthContext, thread: AgentMessageThread) -> None:
        for agent_id in (thread.agent_a_id, thread.agent_b_id):
            agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
            if agent is not None and await resolve_access(
                self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT
            ):
                return
        raise AuthorizationError(
            message="This thread is between agents you may not run",
            details={"thread_id": thread.id},
        )

    async def _reply_target(
        self, thread: AgentMessageThread, reply_to_message_id: UUID | None
    ) -> AgentMessage | None:
        if reply_to_message_id is None:
            return None
        reply_to = await agent_message_repo.get_message(self.db, reply_to_message_id)
        if reply_to is None:
            raise NotFoundError(
                message="The message being replied to was not found",
                details={"message_id": reply_to_message_id},
            )
        if reply_to.thread_id != thread.id:
            raise BadRequestError(
                message="A reply must answer a message in the same thread",
                details={"message_id": reply_to.id, "thread_id": thread.id},
            )
        return reply_to

    async def _owned_attachments(self, ctx: AuthContext, file_ids: list[UUID]) -> list[ChatFile]:
        """The files this sender uploaded, in the order they were named.

        A duplicate id links once: the link table refuses the second, and a
        file named twice is one attachment, not two.
        """
        if len(file_ids) > MAX_ATTACHMENTS:
            raise BadRequestError(
                message=f"A message carries at most {MAX_ATTACHMENTS} files",
                details={"file_count": len(file_ids)},
            )
        ordered = list(dict.fromkeys(file_ids))
        if not ordered:
            return []
        found = await chat_file_repo.get_many(self.db, ordered, user_id=ctx.subject_id)
        found_ids = {chat_file.id for chat_file in found}
        if missing := [file_id for file_id in ordered if file_id not in found_ids]:
            raise NotFoundError(
                message="An attachment was not found, or was uploaded by somebody else",
                details={"file_ids": missing},
            )
        by_id = {chat_file.id: chat_file for chat_file in found}
        return [by_id[file_id] for file_id in ordered]

    async def _read_threads(
        self, ctx: AuthContext, threads: list[AgentMessageThread]
    ) -> list[AgentMessageThreadRead]:
        if not threads:
            return []
        agent_ids = {
            agent_id for thread in threads for agent_id in (thread.agent_a_id, thread.agent_b_id)
        }
        agents, _ = await agent_repo.list_by_ids(
            self.db,
            organization_id=ctx.organization_id,
            agent_ids=agent_ids,
            skip=0,
            limit=len(agent_ids),
        )
        by_id = {agent.id: agent for agent in agents}
        latest = await agent_message_repo.latest_messages(
            self.db, thread_ids=[thread.id for thread in threads]
        )
        reads = await agent_message_repo.get_reads(
            self.db, thread_ids=[thread.id for thread in threads], user_id=ctx.subject_id
        )
        sender_slugs = {
            message.sender_agent_id: by_id[message.sender_agent_id].slug
            for message in latest.values()
            if message.sender_agent_id in by_id
        }
        out: list[AgentMessageThreadRead] = []
        for thread in threads:
            # Both agents are always here: deleting an agent cascades to its
            # threads, so a thread can never outlive a participant.
            agent_a = by_id[thread.agent_a_id]
            agent_b = by_id[thread.agent_b_id]
            last = latest.get(thread.id)
            read = reads.get(thread.id)
            unread = last is not None and (read is None or read.read_at < last.created_at)
            out.append(
                AgentMessageThreadRead(
                    id=thread.id,
                    agent_a=AgentRef(id=agent_a.id, slug=agent_a.slug, name=agent_a.name),
                    agent_b=AgentRef(id=agent_b.id, slug=agent_b.slug, name=agent_b.name),
                    last_message_at=thread.last_message_at,
                    last_message=(
                        AgentMessagePreview(
                            sender_agent_slug=sender_slugs.get(last.sender_agent_id, "?"),
                            body=last.body[:PREVIEW_CHARS],
                            created_at=last.created_at,
                        )
                        if last is not None
                        else None
                    ),
                    unread=unread,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                )
            )
        return out

    async def _read_messages(self, messages: list[AgentMessage]) -> list[AgentMessageRead]:
        if not messages:
            return []
        agent_ids = {message.sender_agent_id for message in messages}
        agents, _ = await agent_repo.list_by_ids(
            self.db,
            organization_id=messages[0].organization_id,
            agent_ids=agent_ids,
            skip=0,
            limit=len(agent_ids),
        )
        by_id = {agent.id: agent for agent in agents}
        reactions = await self._read_reactions([message.id for message in messages])
        attachments = await self._read_attachments([message.id for message in messages])
        return [
            AgentMessageRead(
                id=message.id,
                thread_id=message.thread_id,
                sender_agent_id=message.sender_agent_id,
                sender_agent_slug=by_id[message.sender_agent_id].slug
                if message.sender_agent_id in by_id
                else "?",
                sender_user_id=message.sender_user_id,
                body=message.body,
                reply_to_message_id=message.reply_to_message_id,
                reactions=reactions.get(message.id, []),
                attachments=attachments.get(message.id, []),
                created_at=message.created_at,
                updated_at=message.updated_at,
            )
            for message in messages
        ]

    async def _read_message(
        self,
        message: AgentMessage,
        *,
        sender_agent: Agent,
    ) -> AgentMessageRead:
        reactions = await self._read_reactions([message.id])
        attachments = await self._read_attachments([message.id])
        return AgentMessageRead(
            id=message.id,
            thread_id=message.thread_id,
            sender_agent_id=message.sender_agent_id,
            sender_agent_slug=sender_agent.slug,
            sender_user_id=message.sender_user_id,
            body=message.body,
            reply_to_message_id=message.reply_to_message_id,
            reactions=reactions.get(message.id, []),
            attachments=attachments.get(message.id, []),
            created_at=message.created_at,
            updated_at=message.updated_at,
        )

    async def _read_reactions(
        self, message_ids: list[UUID]
    ) -> dict[UUID, list[AgentMessageReactionRead]]:
        rows = await agent_message_repo.list_reactions(self.db, message_ids=message_ids)
        agent_ids = {row.reactor_agent_id for row in rows if row.reactor_agent_id is not None}
        slugs: dict[UUID, str] = {}
        if agent_ids:
            agents, _ = await agent_repo.list_by_ids(
                self.db,
                organization_id=rows[0].organization_id,
                agent_ids=agent_ids,
                skip=0,
                limit=len(agent_ids),
            )
            slugs = {agent.id: agent.slug for agent in agents}
        grouped: dict[UUID, list[AgentMessageReactionRead]] = {}
        for row in rows:
            grouped.setdefault(row.message_id, []).append(
                AgentMessageReactionRead(
                    emoji=row.emoji,
                    reactor_agent_id=row.reactor_agent_id,
                    reactor_agent_slug=(
                        slugs.get(row.reactor_agent_id) if row.reactor_agent_id else None
                    ),
                    reactor_user_id=row.reactor_user_id,
                    created_at=row.created_at,
                )
            )
        return grouped

    async def _read_attachments(
        self, message_ids: list[UUID]
    ) -> dict[UUID, list[AgentMessageAttachmentRead]]:
        links = await agent_message_repo.list_attachments(self.db, message_ids=message_ids)
        if not links:
            return {}
        files = await agent_message_repo.list_chat_files(
            self.db, file_ids=[link.chat_file_id for link in links]
        )
        by_id = {chat_file.id: chat_file for chat_file in files}
        grouped: dict[UUID, list[AgentMessageAttachmentRead]] = {}
        for link in links:
            chat_file = by_id.get(link.chat_file_id)
            if chat_file is None:
                continue
            grouped.setdefault(link.message_id, []).append(
                AgentMessageAttachmentRead(
                    chat_file_id=chat_file.id,
                    filename=chat_file.filename,
                    mime_type=chat_file.mime_type,
                    size=chat_file.size,
                    file_type=chat_file.file_type,
                )
            )
        return grouped
