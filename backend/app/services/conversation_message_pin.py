"""Pin messages for the current reader without copying transcript content."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.conversation import Message
from app.db.models.conversation_message_pin import ConversationMessagePin
from app.repositories import conversation as conversation_repo
from app.repositories import conversation_message_pin as pin_repo
from app.schemas.conversation_message_pin import (
    ConversationMessagePinList,
    ConversationMessagePinRead,
)
from app.services.conversation import ConversationService, _excerpt, _said


class ConversationMessagePinService:
    """Reader-scoped message pins, authorized as a conversation read."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.conversations = ConversationService(db)

    async def list_message_pins(
        self,
        conversation_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
        skip: int,
        limit: int,
        ctx: AuthContext,
    ) -> ConversationMessagePinList:
        """List the caller's pins after the ordinary conversation read check."""
        conversation = await self.conversations.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            include_favourite=False,
            ctx=ctx,
        )
        rows, total = await pin_repo.list_message_pins(
            self.db,
            user_id=user_id,
            conversation_id=conversation.id,
            skip=skip,
            limit=limit,
        )
        return ConversationMessagePinList(
            items=[self._read(pin, message) for pin, message in rows],
            total=total,
        )

    async def pin_message(
        self,
        conversation_id: UUID,
        message_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
        ctx: AuthContext,
    ) -> ConversationMessagePinRead:
        """Pin one message for the caller; retries leave one row and one result."""
        message = await self._readable_message(
            conversation_id,
            message_id,
            organization_id=organization_id,
            user_id=user_id,
            ctx=ctx,
        )
        await pin_repo.set_message_pin(
            self.db,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            pinned=True,
        )
        pin = await pin_repo.get_message_pin(
            self.db,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        if pin is None:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": message_id},
            )
        return self._read(pin, message)

    async def unpin_message(
        self,
        conversation_id: UUID,
        message_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
        ctx: AuthContext,
    ) -> None:
        """Remove one pin idempotently after the same read and message checks."""
        await self._readable_message(
            conversation_id,
            message_id,
            organization_id=organization_id,
            user_id=user_id,
            ctx=ctx,
        )
        await pin_repo.set_message_pin(
            self.db,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            pinned=False,
        )

    async def _readable_message(
        self,
        conversation_id: UUID,
        message_id: UUID,
        *,
        organization_id: UUID,
        user_id: UUID,
        ctx: AuthContext,
    ) -> Message:
        """Authorize the thread and refuse an id belonging to another thread."""
        await self.conversations.get_conversation(
            conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            include_favourite=False,
            ctx=ctx,
        )
        message = await conversation_repo.get_message_by_id(self.db, message_id)
        if message is None or message.conversation_id != conversation_id:
            raise NotFoundError(
                message="Message not found",
                details={"message_id": message_id, "conversation_id": conversation_id},
            )
        return message

    @staticmethod
    def _read(pin: ConversationMessagePin, message: Message) -> ConversationMessagePinRead:
        """Project the current message, redacting content refused by a guardrail."""
        return ConversationMessagePinRead(
            message_id=message.id,
            thread_root_message_id=message.thread_root_message_id,
            role=message.role,
            message_created_at=message.created_at,
            pinned_at=pin.created_at,
            preview=_excerpt(_said(message)),
        )
