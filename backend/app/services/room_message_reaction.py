"""Set and remove a signed-in person's reaction on an authorized room message."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn_after_commit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.room_message_reaction import RoomMessageReaction
from app.repositories import room_message_reaction as reaction_repo
from app.schemas.room_reaction import (
    MAX_DISTINCT_REACTIONS_PER_MESSAGE,
    RoomMessageReactionCreate,
    RoomMessageReactionsRead,
)
from app.services import chat_room
from app.services.room_submission import RoomSubmissionService, signed_in


class RoomMessageReactionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def set_reaction(
        self,
        ctx: AuthContext,
        *,
        user_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        data: RoomMessageReactionCreate,
    ) -> RoomMessageReactionsRead:
        return await self._change(
            ctx,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            emoji=data.emoji,
            ensure_on=True,
        )

    async def remove_reaction(
        self,
        ctx: AuthContext,
        *,
        user_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        data: RoomMessageReactionCreate,
    ) -> RoomMessageReactionsRead:
        return await self._change(
            ctx,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            emoji=data.emoji,
            ensure_on=False,
        )

    async def _change(
        self,
        ctx: AuthContext,
        *,
        user_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        emoji: str,
        ensure_on: bool,
    ) -> RoomMessageReactionsRead:
        signed_in(ctx)
        if user_id != ctx.subject_id:
            raise AuthorizationError(message="React as yourself")

        rooms = RoomSubmissionService(self.db)
        await rooms.room(ctx, conversation_id, for_write=True)
        # The distinct emoji ceiling is a check-then-write. Serialize reaction
        # changes with room turns, then recheck the ACL after waiting for access
        # or archive state to have changed.
        await hold_subject(self.db, LockScope.CONVERSATION_TURN, conversation_id)
        await rooms.room(ctx, conversation_id, for_write=True)

        message = await reaction_repo.get_room_message(
            self.db,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if message is None:
            raise NotFoundError(message="Room message not found")

        changed = False
        if ensure_on:
            existing = await reaction_repo.get_for_user(
                self.db,
                organization_id=ctx.organization_id,
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                emoji=emoji,
            )
            if existing is None:
                if not await reaction_repo.has_emoji(
                    self.db,
                    organization_id=ctx.organization_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    emoji=emoji,
                ):
                    count = await reaction_repo.distinct_emoji_count(
                        self.db,
                        organization_id=ctx.organization_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                    )
                    if count >= MAX_DISTINCT_REACTIONS_PER_MESSAGE:
                        raise BadRequestError(
                            message="This message already has the maximum number of reactions",
                            details={"maximum": MAX_DISTINCT_REACTIONS_PER_MESSAGE},
                        )
                await reaction_repo.add(
                    self.db,
                    RoomMessageReaction(
                        organization_id=ctx.organization_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        user_id=user_id,
                        emoji=emoji,
                    ),
                )
                changed = True
        else:
            changed = await reaction_repo.remove(
                self.db,
                organization_id=ctx.organization_id,
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=user_id,
                emoji=emoji,
            )

        if changed:
            spawn_after_commit(
                self.db,
                chat_room.room_reaction(str(conversation_id), message_id),
                name="room-message-reaction-changed",
            )
        aggregates = await reaction_repo.list_aggregates(
            self.db,
            organization_id=ctx.organization_id,
            conversation_id=conversation_id,
            message_ids=[message_id],
            user_id=user_id,
        )
        return RoomMessageReactionsRead(reactions=aggregates.get(message_id, []))
