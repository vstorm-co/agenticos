"""Conversations, their messages and the tool calls inside them.

Everything here is tenant-scoped through one door: `get_conversation` takes the
active organization and every other method routes through it. A repository
function that reads a conversation without a tenant exists (`get_conversation_by_id`,
which says so in its own docstring) and must not be called from anywhere a
member's request reaches.
"""

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.conversation import Conversation, Message, ToolCall
from app.repositories import (
    chat_file_repo,
    conversation_repo,
    conversation_share_repo,
    message_rating_repo,
)
from app.schemas.conversation import (
    ConversationAgent,
    ConversationCreate,
    ConversationUpdate,
    ConversationWithLatestMessage,
    MessageCreate,
    MessageRead,
    ToolCallComplete,
    ToolCallCreate,
)
from app.schemas.conversation_share import AdminConversationList, AdminConversationRead

logger = logging.getLogger(__name__)


def _safe_parse_args(args: Any) -> dict:
    """Parse tool call args to a dict; returns {} on failure."""
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {}
    return {}


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
    ) -> Conversation:
        """One conversation, checked against the tenant first and the reader second.

        A row belonging to another organization is reported as missing rather
        than forbidden: "you may not read this" tells somebody in another tenant
        that the id exists.
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
        if (
            user_id is not None
            and hasattr(conversation, "user_id")
            and conversation.user_id is not None
            and str(conversation.user_id) != str(user_id)
        ):
            # Not the owner - check if user has a share granting access
            share = await conversation_share_repo.get_share(self.db, conversation_id, user_id)
            if not share:
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
        return conversation

    async def list_conversations(
        self,
        user_id: UUID | None = None,
        *,
        organization_id: UUID,
        skip: int = 0,
        limit: int = 50,
        include_archived: bool = False,
    ) -> tuple[list[Conversation], int]:
        """One page of the organization's conversations, each naming who answered."""
        items = await conversation_repo.get_conversations_by_user(
            self.db,
            user_id=user_id,
            organization_id=organization_id,
            skip=skip,
            limit=limit,
            include_archived=include_archived,
        )
        total = await conversation_repo.count_conversations(
            self.db,
            user_id=user_id,
            organization_id=organization_id,
            include_archived=include_archived,
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

    async def list_conversations_admin(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        include_archived: bool = False,
        search: str | None = None,
    ) -> tuple[list[ConversationWithLatestMessage], int]:
        rows, total = await conversation_repo.get_all_conversations_with_count(
            self.db,
            skip=skip,
            limit=limit,
            include_archived=include_archived,
            search=search,
        )

        items = [
            ConversationWithLatestMessage(
                id=conv.id,
                user_id=conv.user_id,
                title=conv.title,
                is_archived=conv.is_archived,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=msg_count,
            )
            for conv, msg_count in rows
        ]
        return items, total

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
        )
        update_data = data.model_dump(exclude_unset=True)
        if (
            "active_knowledge_base_ids" in update_data
            and update_data["active_knowledge_base_ids"] is not None
        ):
            update_data["active_knowledge_base_ids"] = [
                str(kb_id) for kb_id in update_data["active_knowledge_base_ids"]
            ]
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
        )
        await conversation_repo.delete_conversation(self.db, db_conversation=conversation)
        return True

    async def get_conversation_with_messages(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID | None = None,
    ) -> Conversation:
        """A transcript, tenant-checked when a tenant is given.

        `organization_id=None` is **deliberately unscoped**, and there are two
        callers: the app-admin transcript view, which exists to read across
        tenants, and the WebSocket session, which resolved the organization when
        the socket was opened. Grep for this default when auditing cross-tenant
        reads; anything serving an ordinary member must pass the tenant.
        """
        return await self._resolve(
            conversation_id, organization_id=organization_id, include_messages=True
        )

    async def _resolve(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID | None,
        include_messages: bool = False,
        user_id: UUID | None = None,
    ) -> Conversation:
        """Load one conversation, with the tenant check only when there is a tenant."""
        if organization_id is not None:
            return await self.get_conversation(
                conversation_id,
                organization_id=organization_id,
                include_messages=include_messages,
                user_id=user_id,
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

    async def update_kb_settings(
        self,
        conversation_id: UUID,
        active_knowledge_base_ids: list[str] | None,
        *,
        organization_id: UUID,
        user_id: UUID | None = None,
    ) -> Conversation:
        """Which collections this conversation searches.

        Three states, and the difference matters: None restores the agent's own
        defaults, an empty list turns retrieval off for this thread, and a list
        of ids is an explicit choice. A single "enabled" boolean cannot express
        the middle one, which is the state somebody reaches for when the search
        is getting in the way of one particular conversation.
        """
        conversation = await self.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
        )
        update_data: dict[str, Any] = {
            "active_knowledge_base_ids": (
                None
                if active_knowledge_base_ids is None
                else [str(kb_id) for kb_id in active_knowledge_base_ids]
            )
        }
        return await conversation_repo.update_conversation(
            self.db, db_conversation=conversation, update_data=update_data
        )

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
        organization_id: UUID | None = None,
        include_tool_calls: bool = False,
        user_id: UUID | None = None,
    ) -> tuple[list[Message | MessageRead], int]:
        """When user_id is provided, messages are enriched with user_rating and rating_count.

        `organization_id=None` is unscoped - see `get_conversation_with_messages`.
        """
        await self._resolve(conversation_id, organization_id=organization_id)
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

    async def add_message(
        self,
        conversation_id: UUID,
        data: MessageCreate,
        *,
        organization_id: UUID | None = None,
    ) -> Message:
        """Append one message. `organization_id=None` is unscoped - see
        `get_conversation_with_messages`.

        An archived conversation is closed to new messages: archiving is the
        user saying "this thread is finished", and a message appended afterwards
        would silently reopen it.
        """
        conversation = await self._resolve(conversation_id, organization_id=organization_id)
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
            model_name=data.model_name,
            tokens_used=data.tokens_used,
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

    async def list_tool_calls(self, message_id: UUID) -> list[ToolCall]:
        await self.get_message(message_id)
        return await conversation_repo.get_tool_calls_by_message(self.db, message_id)

    async def start_tool_call(
        self,
        message_id: UUID,
        data: ToolCallCreate,
    ) -> ToolCall:
        await self.get_message(message_id)
        return await conversation_repo.create_tool_call(
            self.db,
            message_id=message_id,
            tool_call_id=data.tool_call_id,
            tool_name=data.tool_name,
            args=data.args,
            started_at=data.started_at or datetime.now(UTC),
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

    async def link_files_to_message(self, message_id: UUID, file_ids: list[str]) -> None:
        await chat_file_repo.link_to_message(
            self.db,
            message_id=message_id,
            file_ids=[UUID(fid) for fid in file_ids],
        )

    async def list_attached_files(self, file_ids: list[str]) -> list[Any]:
        return await chat_file_repo.get_many(self.db, [UUID(fid) for fid in file_ids])
