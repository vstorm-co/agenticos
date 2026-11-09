"""ConversationShareService - sharing conversations between users (PostgreSQL async)."""

import logging
import secrets
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.drafts._spec import (
    DRAFTED,
    parse_draft_card,
)
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.conversation_share import ConversationShare
from app.repositories import conversation_repo, conversation_share_repo, member_repo, user_repo
from app.schemas.conversation_share import (
    SharedConversationBody,
    SharedConversationRead,
    SharedConversationShare,
    SharedDraft,
    SharedMessageRead,
    SharedVisual,
)
from app.services import rate_limit
from app.services import visual as visuals
from app.services.conversation import ConversationService
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)


SHARED_MAX_DRAFTS = 50
"""How many drafts a thread shared by link shows - the newest ones."""

SHARED_MAX_DRAFT_CHARS = 500_000
"""How much draft text one view of a shared thread carries."""


def _in_turn_order(message: Message) -> list[ToolCall]:
    """A message's tool calls in the order its turn made them.

    The relationship orders by start time, and a turn's calls are stored with the
    same one, so ties come back in any order. The turn's parts keep the real
    sequence: calls they name come first, in that order, then any they do not.
    """
    calls = list(message.tool_calls or [])
    position = {
        part["tool_call_id"]: index
        for index, part in reversed(list(enumerate(message.parts or [])))
        if part.get("type") == "tool" and part.get("tool_call_id")
    }
    return sorted(calls, key=lambda call: position.get(call.tool_call_id, len(position)))


def shared_drafts(conversation: Conversation) -> dict[UUID, list[SharedDraft]]:
    """Each message's drafts, rebuilt from the calls that wrote them, for a thread shared by link.

    A shared thread shows the text of its turns and never their tool calls, so a
    draft is rebuilt here from the arguments of its completed call. A refused
    call, or one whose arguments no longer parse, is left out.

    Bounded, because anybody holding the link can ask for it as often as they
    like: the newest :data:`SHARED_MAX_DRAFTS`, and no more than
    :data:`SHARED_MAX_DRAFT_CHARS` of field text between them. A turn past either
    keeps its text and shows no card.
    """
    placed = [
        (message.id, call)
        for message in conversation.messages or []
        for call in _in_turn_order(message)
        if call.status == "completed"
        and (call.result or "").startswith(DRAFTED)
        and call.presentation_kind == "draft"
    ]
    shared: dict[UUID, list[SharedDraft]] = {}
    budget = SHARED_MAX_DRAFT_CHARS
    for message_id, call in reversed(placed[-SHARED_MAX_DRAFTS:]):
        card = parse_draft_card(call.args)
        if card is None:
            continue
        size = sum(len(f.text) for v in card.versions for f in v.fields)
        if size > budget:
            continue
        budget -= size
        shared.setdefault(message_id, []).insert(
            0,
            SharedDraft.model_validate(
                {"id": call.tool_call_id, **card.model_dump()},
            ),
        )
    return shared


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
        # Who reads a project's chat is the project's to say. A share - a public
        # link above all - would outlive its starter's place in the project and
        # go on showing teammates' later turns to whoever holds it.
        if conv.project_id is not None:
            raise BadRequestError(
                message="A project's chat is shared through its project - share the project",
                details={"conversation_id": str(conversation_id)},
            )

        if permission == "edit" and not await conversation_share_repo.lock_private_publication(
            self.db, conversation_id, conv.organization_id
        ):
            raise NotFoundError(message="Conversation not found")
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

        await rate_limit.enforce_conversation_share(
            organization_id=conv.organization_id, actor_id=shared_by, recipient_id=shared_with
        )
        share = await conversation_share_repo.create(
            self.db,
            conversation_id=conversation_id,
            shared_by=shared_by,
            shared_with=shared_with,
            permission=permission,
        )
        # A share nobody hears of is one the recipient finds only by its link.
        sharer = await user_repo.get_by_id(self.db, shared_by)
        await NotificationService(self.db).conversation_shared(
            recipient=shared_with,
            organization_id=conv.organization_id,
            conversation_id=conversation_id,
            title=conv.title,
            sharer=(sharer.full_name or sharer.email) if sharer is not None else "Someone",
            actor_user_id=shared_by,
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

    async def change_permission(
        self,
        conversation_id: UUID,
        share_id: UUID,
        user_id: UUID,
        *,
        permission: Literal["view", "edit"],
        organization_id: UUID,
    ) -> ConversationShare:
        """Change what a share with a person allows. Owner only.

        A person's own share is not theirs to widen, so only the conversation's
        owner may change it. A link stays view-only: a token reaches only the
        read route, so an `edit` link would promise what nothing grants.

        Raises:
            NotFoundError: If the share is not one of this conversation's.
            AuthorizationError: If the caller does not own the conversation.
            BadRequestError: If the share is a link.
        """
        conv = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        share = await conversation_share_repo.get_by_id(self.db, share_id)
        if (
            conv is None
            or conv.organization_id != organization_id
            or share is None
            or share.conversation_id != conversation_id
        ):
            raise NotFoundError(
                message="Share not found",
                details={"conversation_id": conversation_id, "share_id": share_id},
            )
        if conv.user_id != user_id:
            raise AuthorizationError(message="Only the conversation owner can change a share")
        if share.share_token is not None:
            raise BadRequestError(
                message="A share link is view-only", details={"share_id": share_id}
            )
        if conv.project_id is not None:
            raise BadRequestError(
                message="A project's chat is shared through its project - share the project",
                details={"conversation_id": conversation_id},
            )
        if permission == "edit" and not await conversation_share_repo.lock_private_publication(
            self.db, conversation_id, organization_id
        ):
            raise NotFoundError(
                message="Conversation not found", details={"conversation_id": conversation_id}
            )
        return await conversation_share_repo.set_permission(
            self.db, share=share, permission=permission
        )

    async def revoke_share(self, share_id: UUID, user_id: UUID) -> None:
        """Revoke a share. Owner of conversation or the shared_with user can revoke."""
        share = await conversation_share_repo.get_by_id(self.db, share_id)
        if not share:
            raise NotFoundError(message="Share not found", details={"share_id": str(share_id)})

        if share.shared_by != user_id and share.shared_with != user_id:
            raise AuthorizationError(message="Not authorized to revoke this share")

        await conversation_share_repo.delete(self.db, share_id)

    async def leave(self, conversation_id: UUID, user_id: UUID, *, organization_id: UUID) -> None:
        """Take a conversation somebody shared with this reader out of their chats.

        The reader's own share ends; the conversation, and everybody else's
        access to it, stays. Their star on it goes too, so it does not come back
        to their favourites if it is shared with them again. Only in the active
        organization, as the list it was picked from is.

        Raises:
            NotFoundError: If the conversation was not shared with this reader
                in this organization.
        """
        conversation = await conversation_repo.get_conversation_by_id(self.db, conversation_id)
        share = await conversation_share_repo.get_share(self.db, conversation_id, user_id)
        if share is None or conversation is None or conversation.organization_id != organization_id:
            raise NotFoundError(
                message="Conversation not shared with you",
                details={"conversation_id": conversation_id},
            )
        await conversation_share_repo.delete(self.db, share.id)
        await conversation_repo.set_favourite(
            self.db, user_id=user_id, conversation_id=conversation_id, favourite=False
        )

    async def list_shared_with_me(
        self,
        user_id: UUID,
        *,
        organization_id: UUID,
        skip: int = 0,
        limit: int = 50,
        include_archived: bool = True,
    ) -> tuple[list, int]:
        """List the conversations shared with the current user in one organization.

        One organization, the active one: a share from another would open under
        the wrong organization and fail, and its title has no business on this
        one's screen.

        Each row carries what the reader's own list does - who it is with,
        whether a run is at work in it, whether it holds an answer they have
        not seen - and what the share lets them do. The star is stamped here too. A thread somebody was *shared* is exactly
        the kind they favourite - a shared conversation may be starred by anyone
        who can read it - so a list that answered `false` for every row was
        wrong on the surface where it matters most (#1254).
        """
        items = await conversation_share_repo.get_conversations_shared_with_user(
            self.db,
            user_id,
            organization_id=organization_id,
            skip=skip,
            limit=limit,
            include_archived=include_archived,
        )
        total = await conversation_share_repo.count_conversations_shared_with_user(
            self.db, user_id, organization_id=organization_id, include_archived=include_archived
        )
        starred = await conversation_repo.favourite_ids(
            self.db, user_id=user_id, conversation_ids=[item.id for item in items]
        )
        permissions = await conversation_share_repo.share_permissions(
            self.db, user_id=user_id, conversation_ids=[item.id for item in items]
        )
        await ConversationService(self.db).attach_listing_state(items, user_id=user_id)
        for item in items:
            item.is_favourite = item.id in starred  # ty: ignore[unresolved-attribute]
            item.share_permission = permissions.get(item.id)  # ty: ignore[unresolved-attribute]
        return items, total

    async def get_by_token(self, token: str) -> SharedConversationRead:
        """Get a shared conversation by its public token."""
        share = await conversation_share_repo.get_by_token(self.db, token)
        if not share:
            raise NotFoundError(message="Share link not found or expired")
        conv = await conversation_repo.get_conversation_by_id(
            self.db, share.conversation_id, include_messages=True
        )
        # A link made before its chat was in a project, or before that was
        # refused, opens nothing: the project decides who reads it.
        if not conv or conv.project_id is not None:
            raise NotFoundError(message="Conversation not found")
        drawn = await visuals.shared_visuals(conv)
        drafted = shared_drafts(conv)
        return SharedConversationRead(
            conversation=SharedConversationBody(
                id=conv.id,
                title=conv.title,
                messages=[
                    SharedMessageRead(
                        id=m.id,
                        role=m.role,
                        content=m.content,
                        created_at=m.created_at,
                        visuals=[SharedVisual.model_validate(v) for v in drawn.get(m.id, [])],
                        drafts=drafted.get(m.id, []),
                    )
                    for m in (conv.messages or [])
                ],
            ),
            share=SharedConversationShare.model_validate(
                {"id": share.id, "permission": share.permission}
            ),
        )
