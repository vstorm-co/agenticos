"""Conversations, their messages and the tool calls inside them.

Everything here is tenant-scoped through one door: `get_conversation` takes the
active organization and every other method routes through it. A repository
function that reads a conversation without a tenant exists (`get_conversation_by_id`,
which says so in its own docstring) and must not be called from anywhere a
member's request reaches.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ask_user import parked_status
from app.agents.capabilities.media import prefix_for, restore_stored_media
from app.agents.steering import STEER_PREFIX
from app.core.background import spawn_after_commit
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.user import User
from app.db.updates import writable
from app.repositories import (
    agent_repo,
    agent_trigger_repo,
    chat_file_repo,
    conversation_repo,
    conversation_share_repo,
    member_repo,
    message_rating_repo,
    personal_data_repo,
    project_repo,
)
from app.schemas.conversation import (
    ChatPerson,
    ChatReader,
    ConversationAgent,
    ConversationCost,
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
    MessageReplyRef,
    ToolCallComplete,
    ToolCallCreate,
)
from app.schemas.conversation_share import AdminConversationList, AdminConversationRead
from app.services import chat_room
from app.services.access import AGENT, PROJECT, resolve_access, visible_resource_ids
from app.services.channels import membership as channel_membership
from app.services.file_storage import delete_files_best_effort, delete_prefix_best_effort
from app.services.message_history import HistoryMessage, build_message_history

logger = logging.getLogger(__name__)

API_HISTORY_MESSAGES = 200
"""How much of a conversation an API run sends the model: what a channel thread
sends, with the same summary taking over beyond it."""


def _api_title(prompt: str) -> str:
    """A conversation opened over the API is named for what it was first asked."""
    first = " ".join(prompt.split())
    return first if len(first) <= 80 else f"{first[:79]}…"


def _file_uuids(file_ids: Sequence[str]) -> tuple[list[UUID], list[str]]:
    """Parse client-sent file ids, naming the ones that are not UUIDs at all.

    `str()` first, because the socket payload is untyped JSON: a number or a
    null in the list must land in `malformed`, not raise a `TypeError` past
    the refusal written for it.
    """
    ids: list[UUID] = []
    malformed: list[str] = []
    for fid in file_ids:
        try:
            ids.append(UUID(str(fid)))
        except ValueError:
            malformed.append(str(fid))
    return ids, malformed


def _as_history(
    rows: Sequence[Message],
    exclude_message_id: UUID | None,
    spoken: dict[UUID, str] | None = None,
) -> list[HistoryMessage]:
    """Transcript rows as the replayer wants them, minus the turn being answered.

    A prompt that carried files is replayed with what they added for the model,
    so a follow-up about the file reaches a model that knows it is there. A
    person's turn reads as `spoken` says where it says anything - who said it
    and what it answers - see `ConversationService._spoken`.
    """
    spoken = spoken or {}
    history: list[HistoryMessage] = []
    for row in rows:
        if row.id == exclude_message_id:
            continue
        # What the person added while the answer was being written, as they added
        # it: before the answer it changed. Stored only as parts of the answer,
        # it was in the conversation on screen and missing from the next turn.
        history.extend(
            {"role": "user", "content": f"{STEER_PREFIX}\n\n{part['text']}"}
            for part in row.parts or []
            if part.get("type") == "steer" and isinstance(part.get("text"), str)
        )
        history.append(
            {
                "role": row.role,
                "content": spoken.get(row.id, row.content) + (row.attachment_context or ""),
                # The size of the request this answer came out of: the anchor the
                # compaction estimator measures against, in place of counting
                # characters - see `agent.build_message_history`.
                "context_used_tokens": row.context_used_tokens,
            }
        )
    return history


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def model_history(
        self, conversation_id: UUID, *, limit: int, exclude_message_id: UUID | None = None
    ) -> list[ModelMessage]:
        """The thread as the model should read it, summary included.

        Two halves where a summary has run: the history it reduced the older
        turns to, replayed exactly as the model last saw it - tool calls, their
        returns and the provider usage each answer carried - followed by the
        transcript rows written since. One half where none has, which is the
        recent window and what every surface did before (#49).

        Rebuilding from the transcript alone is what made a summary a per-turn
        purchase: the next turn saw the whole thread again, compacted it again,
        and paid again over a history one turn longer.

        `exclude_message_id` is the turn being answered. The prompt is written
        before the run so a refusal cannot lose it, so it is a row by the time
        this reads - and left in, the model is asked the same question twice.
        """
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        summary = None if conversation is None else conversation.summary_messages
        if conversation is None or summary is None or conversation.summary_ordinal is None:
            return await self._from_transcript(
                conversation_id, limit, exclude_message_id, conversation
            )
        # Re-inline whatever the stored history references before it is parsed
        # (#55). Unconditional: offloading is the `media` capability's decision,
        # but a conversation whose agent was unbound afterwards still has markers
        # in its history, and a marker nobody re-inlines is a picture the model
        # is handed in a language it does not read. A history carrying none costs
        # one tree walk that changes nothing.
        if conversation.organization_id is not None:
            summary = await restore_stored_media(
                summary,
                organization_id=conversation.organization_id,
                conversation_id=conversation_id,
            )
        try:
            replayed = ModelMessagesTypeAdapter.validate_python(summary)
        except ValidationError:
            # A shape `pydantic-ai` no longer reads. The blob is written by the
            # library and read back turns later, so a version this deployment
            # upgraded through is exactly where the two disagree - and raising
            # here would make the thread unanswerable for ever rather than for
            # one turn, on every message anybody sent it. The transcript is
            # still whole; the cost is one summary, bought again.
            logger.exception(
                "conversation_summary_unreadable", extra={"conversation_id": str(conversation_id)}
            )
            return await self._from_transcript(
                conversation_id, limit, exclude_message_id, conversation
            )
        since = await conversation_repo.get_messages_after(
            self.db, conversation_id, ordinal=conversation.summary_ordinal, limit=limit
        )
        spoken = await self._spoken(since, conversation)
        return [*replayed, *build_message_history(_as_history(since, exclude_message_id, spoken))]

    async def _from_transcript(
        self,
        conversation_id: UUID,
        limit: int,
        exclude_message_id: UUID | None,
        conversation: Conversation | None,
    ) -> list[ModelMessage]:
        """The recent window, which is what every surface read before #49."""
        rows = await conversation_repo.get_recent_messages(self.db, conversation_id, limit=limit)
        spoken = await self._spoken(rows, conversation)
        return build_message_history(_as_history(rows, exclude_message_id, spoken))

    async def find_conversation(self, conversation_id: UUID) -> Conversation | None:
        """A conversation by id with no access check, for a caller that already holds it.

        The chat socket's own thread: it resolved and checked the thread when the
        thread was opened, and needs the row again only to read how a turn reads.
        """
        return await conversation_repo.get_conversation_by_id(self.db, conversation_id)

    async def model_text(self, message: Message, conversation: Conversation) -> str:
        """How one person's turn reads to the model - see :meth:`_spoken`."""
        return (await self._spoken([message], conversation)).get(message.id, message.content)

    async def _spoken(
        self, rows: Sequence[Message], conversation: Conversation | None
    ) -> dict[UUID, str]:
        """How each person's turn reads to the model, where that is more than its text.

        In a project's chat several people talk to the agent at once, so each
        turn says who said it; and a turn that replies to an earlier message
        quotes it, so "yes, do that" reaches the model with what it says yes to.
        One query for the quoted messages outside the window, one for the names.
        """
        in_project = getattr(conversation, "project_id", None) is not None
        turns = [
            row
            for row in rows
            if row.role == "user"
            and (row.reply_to_message_id is not None or (in_project and row.author_user_id))
        ]
        if not turns:
            return {}
        quoted = {row.id: row for row in rows}
        quoted |= await conversation_repo.messages_by_id(
            self.db,
            {
                row.reply_to_message_id
                for row in turns
                if row.reply_to_message_id is not None and row.reply_to_message_id not in quoted
            },
        )
        people = await conversation_repo.users_by_id(
            self.db,
            {
                author
                for row in turns
                for author in (
                    row.author_user_id,
                    getattr(quoted.get(row.reply_to_message_id), "author_user_id", None)
                    if row.reply_to_message_id is not None
                    else None,
                )
                if author is not None
            },
        )
        spoken: dict[UUID, str] = {}
        for row in turns:
            text = row.content
            answered = (
                quoted.get(row.reply_to_message_id) if row.reply_to_message_id is not None else None
            )
            if answered is not None:
                text = (
                    f'(In reply to {_whose(answered, people)}: "{_excerpt(answered.content)}")'
                    f"\n\n{text}"
                )
            author = people.get(row.author_user_id) if in_project and row.author_user_id else None
            if author is not None:
                text = f"{ChatPerson.of(author).name}: {text}"
            spoken[row.id] = text
        return spoken

    async def keep_overhead(self, conversation_id: UUID, tokens: int) -> None:
        """Record what a turn measured its instructions and tool schemas at.

        Written only when it moved, because it moves only when the agent does -
        a tool bound, a prompt rewritten - and an UPDATE per turn to store the
        number that was already there is a write nobody reads differently.

        The next run starts from it. Measured from a response, it is otherwise
        unknown until one arrives, so a one-request turn - most of them - could
        never tell a window with no room for a summary from one that works (#49).
        """
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if conversation is None or conversation.overhead_tokens == tokens:
            return
        await conversation_repo.set_overhead(self.db, db_conversation=conversation, tokens=tokens)

    async def keep_reminder_state(self, conversation_id: UUID, state: dict[str, Any]) -> None:
        """Record how far this conversation's system-reminders cadence has advanced.

        Written only when it moved, for the reason :meth:`keep_overhead` is: a
        turn that fired no reminder leaves the counters where they were, and an
        UPDATE per turn to store the number already there is a write nobody reads
        differently. The next run seeds from it, so a reminder set to fire every
        N requests keeps counting across turns rather than resetting each one.
        """
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if conversation is None or conversation.reminder_state == state:
            return
        await conversation_repo.set_reminder_state(
            self.db, db_conversation=conversation, state=state
        )

    async def keep_plan(self, conversation_id: UUID, items: list[dict[str, Any]]) -> None:
        """Record the checklist the run left this conversation with.

        Written only when it moved, for the reason :meth:`keep_overhead` is - and
        an empty list is treated as no plan, which is what makes this safe to call
        for every run: an agent that binds no planning capability dumps `[]` every
        turn, and `[]` against a column that is null is not a change.

        The next run seeds its store from this, so a plan written in one turn is
        still there in the next. It used to be a run's alone, and a chat message
        is a run: the agent denied a plan it had written two messages earlier
        (#1077).
        """
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if conversation is None or (conversation.plan_items or []) == items:
            return
        await conversation_repo.set_plan(self.db, db_conversation=conversation, items=items)

    async def keep_summary(self, conversation_id: UUID, messages: list[dict[str, Any]]) -> None:
        """Write down the history a summary reduced this conversation to.

        Called once a turn's rows are written, so the ordinal it records covers
        the answer as well as the question - which is what stops the next turn
        replaying the summary *and* the turn already inside it.
        """
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if conversation is None:
            return
        await conversation_repo.set_summary(
            self.db,
            db_conversation=conversation,
            messages=messages,
            ordinal=await conversation_repo.last_ordinal(self.db, conversation_id),
        )

    async def get_conversation(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID,
        include_messages: bool = False,
        user_id: UUID | None = None,
        for_write: bool = False,
        turn: bool = False,
        include_favourite: bool = True,
        ctx: AuthContext | None = None,
    ) -> Conversation:
        """One conversation, checked against the tenant first and the reader second.

        A row belonging to another organization is reported as missing rather
        than forbidden: "you may not read this" tells somebody in another tenant
        that the id exists.

        `for_write` picks which of the two questions is asked. Reading and
        writing stopped being one question when participation became a way in:
        see `_may_read` and `_may_write`. `turn` narrows the write to adding a
        person's turn, the one write a project's members share.

        `include_favourite` is on by default so that a route cannot forget it -
        that is the whole of #1254, and the flag reached two responses out of
        eight while each route had to remember. It is turned **off** by the
        callers that use this only to authorize and then discard the row:
        `GET /conversations/{id}/messages` resolves it through `transcript`, which
        serializes no star.
        """
        conversation = await conversation_repo.get_conversation_by_id(
            self.db, conversation_id, include_messages=include_messages
        )
        if not conversation:
            raise NotFoundError(
                message="Conversation not found",
                details={"conversation_id": str(conversation_id)},
            )
        if conversation.organization_id is not None and str(conversation.organization_id) != str(
            organization_id
        ):
            raise NotFoundError(
                message="Conversation not found",
                details={"conversation_id": str(conversation_id)},
            )
        if user_id is not None:
            allowed = (
                await self._may_write(conversation, user_id, turn=turn, ctx=ctx)
                if for_write
                else await self._may_read(conversation, user_id, ctx=ctx)
            )
            if not allowed:
                raise NotFoundError(
                    message="Conversation not found",
                    details={"conversation_id": str(conversation_id)},
                )
        if include_messages and user_id is not None and conversation.messages:
            message_ids = [m.id for m in conversation.messages]
            user_ratings = await message_rating_repo.get_user_ratings_for_messages(
                self.db, message_ids=message_ids, user_id=user_id
            )
            rating_counts = await message_rating_repo.get_rating_counts_for_messages(
                self.db, message_ids=message_ids
            )
            for msg in conversation.messages:
                msg.user_rating = user_ratings.get(msg.id)  # ty: ignore[unresolved-attribute]
                msg.rating_count = rating_counts.get(msg.id)  # ty: ignore[unresolved-attribute]
        if include_messages and conversation.messages:
            await self._attach_authors(conversation.messages)
            await self._attach_senders(conversation.messages, conversation)
            await self._attach_replies(conversation.messages)
        # Here rather than at each route, because this is the one read every
        # reader-scoped one goes through - `update`, `archive` and `set_favourite`
        # all return the object it hands back. Only two responses carried the flag
        # before, so `GET /conversations/{id}` and the PATCH answered `false` to a
        # caller who really had starred the thread (#1254). Skipped entirely for a
        # call with no reader: an internal read pays no query, and a star belongs
        # to nobody in particular there.
        if include_favourite:
            await self._attach_favourites([conversation], user_id=user_id)
        return conversation

    async def _may_read(
        self, conversation: Conversation, user_id: UUID, *, ctx: AuthContext | None = None
    ) -> bool:
        """Whether this reader may open this conversation.

        Four ways in. The owner, whoever it was explicitly shared with, and - for
        a thread that came out of a room - a participant the platform confirms is
        *still in the channel*, the same set `_reachable_by` puts the thread in
        front of in the list. Having spoken is not enough on its own: participation
        that stopped at the `messages` table outlived the access the platform
        grants, so somebody removed from the channel kept reading everything said
        after they left (#641). `channels.membership` is the check, and it fails
        closed.

        The fourth is a trigger's run-log: it has no owner (a schedule runs with
        nobody at the keyboard) and is never shared, so the three above all refuse
        it and clicking a schedule in the sidebar opened nothing. Its access
        defers to the trigger's agent instead, which is where a trigger's
        private/org visibility already lives - a trigger is operational state on
        the agent, not a resource shared on its own. That way in needs the caller's
        `ctx` to resolve the grant, so a read with none (a channel or an export)
        does not get it.

        **A project's chat is read through the project alone** - by its
        starter as much as anybody. Ownership answered first, so a member who
        lost the project kept reading the chats they had started in it, and
        through them its files; the project as it stands decides, for everyone.
        """
        if getattr(conversation, "project_id", None) is not None:
            return await self._project_allows(conversation, user_id, ctx, Perm.PROJECTS_VIEW)
        owner = getattr(conversation, "user_id", None)
        if owner is not None and str(owner) == str(user_id):
            return True
        if await conversation_share_repo.get_share(self.db, conversation.id, user_id):
            return True
        if await channel_membership.confirms_participation(
            self.db, conversation_id=conversation.id, user_id=user_id
        ):
            return True
        return await self._may_read_trigger_log(conversation, ctx)

    async def _member_ctx(self, organization_id: UUID, user_id: UUID) -> AuthContext | None:
        """The context a member acts with in an organization; `None` for a non-member."""
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if membership is None:
            return None
        return AuthContext(user_id=user_id, organization_id=organization_id, role=membership.role)

    async def visible_project_ids(
        self, user_id: UUID, organization_id: UUID, *, reader: AuthContext | None = None
    ) -> list[UUID]:
        """The projects whose chats this person reads, their own chats there included.

        A project's chats are its members', so `/chat` lists them with the
        reader's own, grouped under the project - not only the ones the reader
        has typed in, which left a new member looking at a project whose chats
        were nowhere in their list. Decided on the projects as they stand, so
        losing a project takes its chats out of the list with it (#641).

        `reader` is the request's own context for this person, when the caller
        has one, and saves reading the membership again. Without a role it is
        not a member's, so it reaches no project.
        """
        ctx = reader if reader is not None else await self._member_ctx(organization_id, user_id)
        if ctx is None or not ctx.role:
            return []
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=PROJECT, perm=Perm.PROJECTS_VIEW
        )
        return await project_repo.visible_ids(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            see_all=shared is None,
            shared_ids=[] if shared is None else shared,
        )

    async def _project_allows(
        self, conversation: Conversation, user_id: UUID, ctx: AuthContext | None, perm: Perm
    ) -> bool:
        """Whether the project this chat is in lets this person `perm` it.

        A project's chats are the project's: whoever may see it reads them, and
        whoever may work in it continues them. Decided on the project as it
        stands, so a member who loses the project loses its chats with it.

        A caller with no `ctx` - the chat socket, which resolves a thread before
        it builds one - is given their membership's, as a project chat started
        from that socket is.
        """
        project_id = getattr(conversation, "project_id", None)
        if project_id is None or conversation.organization_id is None:
            return False
        ctx = ctx or await self._member_ctx(conversation.organization_id, user_id)
        if ctx is None:
            return False
        project = await project_repo.get(
            self.db, project_id, organization_id=conversation.organization_id
        )
        return project is not None and await resolve_access(
            self.db, ctx, project, perm, resource_type=PROJECT
        )

    async def _may_read_trigger_log(
        self, conversation: Conversation, ctx: AuthContext | None
    ) -> bool:
        """Whether this conversation is a trigger's run-log the caller may see.

        A trigger's run-log is the transcript of runs the agent made under its
        creator's authority, so it is gated exactly as a run transcript is: the
        caller must hold `runs:view` *and* be able to view the trigger's agent.
        Without the `runs:view` floor a Viewer holding only `agents:view` (or a
        per-agent READ grant) could pull a trigger's `conversation_id` off the
        listing and read the whole run-log of an agent they may see but not use -
        messages and tool calls produced with the creator's run authority - which
        the ordinary run path (`agent_runner`, `runs:view`) refuses.

        The per-agent `resolve_access` stays on top of that floor, so a private
        agent's log is still confined to the people who can see the agent and an
        org-visible one is open to the organization. The agent is loaded
        tenant-scoped to the conversation's own organization, so a run-log never
        resolves against an agent in another tenant.
        """
        if ctx is None or not ctx.has(Perm.RUNS_VIEW):
            return False
        trigger = await agent_trigger_repo.get_by_conversation_id(self.db, conversation.id)
        if trigger is None:
            return False
        agent = await agent_repo.get(
            self.db, trigger.agent_id, organization_id=conversation.organization_id
        )
        if agent is None:
            return False
        return await resolve_access(self.db, ctx, agent, Perm.AGENTS_VIEW, resource_type=AGENT)

    async def _may_write(
        self,
        conversation: Conversation,
        user_id: UUID,
        *,
        turn: bool = False,
        ctx: AuthContext | None = None,
    ) -> bool:
        """Whether this reader may change or delete this conversation.

        Deliberately *not* `_may_read`, and this is the whole reason the two
        exist. Every mutating method here authorizes by resolving the row -
        renaming, archiving, deleting, appending a turn - so widening the read to
        a room's participants widened those too: a Viewer who said one thing in a
        channel could delete the room's transcript, or append a
        `role: "assistant"` turn that everybody reads in `/chat` and the model is
        handed back as its own words on the next turn. Speaking in a room is a
        claim on being shown the thread, never a claim on a row somebody owns.

        A thread with no owner recorded - a room where nobody has linked an
        account - is writable by its participants, the same set `_may_read`
        admits (#701). It used to be writable by the whole organization, which is
        what it was before participation existed: any member could delete a
        transcript the list showed them nothing of, or append a
        `role: "assistant"` turn to it. There is no owner to defer to, so the
        people who were in the room are who tidies it up; participation carries
        the write only while there is nobody it would be taken from.

        **A share carries the write only at `edit`.** Any share at all used to,
        so the two levels the sharing dialog offers meant the same thing: a
        conversation shared to *view* could be renamed, archived, deleted, or
        given a `role: "assistant"` turn that everybody reads in `/chat` and the
        model is handed back as its own words. The level is stated to whoever
        grants it, so it has to be the level that is enforced (#931).

        A project's chat is the project's here as on read: a turn needs the
        right to work in the project, whoever started the chat, and renaming,
        archiving or deleting it stays its starter's while the project is still
        theirs to see.
        """
        owner = getattr(conversation, "user_id", None)
        if getattr(conversation, "project_id", None) is not None:
            if turn:
                return await self._project_allows(conversation, user_id, ctx, Perm.PROJECTS_USE)
            return (
                owner is not None
                and str(owner) == str(user_id)
                and await self._project_allows(conversation, user_id, ctx, Perm.PROJECTS_VIEW)
            )
        if owner is not None and str(owner) == str(user_id):
            return True
        share = await conversation_share_repo.get_share(self.db, conversation.id, user_id)
        if share is not None and share.permission == "edit":
            return True
        if owner is None:
            return await channel_membership.confirms_participation(
                self.db, conversation_id=conversation.id, user_id=user_id
            )
        return False

    async def _attach_authors(self, messages: list[Message]) -> None:
        """Put a name on each turn that came from a chat account.

        Outside the ratings block above on purpose: ratings are *this reader's*,
        so they are only fetched when there is a reader, while who wrote a turn is
        a property of the turn. A channel thread read with no `user_id` - an admin
        view, an export - would otherwise render a room full of anonymous "hej".
        """
        authors = await conversation_repo.authors_of(
            self.db, [m.channel_identity_id for m in messages if m.channel_identity_id]
        )
        if not authors:
            return
        for msg in messages:
            if msg.channel_identity_id is not None:
                msg.author = authors.get(msg.channel_identity_id)  # ty: ignore[unresolved-attribute]

    async def _attach_senders(
        self, messages: Sequence[Message], conversation: Conversation
    ) -> None:
        """Put the person on each turn somebody signed in typed.

        A project's chat is continued by whoever works in it, so its user turns
        are several people's; one query for the page, none when nobody is named.

        A project chat's console turn naming nobody is one whose writer's
        account has since gone - every earlier one was given its owner by
        `0141_message_author_user.py` - and says so, rather than reading as the reader's own
        "You" or as whoever started the thread.
        """
        in_project = getattr(conversation, "project_id", None) is not None
        authored = []
        for msg in messages:
            author_id = getattr(msg, "author_user_id", None)
            if author_id is not None:
                authored.append((msg, author_id))
            elif in_project and _a_persons_turn(msg):
                msg.sender_gone = True  # ty: ignore[unresolved-attribute]
        if not authored:
            return
        people = await conversation_repo.users_by_id(self.db, {a for _, a in authored})
        for msg, author_id in authored:
            author = people.get(author_id)
            if author is None:
                msg.sender_gone = True  # ty: ignore[unresolved-attribute]
            else:
                msg.sender = ChatPerson.of(author)  # ty: ignore[unresolved-attribute]

    async def reply_quoted(self, message: Message) -> MessageReplyRef | None:
        """The quote one turn carries of the message it answers, or `None`."""
        await self._attach_replies([message])
        return getattr(message, "reply_to", None)

    async def _attach_replies(self, messages: Sequence[Message]) -> None:
        """Quote, on each turn that replied to one, the message it answers.

        One query for those outside the page, one for their writers' names.
        """
        replies = [
            (msg, target)
            for msg in messages
            if (target := getattr(msg, "reply_to_message_id", None)) is not None
        ]
        if not replies:
            return
        found = {msg.id: msg for msg in messages}
        found |= await conversation_repo.messages_by_id(
            self.db, {target for _, target in replies if target not in found}
        )
        people = await conversation_repo.users_by_id(
            self.db,
            {
                author
                for _, target in replies
                if (author := getattr(found.get(target), "author_user_id", None)) is not None
            },
        )
        for msg, target in replies:
            answered = found.get(target)
            if answered is None:
                continue
            author = people.get(answered.author_user_id) if answered.author_user_id else None
            msg.reply_to = MessageReplyRef(  # ty: ignore[unresolved-attribute]
                message_id=answered.id,
                role=answered.role,
                excerpt=_excerpt(answered.content),
                sender=ChatPerson.of(author) if author is not None else None,
                agent_id=answered.agent_id,
            )

    async def list_project_chats(
        self,
        project_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Conversation], int]:
        """Every chat in a project, whoever started it, with the people around it.

        Unscoped by reader: the caller has already decided they may see the
        project, and a project's chats are its members'. Each row carries what
        the caller's own list does - agents, running, unread - plus whose it is,
        who has had it open and whose run is at work in it.
        """
        items = await conversation_repo.get_conversations_by_user(
            self.db,
            user_id=None,
            organization_id=organization_id,
            skip=skip,
            limit=limit,
            project_id=project_id,
        )
        total = await conversation_repo.count_conversations(
            self.db, user_id=None, organization_id=organization_id, project_id=project_id
        )
        await self._attach_agents(items)
        await self._attach_running(items)
        await self._attach_unread(items, user_id=user_id)
        await self._attach_people(items)
        return items, total

    async def _attach_people(self, conversations: Sequence[Conversation]) -> None:
        ids = [conversation.id for conversation in conversations]
        readers = await conversation_repo.readers_of(self.db, ids)
        working = await conversation_repo.running_users(self.db, ids)
        here = await chat_room.present_in([str(conversation_id) for conversation_id in ids])
        people = await conversation_repo.users_by_id(
            self.db,
            {c.user_id for c in conversations if c.user_id is not None}
            | set(working.values())
            | {person for room in here.values() for person in room},
        )
        for conversation in conversations:
            owner = people.get(conversation.user_id) if conversation.user_id else None
            worker = people.get(working[conversation.id]) if conversation.id in working else None
            conversation.owner = ChatPerson.of(owner) if owner else None  # ty: ignore[unresolved-attribute]
            conversation.working = ChatPerson.of(worker) if worker else None  # ty: ignore[unresolved-attribute]
            # Somebody whose account went between the heartbeat and this read
            # is simply not drawn.
            conversation.here = [  # ty: ignore[unresolved-attribute]
                ChatPerson.of(people[person])
                for person in here.get(str(conversation.id), [])
                if person in people
            ]
            conversation.seen_by = [  # ty: ignore[unresolved-attribute]
                ChatReader(**ChatPerson.of(user).model_dump(), read_at=read_at)
                for user, read_at in readers.get(conversation.id, [])
            ]

    async def list_conversations(
        self,
        user_id: UUID | None = None,
        *,
        organization_id: UUID,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        agent_id: UUID | None = None,
        include_archived: bool = False,
        archived_only: bool = False,
        sort_by: str = "updated_at",
        sort_dir: str = "desc",
        hide_api: bool = False,
        project_id: UUID | None = None,
        reader: AuthContext | None = None,
    ) -> tuple[list[Conversation], int]:
        """One page of the organization's conversations, each naming who answered.

        The total is counted with the same narrowing as the page, so a caller
        rendering "showing 30 of N" is describing the list it was handed rather
        than the deployment.

        A user's page includes the channel threads they participate in, and the
        participation set is vetted here - against the platform's current
        membership, through `channels.membership` - before the repository sees
        it, so the query never widens on who merely spoke (#641).
        """
        participant_ids: set[UUID] = (
            await channel_membership.confirmed_participant_threads(
                self.db, user_id=user_id, organization_id=organization_id
            )
            if user_id is not None
            else set()
        )
        project_ids = (
            await self.visible_project_ids(user_id, organization_id, reader=reader)
            if user_id is not None
            else []
        )
        items = await conversation_repo.get_conversations_by_user(
            self.db,
            user_id=user_id,
            organization_id=organization_id,
            skip=skip,
            limit=limit,
            search=search,
            agent_id=agent_id,
            include_archived=include_archived,
            archived_only=archived_only,
            sort_by=sort_by,
            sort_dir=sort_dir,
            # Only where the list is the active one. A star survives archiving -
            # the thread is still one somebody cares about - but the band is the
            # active list's, and a band inside the archive would be a second
            # place to look for what archiving just moved (#929).
            #
            # `include_archived` is excluded for a second reason: that listing is
            # the mixed one `ChatContainer` uses to find the conversation somebody
            # has open, and enough old archived favourites at the top of it would
            # push the selected row off the first page.
            favourites_first_for=(
                None if archived_only or include_archived or user_id is None else user_id
            ),
            participant_conversation_ids=participant_ids,
            visible_project_ids=project_ids,
            hide_api=hide_api,
            project_id=project_id,
        )
        total = await conversation_repo.count_conversations(
            self.db,
            user_id=user_id,
            organization_id=organization_id,
            search=search,
            agent_id=agent_id,
            include_archived=include_archived,
            archived_only=archived_only,
            participant_conversation_ids=participant_ids,
            visible_project_ids=project_ids,
            hide_api=hide_api,
            project_id=project_id,
        )
        await self._attach_agents(items)
        await self._attach_favourites(items, user_id=user_id)
        await self._attach_running(items)
        await self._attach_unread(items, user_id=user_id)
        return items, total

    async def _attach_unread(
        self, conversations: Sequence[Conversation], *, user_id: UUID | None
    ) -> None:
        """Say, per row, whether it holds an answer this reader has not seen. One
        query for the page, and none for a listing with no reader - the admin one,
        where being read belongs to nobody in particular."""
        if not conversations:
            return
        unread = (
            set()
            if user_id is None
            else await conversation_repo.unread_ids(
                self.db,
                user_id=user_id,
                conversation_ids=[conversation.id for conversation in conversations],
            )
        )
        for conversation in conversations:
            conversation.unread = conversation.id in unread  # ty: ignore[unresolved-attribute]

    async def mark_read(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
        ctx: AuthContext | None = None,
    ) -> None:
        """Record that this reader has the conversation open, so it is not unread.

        Checked as a read, as a favourite is: somebody a conversation was shared
        with reads it exactly as its owner does.
        """
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            include_favourite=False,
            ctx=ctx,
        )
        await conversation_repo.mark_read(self.db, user_id=user_id, conversation_id=conversation.id)

    async def _attach_running(self, conversations: Sequence[Conversation]) -> None:
        """Say, per row, since when a run has been at work in it, so a list can
        show the thread is busy. Set on the ORM object for the reason
        `_attach_agents` is, and one query for the page."""
        if not conversations:
            return
        since = await conversation_repo.running_since(
            self.db, [conversation.id for conversation in conversations]
        )
        for conversation in conversations:
            conversation.running_since = since.get(conversation.id)  # ty: ignore[unresolved-attribute]

    async def _attach_agents(self, conversations: Sequence[Conversation]) -> None:
        """Name the agents that answered, on each row of a page.

        Set on the ORM object rather than returned alongside it, because the
        route serializes the row straight through the read schema. One query for
        the whole page - see the repository function it calls.

        A conversation can have several: the chat's picker can be changed
        mid-thread, and a transcript relabelled to whoever answered last would
        be a lie about every turn above it.
        """
        if not conversations:
            return
        by_conversation = await conversation_repo.agents_in_conversations(
            self.db, [conversation.id for conversation in conversations]
        )
        for conversation in conversations:
            conversation.agents = [  # ty: ignore[unresolved-attribute]
                ConversationAgent(
                    id=agent.id,
                    slug=agent.slug,
                    name=agent.name,
                    has_avatar=agent.has_avatar,
                    avatar_color=agent.avatar_color,
                )
                for agent in by_conversation.get(conversation.id, [])
            ]

    async def _attach_favourites(
        self, conversations: Sequence[Conversation], *, user_id: UUID | None
    ) -> None:
        """Say, per row, whether this reader has starred it.

        Set on the ORM object for the reason `_attach_agents` is: the route
        serializes the row straight through the read schema. One query for the
        page, and none at all for a listing with no reader - the admin one,
        where a star belongs to nobody in particular and the column would be a
        different person's every request.
        """
        if not conversations:
            return
        starred = (
            set()
            if user_id is None
            else await conversation_repo.favourite_ids(
                self.db,
                user_id=user_id,
                conversation_ids=[conversation.id for conversation in conversations],
            )
        )
        for conversation in conversations:
            conversation.is_favourite = conversation.id in starred  # ty: ignore[unresolved-attribute]

    async def set_favourite(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
        favourite: bool,
        ctx: AuthContext | None = None,
    ) -> Conversation:
        """Star or unstar a conversation for one reader.

        Checked as a **read**, not a write: a star says where a thread sits in
        the starrer's own sidebar and changes nothing about the thread, so
        somebody a conversation was shared with may favourite it exactly as its
        owner may. `for_write` here would refuse the reader the feature is for.

        `ctx` travels for the same reason it does on every other read: without
        it `_may_read_trigger_log` answers false, and a trigger's run-log the
        caller may read through `runs:view` is one they could not star.
        """
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            include_favourite=False,
            ctx=ctx,
        )
        await conversation_repo.set_favourite(
            self.db, user_id=user_id, conversation_id=conversation.id, favourite=favourite
        )
        await self._attach_agents([conversation])
        conversation.is_favourite = favourite  # ty: ignore[unresolved-attribute]
        return conversation

    async def admin_list_with_users(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        user_id: UUID | None = None,
        agent_id: UUID | None = None,
        include_archived: bool = False,
        archived_only: bool = False,
        sort_by: str = "updated_at",
        sort_dir: str = "desc",
    ) -> AdminConversationList:
        rows, total = await conversation_repo.admin_list_with_users(
            self.db,
            skip=skip,
            limit=limit,
            search=search,
            user_id=user_id,
            agent_id=agent_id,
            include_archived=include_archived,
            archived_only=archived_only,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        by_conversation = await conversation_repo.agents_in_conversations(
            self.db, [conv.id for conv, _count, _email in rows]
        )
        items = [
            AdminConversationRead(
                id=conv.id,
                user_id=conv.user_id,
                title=conv.title,
                is_archived=conv.is_archived,
                message_count=msg_count,
                user_email=email,
                agents=[
                    ConversationAgent(
                        id=agent.id,
                        slug=agent.slug,
                        name=agent.name,
                        has_avatar=agent.has_avatar,
                        avatar_color=agent.avatar_color,
                    )
                    for agent in by_conversation.get(conv.id, [])
                ],
                created_at=conv.created_at,
                updated_at=conv.updated_at,
            )
            for conv, msg_count, email in rows
        ]
        return AdminConversationList(items=items, total=total)

    async def for_api_run(
        self,
        ctx: AuthContext,
        conversation_id: UUID | None,
        *,
        prompt: str,
    ) -> tuple[UUID, list[ModelMessage] | None]:
        """The conversation an API run files under, and what the model reads of it.

        A run that names none opens one for the key's issuer, labelled as opened
        over the API, so the next call can continue it and a workspace scoped to
        the conversation has one to be scoped to (#2122). A run that names one
        must name the caller's own, opened over the API, and the model reads its
        history the way a channel thread's is read - the recent window, or the
        summary and what came after it.

        Over the API only: a key that may run agents was never given the person's
        chats, and continuing one would hand their history to the model - and so
        to whoever holds the key - and write the key's run into a thread they
        were having in the console or a channel.

        Raises:
            NotFoundError: If the named conversation is unknown or not the caller's.
            BadRequestError: If it was not opened over the API.
        """
        if conversation_id is None:
            opened = await conversation_repo.create_conversation(
                self.db,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                title=_api_title(prompt),
                origin="api",
            )
            return opened.id, None
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            for_write=True,
            include_favourite=False,
        )
        if conversation.origin != "api":
            raise refused_field(
                "conversation_id",
                "Only a conversation opened over the API can be continued over the API",
            )
        return conversation_id, await self.model_history(
            conversation_id, limit=API_HISTORY_MESSAGES
        )

    async def create_conversation(
        self,
        data: ConversationCreate,
    ) -> Conversation:
        """Create a new conversation."""
        if data.organization_id is None:
            raise BadRequestError(message="A conversation must belong to an organization")
        return await conversation_repo.create_conversation(
            self.db,
            organization_id=data.organization_id,
            user_id=data.user_id,
            title=data.title,
            project_id=data.project_id,
        )

    async def update_conversation(
        self,
        conversation_id: UUID,
        data: ConversationUpdate,
        *,
        organization_id: UUID,
        user_id: UUID | None = None,
    ) -> Conversation:
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            for_write=True,
        )
        update_data = writable(data, over=Conversation)
        return await conversation_repo.update_conversation(
            self.db, db_conversation=conversation, update_data=update_data
        )

    async def archive_conversation(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID | None = None,
    ) -> Conversation:
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            for_write=True,
        )
        return await conversation_repo.archive_conversation(self.db, db_conversation=conversation)

    async def delete_conversation(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID | None = None,
    ) -> bool:
        """Delete one thread, its turns, and the files that arrived with them.

        `user_id` is what makes this self-service: a person deletes their own
        chat history without an administrator, and the ownership check is inside
        `get_conversation` rather than at the route, so every caller gets it
        (FA-015).

        **The attachments' bytes are unlinked, and they were not.**
        `chat_files.message_id` is `ON DELETE CASCADE` from `messages`, which
        cascades from `conversations` - so deleting a thread removed every row
        that named a file and left the file itself on disk: personal data kept
        after somebody asked for it to be deleted, and reachable by nothing
        (#1421). The paths are read before the delete, because afterwards there
        is nothing left to read them from.

        The unlink is handed to `spawn_after_commit` for the reason #1293 gives:
        an unlink before the commit is undone by a rollback as a file already
        gone, leaving a restored row pointing at nothing.
        """
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            for_write=True,
            include_favourite=False,
        )
        await self.forget_stored_files(organization_id, [conversation_id])
        await conversation_repo.delete_conversation(self.db, db_conversation=conversation)
        return True

    async def forget_stored_files(
        self, organization_id: UUID, conversation_ids: Sequence[UUID]
    ) -> None:
        """Delete, once the transaction commits, what these threads keep outside the database.

        Called before the threads are deleted: the attachments' paths are read
        from rows that cascade away with them - see :meth:`delete_conversation`.
        """
        attachments = [
            path
            for conversation_id in conversation_ids
            for path in await personal_data_repo.attachment_paths_in(self.db, conversation_id)
        ]
        if attachments:
            spawn_after_commit(
                self.db,
                delete_files_best_effort(attachments),
                name="delete-conversation-attachments",
            )
        # And whatever the `media` capability offloaded out of a thread's
        # compacted history. Those objects are content-addressed, so nothing
        # records that they are still referenced - the thread's own prefix is
        # their lifetime, and this is where it ends (#55).
        for conversation_id in conversation_ids:
            spawn_after_commit(
                self.db,
                delete_prefix_best_effort(prefix_for(organization_id, conversation_id)),
                name="delete-conversation-media",
            )

    async def get_message(self, message_id: UUID) -> Message:
        message = await conversation_repo.get_message_by_id(self.db, message_id)
        if not message:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": str(message_id)},
            )
        return message

    async def transcript(
        self,
        conversation_id: UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        organization_id: UUID,
        include_tool_calls: bool = False,
        user_id: UUID | None = None,
        ctx: AuthContext | None = None,
    ) -> tuple[list[Message | MessageRead], int, ConversationCost | None]:
        """One conversation's messages and its cost, for a reader allowed to see them.

        `organization_id` keeps this out of another tenant's transcript;
        `user_id` keeps it out of a colleague's. Both are needed: the tenant
        check alone still lets any member of the organization read any
        conversation in it, which is not what `GET /conversations/{id}` does
        one route above.

        When `user_id` is given the messages are also enriched with that
        reader's rating - a second job for one argument, and the reason its
        authorizing half was missed for so long.

        The page and the cost share one authorization: on a channel thread each
        `get_conversation` can ask the platform whether the reader is still in
        the room.

        The cost is summed over every turn, not over the page asked for, and is
        `None` where nothing in the thread was ever measured.
        """
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            include_favourite=False,
            ctx=ctx,
        )
        items = await conversation_repo.get_messages_by_conversation(
            self.db,
            conversation_id,
            skip=skip,
            limit=limit,
            include_tool_calls=include_tool_calls,
        )
        total = await conversation_repo.count_messages(self.db, conversation_id)
        await self._attach_senders(items, conversation)
        await self._attach_replies(items)
        outcomes = await conversation_repo.run_outcomes(
            self.db, {msg.run_id for msg in items if msg.run_id is not None}
        )
        cost = await self._cost(conversation_id)
        if user_id is not None and items:
            message_ids = [msg.id for msg in items]
            user_ratings = await message_rating_repo.get_user_ratings_for_messages(
                self.db, message_ids=message_ids, user_id=user_id
            )
            rating_counts = await message_rating_repo.get_rating_counts_for_messages(
                self.db, message_ids=message_ids
            )

            enriched: list[Message | MessageRead] = []
            for msg in items:
                msg_schema = MessageRead.model_validate(msg)
                msg_schema.user_rating = user_ratings.get(msg.id)
                msg_schema.rating_count = rating_counts.get(msg.id)
                # So a turn a run was stopped mid-way through can say so. Without
                # it a cancelled run's half-written answer reads exactly like a
                # complete one, and the reader believes the agent finished.
                outcome = outcomes.get(msg.run_id) if msg.run_id else None
                msg_schema.run_status = outcome.status if outcome else None
                msg_schema.run_duration_ms = outcome.duration_ms if outcome else None
                enriched.append(msg_schema)
            return enriched, total, cost
        return list(items), total, cost

    async def _cost(self, conversation_id: UUID) -> ConversationCost | None:
        """The thread's totals. Unscoped: the caller must have authorized the read."""
        totals = await conversation_repo.conversation_cost(self.db, conversation_id)
        if totals is None:
            return None
        input_tokens, output_tokens, cost_usd, cost_is_partial = totals
        return ConversationCost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            cost_is_partial=cost_is_partial,
        )

    async def add_message(
        self,
        conversation_id: UUID,
        data: MessageCreate,
        *,
        organization_id: UUID,
        user_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Message:
        """Append one message into a conversation in `organization_id`.

        Required, and for the sharper reason: this writes. Without a tenant,
        any signed-in caller could append a turn - including one with
        `role: "assistant"` - to any conversation in the deployment, and it
        would render to its owner as the agent's own words. That is not a
        possibility any more: the tenant is a `UUID` on every read and write
        here, and the sentinel that used to spell "no tenant check, on purpose"
        went with the deployment-wide conversation browser, its only caller.

        `user_id` narrows that to the owner, somebody the conversation was
        shared with or, on a thread with no owner, somebody who spoke in it -
        `_may_write`, not `_may_read`, because a `role: "assistant"`
        turn appended by a room's participant is read as the agent's own words by
        everybody in the thread and by the model on the next turn. It is optional
        because one caller has no user to check: the assistant turn is written by
        the agent, after `persist_user_turn` has already resolved the same
        conversation for the person who asked.

        `run_id` is a keyword rather than a field on `MessageCreate` because
        that schema is bound from a request body. A run id taken from a caller
        would put their words in another organization's run transcript - the
        route scopes the conversation, and a bare id carries nothing to scope.
        Only the runner knows which run produced a turn, and only the runner
        passes this.

        An archived conversation is closed to new messages: archiving is the
        user saying "this thread is finished", and a message appended afterwards
        would silently reopen it.
        """
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            for_write=True,
            turn=data.role == "user",
            include_favourite=False,
        )
        if conversation.is_archived:
            raise BadRequestError(
                message="Conversation is archived",
                details={"conversation_id": str(conversation_id)},
            )
        if user_id is not None and data.role != "user" and conversation.project_id is not None:
            # A project's chat is read by the whole project, and the model reads
            # it back as its own words: an agent's turn written by a person would
            # be a fabricated answer everybody else trusts. The runs write those,
            # with no person behind the call.
            raise refused_field("role", "In a project's chat, write your own turns only")
        if data.reply_to_message_id is not None:
            answered = await conversation_repo.get_message_by_id(self.db, data.reply_to_message_id)
            if answered is None or answered.conversation_id != conversation.id:
                raise refused_field(
                    "reply_to_message_id", "Reply to a message in this conversation"
                )
        return await conversation_repo.create_message(
            self.db,
            conversation_id=conversation_id,
            role=data.role,
            content=data.content,
            thinking=data.thinking,
            # Dumped without its empty fields, so a text part is `{"type": "text",
            # "text": ...}` rather than that plus a null `tool_call_id`. What comes
            # back validates the same either way; this is what a person reading the
            # column sees.
            parts=(
                None
                if data.parts is None
                else [part.model_dump(exclude_none=True) for part in data.parts]
            ),
            model_name=data.model_name,
            tokens_used=data.tokens_used,
            # Every field the schema carries, and the two at the end were being
            # dropped here: `persist_assistant_turn` built them, the model documents
            # why they are per-message, and this call did not forward them - so every
            # assistant row in the database had a null agent and a null version, and
            # a reloaded transcript could not say who said what or under which
            # instructions. A partial forward is the failure mode this shape invites,
            # which is why it is now all of them.
            input_tokens=data.input_tokens,
            output_tokens=data.output_tokens,
            cache_read_tokens=data.cache_read_tokens,
            cache_write_tokens=data.cache_write_tokens,
            cost_usd=data.cost_usd,
            cost_is_partial=data.cost_is_partial,
            context_used_tokens=data.context_used_tokens,
            agent_id=data.agent_id,
            agent_version_id=data.agent_version_id,
            run_id=run_id,
            # Whose words these are: in a project's chat, not always the owner's.
            author_user_id=user_id if data.role == "user" else None,
            reply_to_message_id=data.reply_to_message_id,
        )

    async def delete_message(self, message_id: UUID) -> bool:
        deleted = await conversation_repo.delete_message(self.db, message_id)
        if not deleted:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": str(message_id)},
            )
        return True

    async def get_tool_call(self, tool_call_id: UUID) -> ToolCall:
        tool_call = await conversation_repo.get_tool_call_by_id(self.db, tool_call_id)
        if not tool_call:
            raise NotFoundError(
                message="Tool call not found",
                details={"tool_call_id": str(tool_call_id)},
            )
        return tool_call

    async def start_tool_call(
        self,
        message_id: UUID,
        data: ToolCallCreate,
        *,
        parked: bool = False,
        mcp_connection_id: UUID | None = None,
    ) -> ToolCall:
        """Write one tool call under a message.

        `parked` is a keyword rather than a field on `ToolCallCreate` for the
        reason `MessageCreate` carries no `run_id`: the schema is bindable from
        a request body, and whether a call is awaiting a person is the runner's
        fact, not a caller's claim - as is `mcp_connection_id`, the organization
        MCP connection that served the call.
        """
        await self.get_message(message_id)
        return await conversation_repo.create_tool_call(
            self.db,
            message_id=message_id,
            tool_call_id=data.tool_call_id,
            tool_name=data.tool_name,
            args=data.args,
            started_at=data.started_at or datetime.now(UTC),
            status=parked_status(data.tool_name) if parked else "running",
            mcp_connection_id=mcp_connection_id,
        )

    async def complete_tool_call(
        self,
        tool_call_id: UUID,
        data: ToolCallComplete,
    ) -> ToolCall:
        tool_call = await self.get_tool_call(tool_call_id)
        return await conversation_repo.complete_tool_call(
            self.db,
            db_tool_call=tool_call,
            result=data.result,
            completed_at=data.completed_at or datetime.now(UTC),
            success=data.success,
        )

    async def link_files_to_message(
        self, message_id: UUID, file_ids: list[str], *, user_id: UUID
    ) -> None:
        """Attach `user_id`'s own unlinked files to a message, refusing anything else.

        The ids come off a socket payload, so each must resolve to the caller's
        own *unlinked* row: a foreign id would render another user's filename in
        this conversation and silently pull the file off the message it already
        hangs on (#706). Refused, never narrowed - a turn that quietly dropped an
        attachment would read as an agent ignoring the file it was asked about.
        A file that is not the caller's answers exactly like one that does not
        exist, so an id cannot be probed for whether it is taken. An id that is
        not a UUID at all is refused the same loud way: a `ValueError` here used
        to fall into the caller's infrastructure net and resurface a step later
        as a generic failed turn, after the message had already been persisted.
        """
        ids, malformed = _file_uuids(file_ids)
        if malformed:
            raise BadRequestError(message="Invalid file id", details={"file_ids": malformed})
        if not ids:
            return
        rows = await chat_file_repo.get_many(self.db, ids, user_id=user_id)
        found = {row.id for row in rows}
        missing = sorted(fid for fid in set(ids) if fid not in found)
        if missing:
            raise NotFoundError(message="File not found", details={"file_ids": missing})
        taken = sorted(row.id for row in rows if row.message_id is not None)
        if taken:
            raise BadRequestError(
                message="File is already attached to a message",
                details={"file_ids": taken},
            )
        linked = await chat_file_repo.link_to_message(
            self.db, message_id=message_id, file_ids=ids, user_id=user_id
        )
        if linked != len(set(ids)):
            # The read above and the UPDATE are two statements, so a concurrent
            # turn naming the same file can take a row between them; the count
            # is what turns that race into the same refusal instead of a message
            # that quietly lost its attachment (#706).
            raise BadRequestError(
                message="File is already attached to a message",
                details={"file_ids": sorted(set(ids))},
            )

    async def list_turn_attachments(
        self, message_id: UUID | None, file_ids: list[str], *, user_id: UUID
    ) -> list[Any]:
        """This turn's attachments: the caller's own files among `file_ids` that
        are linked to this turn's message or still unlinked (#1756).

        The run's own load path, distinct from `list_attached_files`: that one
        validates a *fresh* submission and refuses an already-linked id, which is
        exactly what the turn's files are once `persist_user_turn` has linked them.
        Loaded by id (the primary key) and scoped to the caller (#706). A file a
        best-effort `link_files_to_message` left unlinked is still read, so a
        transient link failure does not silently drop the turn's attachments; a
        file already on a *different* message is skipped - `persist_user_turn`
        refuses to re-link one, so it never reaches here.

        `message_id` is None when `persist_user_turn` swallowed a write failure and
        wrote no prompt row: only the caller's still-unlinked uploads then match, so
        the files still reach the model rather than being dropped (#1654 review).
        """
        ids, _ = _file_uuids(file_ids)
        rows = await chat_file_repo.get_many(self.db, ids, user_id=user_id)
        kept = [row for row in rows if row.message_id in (message_id, None)]
        kept.sort(key=lambda row: row.created_at)
        return kept

    async def list_attached_files(self, file_ids: list[str], *, user_id: UUID) -> list[Any]:
        """The caller's rows behind the ids a client sent; anybody else's resolve to nothing (#706).

        The ids come off an untyped socket payload, so one that is not a UUID is
        refused as validation naming `file_ids` - the same loud refusal
        `link_files_to_message` gives. A bare `UUID()` here raised a `ValueError`
        that the turn handler caught in its infrastructure net and resurfaced a
        step later as a generic failed turn, logged as a server error.
        """
        ids, malformed = _file_uuids(file_ids)
        if malformed:
            raise BadRequestError(message="Invalid file id", details={"file_ids": malformed})
        rows = await chat_file_repo.get_many(self.db, ids, user_id=user_id)
        # Every requested id has to resolve to a row of theirs that nothing has
        # claimed yet. Returning only what matched ran the turn on silently
        # partial input - billed, answered, and missing the document the caller
        # believed it had sent - and an already-linked file was worse: the model
        # received it while `_attach` updated no row, so the new turn could not
        # show the file it had actually used (#936).
        by_id = {row.id: row for row in rows}
        unknown = [str(file_id) for file_id in ids if file_id not in by_id]
        claimed = [str(row.id) for row in rows if row.message_id is not None]
        if unknown or claimed:
            raise BadRequestError(
                message="Those files cannot be attached to this message",
                details={"unknown": unknown, "already_attached": claimed},
            )
        return rows


def _a_persons_turn(message: Message) -> bool:
    """A turn somebody typed in the console - not an answer, not a chat account's."""
    return message.role == "user" and getattr(message, "channel_identity_id", None) is None


_EXCERPT_CHARS = 280
"""How much of a replied-to message is quoted to the model and above the reply."""


def _excerpt(text: str) -> str:
    """A message as one short line: its whitespace folded, its tail cut."""
    flat = " ".join(text.split())
    return flat if len(flat) <= _EXCERPT_CHARS else f"{flat[:_EXCERPT_CHARS]}…"


def _whose(message: Message, people: dict[UUID, User]) -> str:
    """Who wrote a quoted message, as the model is told it: its own answer is "you"."""
    if message.role == "assistant":
        return "your earlier answer"
    author = people.get(message.author_user_id) if message.author_user_id else None
    return ChatPerson.of(author).name if author is not None else "an earlier message"
