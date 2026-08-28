"""ConversationShareService - sharing conversations between users (PostgreSQL async)."""

import logging
import secrets
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.repositories import conversation_repo, conversation_share_repo, member_repo, user_repo

logger = logging.getLogger(__name__)


class ConversationShareService:
    """Business logic for conversation sharing."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _is_member(self, organization_id: UUID, user_id: UUID) -> bool:
        """Whether the user belongs to the conversation's organization.

        Plain membership, not `get_active`: the question is tenancy, and a
        deactivated member is still inside the tenant. Whether they can sign in
        is the read path's to decide, not this refusal's.
        """
        membership = await member_repo.get(
            self.db, organization_id=organization_id, user_id=user_id
        )
        return membership is not None

    async def share_conversation(
        self,
        conversation_id: UUID,
        shared_by: UUID,
        *,
        shared_with: UUID | None = None,
        shared_with_email: str | None = None,
        generate_link: bool = False,
        permission: str = "view",
    ) -> dict:
        """Share a conversation with a user or generate a public link.

        Only the conversation owner can share.
        """
        conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if not conv:
            raise NotFoundError(
                message="Conversation not found", details={"conversation_id": str(conversation_id)}
            )
        if conv.user_id != shared_by:
            raise AuthorizationError(message="Only the conversation owner can share it")

        share_token = None

        if generate_link:
            share_token = secrets.token_urlsafe(32)
            share = await conversation_share_repo.create(
                self.db,
                conversation_id=conversation_id,
                shared_by=shared_by,
                share_token=share_token,
                permission=permission,
            )
            return {"share": share, "share_url": f"/shared/{share_token}"}

        # The dialog sends an email - people know each other by email, not by
        # UUID - and the API keeps accepting an id for callers that hold one.
        #
        # A target outside the conversation's organization is refused as though it
        # did not exist: the read path refuses on the tenant anyway, so the share
        # would be unreadable (#930), and naming it a member of another org would
        # be a cross-tenant probe for which addresses hold an account elsewhere.
        if shared_with is not None:
            target_user = await user_repo.get_by_id(self.db, shared_with)
            if not target_user or not await self._is_member(conv.organization_id, target_user.id):
                raise NotFoundError(message="User not found", details={"user_id": str(shared_with)})
        elif shared_with_email is not None:
            target_user = await user_repo.get_by_email(self.db, shared_with_email)
            if not target_user or not await self._is_member(conv.organization_id, target_user.id):
                raise NotFoundError(
                    message="No user with that email", details={"email": shared_with_email}
                )
            shared_with = target_user.id
        else:
            raise NotFoundError(
                message="Must provide shared_with, shared_with_email or generate_link=true"
            )

        # After resolution, so sharing with your own email is refused too.
        if shared_with == shared_by:
            raise AlreadyExistsError(message="Cannot share a conversation with yourself")

        existing = await conversation_share_repo.get_share(self.db, conversation_id, shared_with)
        if existing:
            raise AlreadyExistsError(
                message="Conversation already shared with this user",
                details={"shared_with": str(shared_with)},
            )

        share = await conversation_share_repo.create(
            self.db,
            conversation_id=conversation_id,
            shared_by=shared_by,
            shared_with=shared_with,
            permission=permission,
        )
        return {"share": share}

    async def list_shares(self, conversation_id: UUID, user_id: UUID) -> list:
        """List all shares for a conversation. Owner only."""
        conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        if not conv:
            raise NotFoundError(message="Conversation not found")
        if conv.user_id != user_id:
            raise AuthorizationError(message="Only the conversation owner can view shares")

        return await conversation_share_repo.get_shares_for_conversation(
            self.db, conversation_id, organization_id=conv.organization_id
        )

    async def revoke_share(self, share_id: UUID, user_id: UUID) -> None:
        """Revoke a share. Owner of conversation or the shared_with user can revoke."""
        share = await conversation_share_repo.get_by_id(self.db, share_id)
        if not share:
            raise NotFoundError(message="Share not found", details={"share_id": str(share_id)})

        if share.shared_by != user_id and share.shared_with != user_id:
            raise AuthorizationError(message="Not authorized to revoke this share")

        await conversation_share_repo.delete(self.db, share_id)

    async def list_shared_with_me(
        self, user_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> tuple[list, int]:
        """List conversations shared with the current user.

        The star is stamped here too. A thread somebody was *shared* is exactly
        the kind they favourite - a shared conversation may be starred by anyone
        who can read it - so a list that answered `false` for every row was
        wrong on the surface where it matters most (#1254).
        """
        items = await conversation_share_repo.get_conversations_shared_with_user(
            self.db, user_id, skip=skip, limit=limit
        )
        total = await conversation_share_repo.count_conversations_shared_with_user(self.db, user_id)
        starred = await conversation_repo.favourite_ids(
            self.db, user_id=user_id, conversation_ids=[item.id for item in items]
        )
        for item in items:
            item.is_favourite = item.id in starred  # ty: ignore[unresolved-attribute]
        return items, total

    async def get_by_token(self, token: str) -> dict:
        """Get a shared conversation by its public token."""
        share = await conversation_share_repo.get_by_token(self.db, token)
        if not share:
            raise NotFoundError(message="Share link not found or expired")
        conv = await conversation_repo.get_conversation_by_id(
            self.db, share.conversation_id, include_messages=True
        )
        if not conv:
            raise NotFoundError(message="Conversation not found")
        return {
            "conversation": {
                "id": str(conv.id),
                "title": conv.title,
                "messages": [
                    {
                        "id": str(m.id),
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in (conv.messages or [])
                ],
            },
            "share": {
                "id": str(share.id),
                "permission": share.permission,
                "share_token": share.share_token,
            },
        }
