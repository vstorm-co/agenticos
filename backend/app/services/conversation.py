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
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.updates import writable
from app.repositories import (
    chat_file_repo,
    conversation_repo,
    conversation_share_repo,
    message_rating_repo,
)
from app.schemas.conversation import (
    ConversationAgent,
    ConversationCost,
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
    ToolCallComplete,
    ToolCallCreate,
)
from app.schemas.conversation_share import AdminConversationList, AdminConversationRead
from app.services.channels import membership as channel_membership

logger = logging.getLogger(__name__)

UNSCOPED: Final = "unscoped"
"""Read this conversation without a tenant predicate, on purpose.

`organization_id` used to default to `None` on the methods below, and `None`
meant unscoped. Two routes serving ordinary members simply omitted it, and any
signed-in user could read and append to any conversation in the deployment.
An omission cannot express intent; this can, and `rg UNSCOPED` lists every
place that claims it.

There is one caller, `/admin/conversations/{id}`, which exists to read across
tenants and is gated on `CurrentAppAdmin`. Anything serving an ordinary member
passes the active organization.
"""

type OrgScope = UUID | Literal["unscoped"]
"""A tenant to check against, or an explicit refusal to check one."""


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


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_conversation(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID,
        include_messages: bool = False,
        user_id: UUID | None = None,
        for_write: bool = False,
    ) -> Conversation:
        """One conversation, checked against the tenant first and the reader second.

        A row belonging to another organization is reported as missing rather
        than forbidden: "you may not read this" tells somebody in another tenant
        that the id exists.

        `for_write` picks which of the two questions is asked. Reading and
        writing stopped being one question when participation became a way in:
        see `_may_read` and `_may_write`.
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
                await self._may_write(conversation, user_id)
                if for_write
                else await self._may_read(conversation, user_id)
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
        return conversation

    async def _may_read(self, conversation: Conversation, user_id: UUID) -> bool:
        """Whether this reader may open this conversation.

        Three ways in, and a channel thread needs all three: the owner, whoever
        it was explicitly shared with, and - for a thread that came out of a room
        - a participant the platform confirms is *still in the channel*, the same
        set `_reachable_by` puts the thread in front of in the list. Having
        spoken is not enough on its own: participation that stopped at the
        `messages` table outlived the access the platform grants, so somebody
        removed from the channel kept reading everything said after they left
        (#641). `channels.membership` is the check, and it fails closed.
        """
        owner = getattr(conversation, "user_id", None)
        if owner is not None and str(owner) == str(user_id):
            return True
        if await conversation_share_repo.get_share(self.db, conversation.id, user_id):
            return True
        return await channel_membership.confirms_participation(
            self.db, conversation_id=conversation.id, user_id=user_id
        )

    async def _may_write(self, conversation: Conversation, user_id: UUID) -> bool:
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
        """
        owner = getattr(conversation, "user_id", None)
        if owner is not None and str(owner) == str(user_id):
            return True
        if await conversation_share_repo.get_share(self.db, conversation.id, user_id):
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
            participant_conversation_ids=participant_ids,
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
        )
        await self._attach_agents(items)
        return items, total

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
                )
                for agent in by_conversation.get(conversation.id, [])
            ]

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
                    )
                    for agent in by_conversation.get(conv.id, [])
                ],
                created_at=conv.created_at,
                updated_at=conv.updated_at,
            )
            for conv, msg_count, email in rows
        ]
        return AdminConversationList(items=items, total=total)

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
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            for_write=True,
        )
        await conversation_repo.delete_conversation(self.db, db_conversation=conversation)
        return True

    async def get_conversation_with_messages(
        self,
        conversation_id: UUID,
        *,
        organization_id: OrgScope,
    ) -> Conversation:
        """A transcript, tenant-checked unless the caller passes `UNSCOPED`.

        Required rather than defaulted: the default was `None`, `None` meant
        unscoped, and omitting an argument is indistinguishable from intending
        to omit it. See `UNSCOPED`.
        """
        return await self._resolve(
            conversation_id, organization_id=organization_id, include_messages=True
        )

    async def _resolve(
        self,
        conversation_id: UUID,
        *,
        organization_id: OrgScope,
        include_messages: bool = False,
        user_id: UUID | None = None,
        for_write: bool = False,
    ) -> Conversation:
        """Load one conversation, skipping the tenant check only for `UNSCOPED`."""
        if organization_id != UNSCOPED:
            return await self.get_conversation(
                conversation_id,
                organization_id=organization_id,
                include_messages=include_messages,
                user_id=user_id,
                for_write=for_write,
            )
        conversation = await conversation_repo.get_conversation_by_id(
            self.db, conversation_id, include_messages=include_messages
        )
        if not conversation:
            raise NotFoundError(
                message="Conversation not found",
                details={"conversation_id": str(conversation_id)},
            )
        return conversation

    async def get_message(self, message_id: UUID) -> Message:
        message = await conversation_repo.get_message_by_id(self.db, message_id)
        if not message:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": str(message_id)},
            )
        return message

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        organization_id: OrgScope,
        include_tool_calls: bool = False,
        user_id: UUID | None = None,
    ) -> tuple[list[Message | MessageRead], int]:
        """One conversation's messages, for a reader who is allowed to see them.

        `organization_id` keeps this out of another tenant's transcript;
        `user_id` keeps it out of a colleague's. Both are needed: the tenant
        check alone still lets any member of the organization read any
        conversation in it, which is not what `GET /conversations/{id}` does
        one route above.

        When `user_id` is given the messages are also enriched with that
        reader's rating - a second job for one argument, and the reason its
        authorizing half was missed for so long.
        """
        await self._resolve(conversation_id, organization_id=organization_id, user_id=user_id)
        items = await conversation_repo.get_messages_by_conversation(
            self.db,
            conversation_id,
            skip=skip,
            limit=limit,
            include_tool_calls=include_tool_calls,
        )
        total = await conversation_repo.count_messages(self.db, conversation_id)
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
                enriched.append(msg_schema)
            return enriched, total
        return list(items), total

    async def conversation_cost(
        self,
        conversation_id: UUID,
        *,
        organization_id: OrgScope,
        user_id: UUID | None = None,
    ) -> ConversationCost | None:
        """What this whole thread has cost, or `None` where nothing was measured.

        Scoped exactly as :meth:`list_messages` is, and for the same reason: it
        is a fact about a transcript, and a total is enough to tell how heavily
        somebody else's conversation was used.

        The sum is over every turn, not over the page the caller asked for. A
        client adding up what it was handed would answer "the first hundred
        turns" while the label says "this conversation".
        """
        await self._resolve(conversation_id, organization_id=organization_id, user_id=user_id)
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
        organization_id: OrgScope,
        user_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Message:
        """Append one message into a conversation in `organization_id`.

        Required, and for the sharper reason: this writes. Unscoped, any
        signed-in caller could append a turn - including one with
        `role: "assistant"` - to any conversation in the deployment, and it
        would render to its owner as the agent's own words. See `UNSCOPED`.

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
        conversation = await self._resolve(
            conversation_id, organization_id=organization_id, user_id=user_id, for_write=True
        )
        if conversation.is_archived:
            raise BadRequestError(
                message="Conversation is archived",
                details={"conversation_id": str(conversation_id)},
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
            cost_usd=data.cost_usd,
            cost_is_partial=data.cost_is_partial,
            agent_id=data.agent_id,
            agent_version_id=data.agent_version_id,
            run_id=run_id,
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
    ) -> ToolCall:
        """Write one tool call under a message.

        `parked` is a keyword rather than a field on `ToolCallCreate` for the
        reason `MessageCreate` carries no `run_id`: the schema is bindable from
        a request body, and whether a call is awaiting a person is the runner's
        fact, not a caller's claim.
        """
        await self.get_message(message_id)
        return await conversation_repo.create_tool_call(
            self.db,
            message_id=message_id,
            tool_call_id=data.tool_call_id,
            tool_name=data.tool_name,
            args=data.args,
            started_at=data.started_at or datetime.now(UTC),
            status="awaiting_approval" if parked else "running",
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

    async def list_attached_files(self, file_ids: list[str], *, user_id: UUID) -> list[Any]:
        """The caller's rows behind the ids a client sent; anybody else's resolve to nothing (#706)."""
        return await chat_file_repo.get_many(
            self.db, [UUID(fid) for fid in file_ids], user_id=user_id
        )
