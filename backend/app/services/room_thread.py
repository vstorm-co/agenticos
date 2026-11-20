"""Thread lifecycle, read cursors and follower notifications for room chats."""

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.conversation import Conversation, Message
from app.db.models.room_thread import RoomThread
from app.repositories import (
    conversation as conversation_repo,
)
from app.repositories import (
    member as member_repo,
)
from app.repositories import (
    room_thread as room_thread_repo,
)
from app.schemas.conversation import MessageCreate
from app.schemas.room_thread import (
    RoomThreadActionRead,
    RoomThreadContextActionRead,
    RoomThreadContextRead,
    RoomThreadContextUpdate,
    RoomThreadRangeCreate,
    RoomThreadSummary,
)
from app.services.conversation import ConversationService
from app.services.room_participant import RoomParticipantService
from app.services.room_thread_context_access import RoomThreadContextAccessService


class RoomThreadService:
    """Authorize thread actions against the conversation's current audience."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)
        self.participants = RoomParticipantService(db)
        self.context_access = RoomThreadContextAccessService(db)

    def _announce_thread_changed(self, conversation_id: UUID, root_message_id: UUID) -> None:
        """Invalidate the saved root after this transaction commits."""
        from app.core.background import spawn_after_commit
        from app.services.chat_room import room_thread

        spawn_after_commit(
            self.db,
            room_thread(str(conversation_id), root_message_id),
            name="room-thread",
        )

    async def _conversation_and_root(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> tuple[Conversation, Message, UUID, UUID]:
        organization_id, user_id = self.participants._principal(ctx)
        conversation = await self.participants._conversation(ctx, conversation_id)
        root = await conversation_repo.get_thread_root(
            self.db,
            conversation_id=conversation.id,
            root_message_id=root_message_id,
        )
        if root is None:
            raise NotFoundError(message="Room thread not found")
        return conversation, root, organization_id, user_id

    async def _can_manage(
        self,
        ctx: AuthContext,
        conversation: Conversation,
        root: Message,
        user_id: UUID,
    ) -> bool:
        """A room manager or the human who started the root can manage its thread."""
        if conversation.is_archived or (
            conversation.project_id is None and conversation.room_visibility is None
        ):
            return False
        if not await self.participants._can_post(ctx, conversation):
            return False
        return root.author_user_id == user_id or await self.participants._can_manage(
            ctx, conversation
        )

    async def _summary(
        self,
        ctx: AuthContext,
        conversation: Conversation,
        root: Message,
        organization_id: UUID,
        user_id: UUID,
    ) -> RoomThreadActionRead:
        summaries = await room_thread_repo.summaries_for_roots(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            root_message_ids={root.id},
            user_id=user_id,
        )
        summary = summaries.get(root.id)
        manager = await self._can_manage(ctx, conversation, root, user_id)
        return RoomThreadActionRead(
            conversation_id=conversation.id,
            root_message_id=root.id,
            state=cast(Literal["open", "closed", "archived"], summary.state) if summary else "open",
            following=summary.following if summary else False,
            unread=summary.unread if summary else 0,
            can_manage=manager,
        )

    @staticmethod
    def context_read(row: RoomThread) -> RoomThreadContextRead:
        """Convert a persisted context snapshot into its public, stable shape."""
        if (
            row.context_source_conversation_id is None
            or row.context_start_message_id is None
            or row.context_end_message_id is None
            or row.context_first_ordinal is None
            or row.context_last_ordinal is None
            or not row.context_message_ids
            or row.context_revision < 1
        ):
            raise ConflictError(
                message="This thread's saved context is unavailable.",
                details={"reason": "stale_context"},
            )
        return RoomThreadContextRead(
            source_conversation_id=row.context_source_conversation_id,
            start_message_id=row.context_start_message_id,
            end_message_id=row.context_end_message_id,
            first_ordinal=row.context_first_ordinal,
            last_ordinal=row.context_last_ordinal,
            excluded_message_ids=list(row.context_excluded_message_ids),
            message_ids=list(row.context_message_ids),
            message_count=len(row.context_message_ids),
            moved=row.context_moved,
            revision=row.context_revision,
        )

    async def _context_action(
        self,
        ctx: AuthContext,
        conversation: Conversation,
        root: Message,
        organization_id: UUID,
        user_id: UUID,
        row: RoomThread,
    ) -> RoomThreadContextActionRead:
        summary = await self._summary(ctx, conversation, root, organization_id, user_id)
        return RoomThreadContextActionRead(
            **summary.model_dump(),
            context=self.context_read(row),
        )

    async def _fresh_authorized_destination(
        self, ctx: AuthContext, conversation_id: UUID
    ) -> Conversation:
        """Recheck the destination audience and reload mutable room state."""
        await self.participants._conversation(ctx, conversation_id)
        conversation = await conversation_repo.get_conversation_by_id(
            self.db, conversation_id, fresh=True
        )
        if conversation is None or conversation.organization_id != ctx.organization_id:
            raise NotFoundError(message="Room not found")
        return conversation

    async def _managed_context_thread(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        *,
        lock: bool,
    ) -> tuple[Conversation, Message, UUID, UUID, RoomThread]:
        """Reload and authorize one saved context thread after its advisory lock."""
        conversation, root, organization_id, user_id = await self._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        fresh = await conversation_repo.get_conversation_by_id(self.db, conversation.id, fresh=True)
        if fresh is None or fresh.organization_id != organization_id:
            raise NotFoundError(message="Room thread not found")
        if fresh.is_archived:
            raise ConflictError(
                message="Archived threads are read-only",
                details={"reason": "archived_thread"},
            )
        if not await self._can_manage(ctx, fresh, root, user_id):
            raise AuthorizationError(
                message="Only the thread starter or a room manager may change its context"
            )
        row = await room_thread_repo.get_thread(
            self.db,
            organization_id=organization_id,
            conversation_id=fresh.id,
            root_message_id=root.id,
            lock=lock,
        )
        if row is None or row.context_source_conversation_id is None:
            raise NotFoundError(message="This room thread has no saved context")
        if row.state == "archived":
            raise ConflictError(
                message="Archived threads are read-only",
                details={"reason": "archived_thread"},
            )
        return fresh, root, organization_id, user_id, row

    async def _lock_context_conversations(self, conversation_ids: set[UUID]) -> None:
        """Take every affected room lock in UUID order before reading mutable context."""
        for conversation_id in sorted(conversation_ids, key=str):
            await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)

    async def _context_source(
        self,
        *,
        destination: Conversation,
        source_conversation_id: UUID,
        actor: AuthContext,
    ) -> Conversation:
        """Load a same-tenant source and prove its current audience fits the destination."""
        if source_conversation_id == destination.id:
            source = destination
        else:
            source = await conversation_repo.get_conversation_by_id(
                self.db, source_conversation_id, fresh=True
            )
        if source is None or source.organization_id != destination.organization_id:
            raise NotFoundError(message="Thread context source not found")
        await self.context_access.assert_visible(
            destination=destination,
            source=source,
            actor=actor,
        )
        return source

    async def _ensure_context_room_writable(
        self, ctx: AuthContext, conversation: Conversation
    ) -> None:
        if conversation.project_id is None and conversation.room_visibility is None:
            raise NotFoundError(message="Room thread not found")
        if conversation.is_archived:
            raise ConflictError(
                message="Archived rooms are read-only",
                details={"reason": "archived_thread"},
            )
        if not await self.participants._can_post(ctx, conversation):
            raise AuthorizationError(message="Room posting access is required")

    async def _ensure_context_idle(
        self,
        *,
        organization_id: UUID,
        conversation_ids: set[UUID],
    ) -> None:
        if await room_thread_repo.has_context_work(
            self.db,
            organization_id=organization_id,
            conversation_ids=conversation_ids,
        ):
            raise ConflictError(
                message="Wait for room work to finish before changing thread context",
                details={"reason": "room_busy"},
            )

    async def _resolve_context_range(
        self,
        *,
        organization_id: UUID,
        source: Conversation,
        start_message_id: UUID,
        end_message_id: UUID,
        excluded_message_ids: list[UUID],
        own_context: RoomThread | None = None,
    ) -> tuple[UUID, UUID, int, int, list[UUID], list[UUID]]:
        """Normalize and snapshot an eligible range without counting hidden rows."""
        own_ids = (
            list(own_context.context_message_ids)
            if own_context is not None
            and own_context.context_moved
            and own_context.context_source_conversation_id == source.id
            else []
        )
        own_root_id = own_context.root_message_id if own_context is not None else None
        boundaries = await room_thread_repo.context_range_boundaries(
            self.db,
            organization_id=organization_id,
            source_conversation_id=source.id,
            boundary_message_ids={start_message_id, end_message_id},
            own_root_message_id=own_root_id,
            own_message_ids=own_ids,
        )
        boundary_by_id = {message.id: message for message in boundaries}
        if set(boundary_by_id) != {start_message_id, end_message_id}:
            raise ConflictError(
                message="Choose live top-level user or assistant messages in the saved room",
                details={"reason": "invalid_range"},
            )

        start = boundary_by_id[start_message_id]
        end = boundary_by_id[end_message_id]
        first, last = (start, end) if start.ordinal <= end.ordinal else (end, start)
        ordered = await room_thread_repo.context_range_candidates(
            self.db,
            organization_id=organization_id,
            source_conversation_id=source.id,
            first_ordinal=first.ordinal,
            last_ordinal=last.ordinal,
            own_root_message_id=own_root_id,
            own_message_ids=own_ids,
            limit=1001,
        )
        eligible_ids = {message.id for message in ordered}
        exclusions = set(excluded_message_ids)
        if (
            len(ordered) > 1000
            or len(exclusions) > 500
            or not {start_message_id, end_message_id}.issubset(eligible_ids)
            or not exclusions.issubset(eligible_ids)
        ):
            raise ConflictError(
                message="Select a valid range of up to 500 messages and 500 exclusions",
                details={"reason": "invalid_range"},
            )
        message_ids = [message.id for message in ordered if message.id not in exclusions]
        normalized_exclusions = [message.id for message in ordered if message.id in exclusions]
        if not message_ids or len(message_ids) > 500:
            raise ConflictError(
                message="A saved context range must contain between 1 and 500 messages",
                details={"reason": "invalid_range"},
            )
        return first.id, last.id, first.ordinal, last.ordinal, normalized_exclusions, message_ids

    async def _ensure_no_nested_replies(
        self, *, conversation_id: UUID, message_ids: list[UUID]
    ) -> None:
        if await room_thread_repo.has_nested_replies(
            self.db, conversation_id=conversation_id, message_ids=message_ids
        ):
            raise ConflictError(
                message="Return replies to selected messages before moving their context",
                details={"reason": "nested_replies"},
            )

    async def _change_context_placement(
        self,
        *,
        conversation_id: UUID,
        root_message_id: UUID,
        message_ids: list[UUID],
        old_root_message_id: UUID | None,
        new_root_message_id: UUID | None,
    ) -> None:
        """Change only the exact snapshotted rows and refuse a partial result."""
        if not message_ids:
            raise ConflictError(
                message="This thread's saved context is unavailable.",
                details={"reason": "stale_context"},
            )
        changed_ids = await room_thread_repo.change_context_placement(
            self.db,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
            message_ids=message_ids,
            old_root_message_id=old_root_message_id,
            new_root_message_id=new_root_message_id,
        )
        if changed_ids != set(message_ids):
            raise ConflictError(
                message="This thread's saved context changed. Select the context again.",
                details={"reason": "stale_context"},
            )

    @staticmethod
    def _check_context_revision(row: RoomThread, expected_revision: int) -> None:
        if row.context_revision != expected_revision:
            raise ConflictError(
                message="This thread's context changed. Refresh it before continuing.",
                details={"reason": "stale_context"},
            )

    async def create_context(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        body: RoomThreadRangeCreate,
    ) -> RoomThreadContextActionRead:
        """Create a context-only range thread with a marker and no agent dispatch."""
        organization_id, user_id = self.participants._principal(ctx)
        await self.participants._conversation(ctx, conversation_id)
        source_id = body.source_conversation_id or conversation_id
        await self._lock_context_conversations({conversation_id, source_id})
        async with self.db.begin_nested():
            destination = await self._fresh_authorized_destination(ctx, conversation_id)
            await self._ensure_context_room_writable(ctx, destination)
            source = await self._context_source(
                destination=destination,
                source_conversation_id=source_id,
                actor=ctx,
            )
            affected = {destination.id, source.id}
            await self._ensure_context_idle(
                organization_id=organization_id,
                conversation_ids=affected,
            )
            (
                first_id,
                last_id,
                first_ordinal,
                last_ordinal,
                excluded_ids,
                message_ids,
            ) = await self._resolve_context_range(
                organization_id=organization_id,
                source=source,
                start_message_id=body.start_message_id,
                end_message_id=body.end_message_id,
                excluded_message_ids=body.excluded_message_ids,
            )
            first_message = await conversation_repo.get_message_by_id(self.db, message_ids[0])
            if first_message is None:
                raise ConflictError(
                    message="This thread's saved context changed. Select the context again.",
                    details={"reason": "stale_context"},
                )
            default_title = (
                first_message.content if source.id == destination.id else "Shared context"
            )
            marker_title = " ".join((body.title or default_title).split())[:255]
            if not marker_title:
                marker_title = "Shared context"
            root = await self.conversations.add_message(
                destination.id,
                MessageCreate(role="user", content=marker_title),
                organization_id=organization_id,
                user_id=user_id,
            )
            row = await room_thread_repo.ensure_thread(
                self.db,
                organization_id=organization_id,
                conversation_id=destination.id,
                root_message_id=root.id,
            )
            row.context_source_conversation_id = source.id
            row.context_start_message_id = first_id
            row.context_end_message_id = last_id
            row.context_first_ordinal = first_ordinal
            row.context_last_ordinal = last_ordinal
            row.context_excluded_message_ids = excluded_ids
            row.context_message_ids = message_ids
            row.context_moved = False
            row.context_revision = 1
            self.db.add(row)
            await self.db.flush()
            await conversation_repo.invalidate_thread_context_history(
                self.db, conversation_ids=affected
            )
            result = await self._context_action(
                ctx, destination, root, organization_id, user_id, row
            )
        self._announce_thread_changed(destination.id, root.id)
        return result

    async def update_context(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        body: RoomThreadContextUpdate,
    ) -> RoomThreadContextActionRead:
        """Replace a range, atomically returning or moving its selected rows as needed."""
        _, _, _, _, initial = await self._managed_context_thread(
            ctx, conversation_id, root_message_id, lock=False
        )
        self._check_context_revision(initial, body.expected_context_revision)
        old_source_id = initial.context_source_conversation_id
        if old_source_id is None:
            raise ConflictError(
                message="This thread's saved context is unavailable.",
                details={"reason": "stale_context"},
            )
        target_source_id = body.source_conversation_id or old_source_id
        await self._lock_context_conversations({conversation_id, old_source_id, target_source_id})
        async with self.db.begin_nested():
            destination, root, organization_id, user_id, row = await self._managed_context_thread(
                ctx, conversation_id, root_message_id, lock=True
            )
            self._check_context_revision(row, body.expected_context_revision)
            if row.context_source_conversation_id != old_source_id:
                raise ConflictError(
                    message="This thread's context changed. Refresh it before continuing.",
                    details={"reason": "stale_context"},
                )
            target_source_id = body.source_conversation_id or old_source_id
            should_move = row.context_moved if body.move is None else body.move
            if should_move and target_source_id != destination.id:
                raise ConflictError(
                    message="Context from another room cannot be moved into this thread",
                    details={"reason": "cross_room_move"},
                )
            target_source = await self._context_source(
                destination=destination,
                source_conversation_id=target_source_id,
                actor=ctx,
            )
            affected = {destination.id, old_source_id, target_source.id}
            await self._ensure_context_idle(
                organization_id=organization_id,
                conversation_ids=affected,
            )
            if target_source_id != old_source_id and await room_thread_repo.has_context_history(
                self.db,
                organization_id=organization_id,
                conversation_id=destination.id,
                root_message_id=root.id,
            ):
                raise ConflictError(
                    message=(
                        "This thread already has replies or accepted requests. "
                        "Start a new thread to use context from another room."
                    ),
                    details={"reason": "context_source_in_use"},
                )
            (
                first_id,
                last_id,
                first_ordinal,
                last_ordinal,
                excluded_ids,
                message_ids,
            ) = await self._resolve_context_range(
                organization_id=organization_id,
                source=target_source,
                start_message_id=body.start_message_id,
                end_message_id=body.end_message_id,
                excluded_message_ids=body.excluded_message_ids,
                own_context=row,
            )
            unchanged = (
                target_source_id == old_source_id
                and first_id == row.context_start_message_id
                and last_id == row.context_end_message_id
                and first_ordinal == row.context_first_ordinal
                and last_ordinal == row.context_last_ordinal
                and excluded_ids == list(row.context_excluded_message_ids)
                and message_ids == list(row.context_message_ids)
                and should_move == row.context_moved
            )
            if unchanged:
                result = await self._context_action(
                    ctx, destination, root, organization_id, user_id, row
                )
            else:
                if row.context_moved:
                    if old_source_id != destination.id:
                        raise ConflictError(
                            message="Context from another room cannot be returned from this thread",
                            details={"reason": "cross_room_move"},
                        )
                    await self._change_context_placement(
                        conversation_id=destination.id,
                        root_message_id=root.id,
                        message_ids=list(row.context_message_ids),
                        old_root_message_id=root.id,
                        new_root_message_id=None,
                    )
                if should_move:
                    if target_source.id != destination.id:
                        raise ConflictError(
                            message="Context from another room cannot be moved into this thread",
                            details={"reason": "cross_room_move"},
                        )
                    await self._ensure_no_nested_replies(
                        conversation_id=destination.id,
                        message_ids=message_ids,
                    )
                    await self._change_context_placement(
                        conversation_id=destination.id,
                        root_message_id=root.id,
                        message_ids=message_ids,
                        old_root_message_id=None,
                        new_root_message_id=root.id,
                    )
                row.context_source_conversation_id = target_source.id
                row.context_start_message_id = first_id
                row.context_end_message_id = last_id
                row.context_first_ordinal = first_ordinal
                row.context_last_ordinal = last_ordinal
                row.context_excluded_message_ids = excluded_ids
                row.context_message_ids = message_ids
                row.context_moved = should_move
                row.context_revision += 1
                self.db.add(row)
                await self.db.flush()
                await conversation_repo.invalidate_thread_context_history(
                    self.db,
                    conversation_ids=affected,
                )
                result = await self._context_action(
                    ctx, destination, root, organization_id, user_id, row
                )
        if not unchanged:
            self._announce_thread_changed(conversation_id, root_message_id)
        return result

    async def move_context(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        expected_context_revision: int,
    ) -> RoomThreadContextActionRead:
        """Move only the exact saved IDs beneath their thread marker."""
        _, _, _, _, initial = await self._managed_context_thread(
            ctx, conversation_id, root_message_id, lock=False
        )
        self._check_context_revision(initial, expected_context_revision)
        source_id = initial.context_source_conversation_id
        if source_id is None or source_id != conversation_id:
            raise ConflictError(
                message="Context from another room cannot be moved into this thread",
                details={"reason": "cross_room_move"},
            )
        await self._lock_context_conversations({conversation_id, source_id})
        changed = False
        async with self.db.begin_nested():
            destination, root, organization_id, user_id, row = await self._managed_context_thread(
                ctx, conversation_id, root_message_id, lock=True
            )
            self._check_context_revision(row, expected_context_revision)
            if row.context_source_conversation_id != destination.id:
                raise ConflictError(
                    message="Context from another room cannot be moved into this thread",
                    details={"reason": "cross_room_move"},
                )
            if row.context_moved:
                result = await self._context_action(
                    ctx, destination, root, organization_id, user_id, row
                )
            else:
                await self._ensure_context_idle(
                    organization_id=organization_id,
                    conversation_ids={destination.id},
                )
                await self._ensure_no_nested_replies(
                    conversation_id=destination.id,
                    message_ids=list(row.context_message_ids),
                )
                await self._change_context_placement(
                    conversation_id=destination.id,
                    root_message_id=root.id,
                    message_ids=list(row.context_message_ids),
                    old_root_message_id=None,
                    new_root_message_id=root.id,
                )
                row.context_moved = True
                row.context_revision += 1
                self.db.add(row)
                await self.db.flush()
                await conversation_repo.invalidate_thread_context_history(
                    self.db, conversation_ids={destination.id}
                )
                changed = True
                result = await self._context_action(
                    ctx, destination, root, organization_id, user_id, row
                )
        if changed:
            self._announce_thread_changed(conversation_id, root_message_id)
        return result

    async def return_context(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        expected_context_revision: int,
    ) -> RoomThreadContextActionRead:
        """Return only the saved context IDs to the room's top level."""
        _, _, _, _, initial = await self._managed_context_thread(
            ctx, conversation_id, root_message_id, lock=False
        )
        self._check_context_revision(initial, expected_context_revision)
        source_id = initial.context_source_conversation_id
        if source_id is None or source_id != conversation_id:
            raise ConflictError(
                message="Context from another room cannot be returned from this thread",
                details={"reason": "cross_room_move"},
            )
        await self._lock_context_conversations({conversation_id, source_id})
        changed = False
        async with self.db.begin_nested():
            destination, root, organization_id, user_id, row = await self._managed_context_thread(
                ctx, conversation_id, root_message_id, lock=True
            )
            self._check_context_revision(row, expected_context_revision)
            if row.context_source_conversation_id != destination.id:
                raise ConflictError(
                    message="Context from another room cannot be returned from this thread",
                    details={"reason": "cross_room_move"},
                )
            if not row.context_moved:
                result = await self._context_action(
                    ctx, destination, root, organization_id, user_id, row
                )
            else:
                await self._ensure_context_idle(
                    organization_id=organization_id,
                    conversation_ids={destination.id},
                )
                await self._change_context_placement(
                    conversation_id=destination.id,
                    root_message_id=root.id,
                    message_ids=list(row.context_message_ids),
                    old_root_message_id=root.id,
                    new_root_message_id=None,
                )
                row.context_moved = False
                row.context_revision += 1
                self.db.add(row)
                await self.db.flush()
                await conversation_repo.invalidate_thread_context_history(
                    self.db, conversation_ids={destination.id}
                )
                changed = True
                result = await self._context_action(
                    ctx, destination, root, organization_id, user_id, row
                )
        if changed:
            self._announce_thread_changed(conversation_id, root_message_id)
        return result

    async def summaries_for_messages(
        self,
        conversation: Conversation,
        messages: list[Message],
        *,
        user_id: UUID,
        ctx: AuthContext | None,
        existing_thread_ids: set[UUID] | None = None,
        include_all_roots: bool = False,
    ) -> dict[UUID, RoomThreadSummary]:
        """Enrich a transcript page with thread state using one summary query."""
        roots = [message for message in messages if message.thread_root_message_id is None]
        if not roots:
            return {}
        root_ids = {message.id for message in roots}
        organization_id = conversation.organization_id
        summaries = await room_thread_repo.summaries_for_roots(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            root_message_ids=root_ids,
            user_id=user_id,
        )
        existing_threads = (
            existing_thread_ids
            if existing_thread_ids is not None
            else set(
                await conversation_repo.thread_summaries(
                    self.db, conversation_id=conversation.id, root_ids=root_ids
                )
            )
        )
        room_has_threads = (
            conversation.project_id is not None or conversation.room_visibility is not None
        )
        signed_in = ctx is not None and ctx.api_key_id is None and not ctx.is_impersonated
        can_post = False
        manager = False
        if ctx is not None and signed_in and room_has_threads and not conversation.is_archived:
            can_post = await self.conversations._may_write(
                conversation, user_id, turn=True, ctx=ctx
            )
            if conversation.project_id is not None:
                manager = await self.conversations._may_write(conversation, user_id, ctx=ctx)
                manager = manager or await self.conversations._project_allows(
                    conversation, user_id, ctx, Perm.PROJECTS_EDIT
                )
            else:
                manager = await self.conversations._may_write(conversation, user_id, ctx=ctx)

        result: dict[UUID, RoomThreadSummary] = {}
        for root in roots:
            state = summaries.get(root.id)
            if not include_all_roots and not room_has_threads and root.id not in existing_threads:
                continue
            result[root.id] = RoomThreadSummary(
                state=cast(Literal["open", "closed", "archived"], state.state) if state else "open",
                following=state.following if state else False,
                unread=state.unread if state else 0,
                can_manage=signed_in and can_post and (manager or root.author_user_id == user_id),
            )
        return result

    async def _mutate_lifecycle(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        action: str,
    ) -> RoomThreadActionRead:
        conversation, root, organization_id, user_id = await self._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation, root, organization_id, user_id = await self._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        if not await self._can_manage(ctx, conversation, root, user_id):
            raise AuthorizationError(
                message="Only the thread starter or a room manager may change it"
            )
        row = await room_thread_repo.ensure_thread(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            root_message_id=root.id,
        )
        now = datetime.now(UTC)
        changed = False
        if action == "close":
            if row.state == "archived":
                raise ConflictError(message="Unarchive this thread before closing it")
            if row.state != "closed":
                row.state = "closed"
                row.closed_by_user_id = user_id
                row.closed_at = now
                changed = True
        elif action == "reopen":
            if row.state == "archived":
                raise ConflictError(message="Unarchive this thread before reopening it")
            if row.state == "closed":
                row.state = "open"
                row.closed_by_user_id = None
                row.closed_at = None
                changed = True
        elif action == "archive":
            if row.state != "archived":
                row.state = "archived"
                row.archived_by_user_id = user_id
                row.archived_at = now
                changed = True
        elif action == "unarchive":
            if row.state == "archived":
                row.state = "closed" if row.closed_at is not None else "open"
                row.archived_by_user_id = None
                row.archived_at = None
                changed = True
        else:
            raise ValueError(f"Unknown thread action: {action}")
        self.db.add(row)
        await self.db.flush()
        if changed:
            self._announce_thread_changed(conversation.id, root.id)
        return await self._summary(ctx, conversation, root, organization_id, user_id)

    async def close(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> RoomThreadActionRead:
        return await self._mutate_lifecycle(ctx, conversation_id, root_message_id, "close")

    async def reopen(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> RoomThreadActionRead:
        return await self._mutate_lifecycle(ctx, conversation_id, root_message_id, "reopen")

    async def archive(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> RoomThreadActionRead:
        return await self._mutate_lifecycle(ctx, conversation_id, root_message_id, "archive")

    async def unarchive(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> RoomThreadActionRead:
        return await self._mutate_lifecycle(ctx, conversation_id, root_message_id, "unarchive")

    async def _set_following(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        following: bool,
    ) -> RoomThreadActionRead:
        conversation, root, organization_id, user_id = await self._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation, root, organization_id, user_id = await self._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        await room_thread_repo.ensure_thread(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            root_message_id=root.id,
        )
        # An explicit mute must survive a future reply even when this reader
        # does not follow implicitly yet. Persist the choice; the upsert tells
        # us whether it actually changed, so retries still publish nothing.
        changed = await room_thread_repo.set_following(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation.id,
            root_message_id=root.id,
            user_id=user_id,
            following=following,
        )
        if changed:
            self._announce_thread_changed(conversation.id, root.id)
        return await self._summary(ctx, conversation, root, organization_id, user_id)

    async def follow(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> RoomThreadActionRead:
        return await self._set_following(ctx, conversation_id, root_message_id, True)

    async def unfollow(
        self, ctx: AuthContext, conversation_id: UUID, root_message_id: UUID
    ) -> RoomThreadActionRead:
        return await self._set_following(ctx, conversation_id, root_message_id, False)

    async def mark_read(
        self,
        ctx: AuthContext,
        conversation_id: UUID,
        root_message_id: UUID,
        through_message_id: UUID,
    ) -> RoomThreadActionRead:
        conversation, root, organization_id, user_id = await self._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation.id)
        conversation, root, organization_id, user_id = await self._conversation_and_root(
            ctx, conversation_id, root_message_id
        )
        message = await conversation_repo.get_message_by_id(self.db, through_message_id)
        if message is not None and await room_thread_repo.is_context_message_id(
            self.db,
            conversation_id=conversation.id,
            message_id=message.id,
        ):
            raise NotFoundError(message="Thread read cursor message not found")
        if (
            message is None
            or message.role not in {"user", "assistant"}
            or message.conversation_id != conversation.id
            or (message.id != root.id and message.thread_root_message_id != root.id)
        ):
            raise NotFoundError(message="Thread read cursor message not found")
        # The root ordinal is already the implicit cursor for a reader with no
        # stored row. Reading just the root therefore has no durable state change.
        changed = False
        if message.ordinal > root.ordinal:
            await room_thread_repo.ensure_thread(
                self.db,
                organization_id=organization_id,
                conversation_id=conversation.id,
                root_message_id=root.id,
            )
            changed = await room_thread_repo.set_read_ordinal(
                self.db,
                organization_id=organization_id,
                conversation_id=conversation.id,
                root_message_id=root.id,
                user_id=user_id,
                ordinal=message.ordinal,
            )
        if changed:
            self._announce_thread_changed(conversation.id, root.id)
        return await self._summary(ctx, conversation, root, organization_id, user_id)

    async def assert_replyable(self, conversation_id: UUID, root_message_id: UUID) -> None:
        """Reject a reply to an archived thread before a worker calls a model."""
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if conversation is None or conversation.origin == "workflow":
            raise NotFoundError(message="Room thread not found")
        root = await conversation_repo.get_thread_root(
            self.db,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
        )
        if root is None:
            raise NotFoundError(message="Room thread not found")
        row = await room_thread_repo.get_thread(
            self.db,
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            root_message_id=root.id,
        )
        if row is not None and row.state == "archived":
            raise ConflictError(message="Archived threads are read-only")

    async def reply_saved(
        self,
        *,
        organization_id: UUID,
        conversation_id: UUID,
        root_message_id: UUID,
        reply_message_id: UUID,
        actor_user_id: UUID | None,
        sender: str,
        excluded_user_ids: set[UUID] | None = None,
    ) -> None:
        """Reopen a closed thread and notify its current followers once per reply."""
        # Archive and final reply persistence must serialize even before a
        # lifecycle row exists. A worker's earlier model-admission check may
        # have happened before somebody archived the thread.
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        root = await conversation_repo.get_thread_root(
            self.db,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
        )
        reply = await conversation_repo.get_message_by_id(self.db, reply_message_id)
        reply_is_context = reply is not None and await room_thread_repo.is_context_message_id(
            self.db,
            conversation_id=conversation_id,
            message_id=reply.id,
        )
        if (
            conversation is None
            or conversation.organization_id != organization_id
            or root is None
            or reply is None
            or reply_is_context
            or reply.conversation_id != conversation_id
            or reply.thread_root_message_id != root_message_id
        ):
            raise NotFoundError(message="Room thread reply not found")
        await self.assert_replyable(conversation_id, root_message_id)
        row = await room_thread_repo.get_thread(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
            lock=True,
        )
        if row is not None and row.state == "archived":
            raise ConflictError(message="Archived threads are read-only")
        if row is not None and row.context_source_conversation_id is not None:
            row.context_used = True
            self.db.add(row)
        if row is not None and row.state == "closed":
            row.state = "open"
            row.closed_by_user_id = None
            row.closed_at = None
            self.db.add(row)
        await self.db.flush()
        self._announce_thread_changed(conversation_id, root_message_id)

        excluded = set(excluded_user_ids or ())
        for mention in reply.room_mentions or []:
            if isinstance(mention, dict) and mention.get("kind") == "user" and mention.get("id"):
                try:
                    excluded.add(UUID(mention["id"]))
                except ValueError, TypeError:
                    continue
        recipient_ids = await room_thread_repo.follower_ids(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
        )
        active: list[UUID] = []
        for recipient_id in sorted(
            recipient_ids - excluded - ({actor_user_id} if actor_user_id else set())
        ):
            member = await member_repo.get_active(
                self.db,
                organization_id=organization_id,
                user_id=recipient_id,
            )
            if member is None:
                continue
            member_ctx = await self.conversations._member_ctx(organization_id, recipient_id)
            if member_ctx is None or not await self.conversations._may_read(
                conversation, recipient_id, ctx=member_ctx
            ):
                continue
            active.append(recipient_id)
        if active:
            from app.services.notifications import NotificationService

            await NotificationService(self.db).room_thread_replied(
                recipients=active,
                organization_id=organization_id,
                conversation_id=conversation_id,
                message_id=reply_message_id,
                thread_root_message_id=root_message_id,
                title=conversation.title,
                sender=sender or "Someone",
                actor_user_id=actor_user_id,
            )
