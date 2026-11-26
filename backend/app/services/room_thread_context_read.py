"""Authorized context reads kept separate from a thread's actual replies."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.conversation import Conversation, Message
from app.db.models.room_thread import RoomThread
from app.repositories import conversation as conversation_repo
from app.repositories import room_message_reaction as reaction_repo
from app.repositories import room_thread as thread_repo
from app.schemas.conversation import MessageRead
from app.schemas.room_submission import RoomThreadContextCandidatesRead
from app.schemas.room_thread import RoomThreadContextRead, RoomThreadMovedStubRead
from app.services.conversation import ConversationService
from app.services.room_thread import RoomThreadService
from app.services.room_thread_context_access import RoomThreadContextAccessService


class RoomThreadContextReadService:
    """Recheck source audiences before exposing stored context or using its history."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)
        self.threads = RoomThreadService(db)
        self.access = RoomThreadContextAccessService(db)

    async def _context(
        self,
        *,
        destination: Conversation,
        root_message_id: UUID,
        actor: AuthContext | None,
        responder_agent_id: UUID | None = None,
    ) -> tuple[RoomThread, Conversation] | None:
        row = await thread_repo.get_thread(
            self.db,
            organization_id=destination.organization_id,
            conversation_id=destination.id,
            root_message_id=root_message_id,
        )
        if row is None or row.context_source_conversation_id is None:
            return None
        source = await conversation_repo.get_conversation_by_id(
            self.db, row.context_source_conversation_id, fresh=True
        )
        if source is None or source.organization_id != destination.organization_id:
            raise NotFoundError(message="Thread context is unavailable")
        await self.access.assert_visible(
            destination=destination,
            source=source,
            actor=actor,
            responder_agent_id=responder_agent_id,
        )
        return row, source

    async def assert_history(
        self,
        *,
        destination: Conversation,
        root_message_id: UUID,
        actor: AuthContext | None = None,
        responder_agent_id: UUID | None = None,
    ) -> RoomThread | None:
        """Check live source access and snapshot completeness before each model request."""
        context = await self._context(
            destination=destination,
            root_message_id=root_message_id,
            actor=actor,
            responder_agent_id=responder_agent_id,
        )
        if context is None:
            return None
        row, source = context
        if not await conversation_repo.context_snapshot_exists(
            self.db,
            organization_id=source.organization_id,
            source_conversation_id=source.id,
            message_ids=row.context_message_ids,
        ):
            raise ConflictError(
                message="This thread's saved context changed. Select the context again.",
                details={"reason": "stale_context"},
            )
        return row

    async def _messages(
        self, ctx: AuthContext, source: Conversation, rows: list[Message]
    ) -> list[MessageRead]:
        await self.conversations._attach_senders(rows, source)
        await self.conversations._attach_replies(rows)
        reactions = await reaction_repo.list_aggregates(
            self.db,
            organization_id=source.organization_id,
            conversation_id=source.id,
            message_ids=[row.id for row in rows],
            user_id=ctx.subject_id,
        )
        result = []
        for row in rows:
            message = MessageRead.model_validate(row)
            message.reactions = reactions.get(row.id, [])
            result.append(message)
        return result

    async def detail(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> tuple[RoomThreadContextRead | None, list[MessageRead]]:
        destination, _, _, _ = await self.threads._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        context = await self._context(
            destination=destination, root_message_id=root_message_id, actor=ctx
        )
        if context is None:
            return None, []
        row, source = context
        messages = await thread_repo.context_messages(
            self.db,
            organization_id=source.organization_id,
            source_conversation_id=source.id,
            message_ids=row.context_message_ids,
        )
        if {message.id for message in messages} != set(row.context_message_ids):
            # Keep the revision and boundaries available for an authorized editor
            # to repair the snapshot, without presenting a silently shortened range.
            return self.threads.context_read(row).model_copy(update={"stale": True}), []
        return self.threads.context_read(row), await self._messages(ctx, source, messages)

    async def candidates(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> RoomThreadContextCandidatesRead:
        destination, root, _, user_id = await self.threads._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        if not await self.threads._can_manage(ctx, destination, root, user_id):
            raise AuthorizationError(
                message="Only the thread starter or a room manager may edit its context"
            )
        context = await self._context(
            destination=destination, root_message_id=root_message_id, actor=ctx
        )
        if context is None:
            raise NotFoundError(message="This thread has no selected context")
        row, source = context
        if row.context_first_ordinal is None or row.context_last_ordinal is None:
            raise ConflictError(
                message="Thread context boundaries are unavailable",
                details={"reason": "stale_context"},
            )
        messages = await thread_repo.context_candidates(
            self.db,
            organization_id=source.organization_id,
            source_conversation_id=source.id,
            first_ordinal=row.context_first_ordinal,
            last_ordinal=row.context_last_ordinal,
            root_message_id=root_message_id,
            message_ids=row.context_message_ids,
            limit=1000,
        )
        return RoomThreadContextCandidatesRead(
            source_conversation_id=source.id,
            items=await self._messages(ctx, source, messages),
            total=len(messages),
        )

    async def moved_stubs(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        *,
        page_message_ids: list[UUID],
        before: UUID | None,
        latest: bool,
    ) -> list[RoomThreadMovedStubRead]:
        destination = await self.conversations.get_conversation(
            conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            include_favourite=False,
            ctx=ctx,
        )
        rows = await conversation_repo.moved_thread_stubs(
            self.db,
            organization_id=destination.organization_id,
            conversation_id=destination.id,
            page_message_ids=page_message_ids,
            before=before,
            latest=latest,
        )
        return [
            RoomThreadMovedStubRead(
                root_message_id=row.root_message_id,
                source_conversation_id=destination.id,
                first_ordinal=row.context_first_ordinal,
                last_ordinal=row.context_last_ordinal,
                message_count=len(row.context_message_ids),
                title=title,
            )
            for row, title in rows
            if row.context_first_ordinal is not None and row.context_last_ordinal is not None
        ]
