"""Thread lifecycle, read cursors and follower notifications for room chats."""

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.locks import LockScope, hold_subject
from app.db.models.conversation import Conversation, Message
from app.repositories import (
    conversation as conversation_repo,
)
from app.repositories import (
    member as member_repo,
)
from app.repositories import (
    room_thread as room_thread_repo,
)
from app.schemas.room_thread import RoomThreadActionRead, RoomThreadSummary
from app.services.conversation import ConversationService
from app.services.room_participant import RoomParticipantService


class RoomThreadService:
    """Authorize thread actions against the conversation's current audience."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)
        self.participants = RoomParticipantService(db)

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
        if (
            conversation is None
            or conversation.organization_id != organization_id
            or root is None
            or reply is None
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
