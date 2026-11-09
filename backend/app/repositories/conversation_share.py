"""ConversationShare repository (PostgreSQL async)."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import ColumnElement, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.models.conversation import Conversation
from app.db.models.conversation_share import ConversationShare
from app.db.models.organization import OrganizationMember
from app.repositories.conversation import LISTED_COLUMNS, favourited_by


async def get_by_id(db: AsyncSession, share_id: UUID) -> ConversationShare | None:
    """Get a share by ID."""
    return await db.get(ConversationShare, share_id)


async def get_share(
    db: AsyncSession, conversation_id: UUID, shared_with: UUID
) -> ConversationShare | None:
    """Get a share by conversation + user composite key."""
    result = await db.execute(
        select(ConversationShare).where(
            ConversationShare.conversation_id == conversation_id,
            ConversationShare.shared_with == shared_with,
        )
    )
    return result.scalar_one_or_none()


async def get_by_token(db: AsyncSession, token: str) -> ConversationShare | None:
    """Get a share by its public token."""
    result = await db.execute(
        select(ConversationShare).where(ConversationShare.share_token == token)
    )
    return result.scalar_one_or_none()


async def get_shares_for_conversation(
    db: AsyncSession, conversation_id: UUID, *, organization_id: UUID
) -> list[ConversationShare]:
    """List a conversation's shares, dropping any written to a non-member.

    A share to somebody outside `organization_id` is unreadable - the read path
    refuses on the tenant before it ever consults the share (#930) - so listing
    it would show access nobody has. A public-link share carries no `shared_with`
    and is kept.
    """
    result = await db.execute(
        select(ConversationShare)
        .where(
            ConversationShare.conversation_id == conversation_id,
            or_(
                ConversationShare.shared_with.is_(None),
                ConversationShare.shared_with.in_(
                    select(OrganizationMember.user_id).where(
                        OrganizationMember.organization_id == organization_id
                    )
                ),
            ),
        )
        .order_by(ConversationShare.created_at.desc())
    )
    return list(result.scalars().all())


def _shared_with_member(
    user_id: UUID, *, include_archived: bool = True
) -> tuple[ColumnElement[bool], ...]:
    """The recipient holds the share *and* belongs to the conversation's org.

    The read path refuses a share whose conversation is in an organization the
    recipient does not belong to (#930), so listing or counting it here shows a
    conversation - its title, its owner, its organization - that opening only
    denies. The same tenant condition the owner's listing applies, from the
    recipient's side. Requires the query to join `Conversation`.
    """
    return (
        ConversationShare.shared_with == user_id,
        or_(literal(include_archived), Conversation.is_archived.is_(False)),
        # A project's access supersedes legacy individual shares, as on token reads.
        Conversation.project_id.is_(None),
        Conversation.organization_id.in_(
            select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user_id)
        ),
    )


def _in_organization(organization_id: UUID | None) -> tuple[ColumnElement[bool], ...]:
    """Narrow a shared-with-me query to one organization, when one is named."""
    return () if organization_id is None else (Conversation.organization_id == organization_id,)


async def get_conversations_shared_with_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    organization_id: UUID | None = None,
    skip: int = 0,
    limit: int = 50,
    include_archived: bool = True,
) -> list[Conversation]:
    """Get conversations shared with a specific user, within their own tenants.

    `organization_id` narrows it to one of them: the console lists the active
    organization's, and a share from another one would open under the wrong
    organization and fail.
    """
    result = await db.execute(
        select(Conversation)
        .options(load_only(*LISTED_COLUMNS, raiseload=True))
        .join(ConversationShare, ConversationShare.conversation_id == Conversation.id)
        .where(
            *_shared_with_member(user_id, include_archived=include_archived),
            *_in_organization(organization_id),
        )
        .order_by(
            favourited_by(user_id).desc(),
            func.coalesce(Conversation.updated_at, Conversation.created_at).desc(),
            Conversation.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def share_permissions(
    db: AsyncSession, *, user_id: UUID, conversation_ids: Collection[UUID]
) -> dict[UUID, str]:
    """What each of these conversations' shares with `user_id` allows, by conversation."""
    if not conversation_ids:
        return {}
    result = await db.execute(
        select(ConversationShare.conversation_id, ConversationShare.permission).where(
            ConversationShare.shared_with == user_id,
            ConversationShare.conversation_id.in_(list(conversation_ids)),
        )
    )
    return dict(result.tuples().all())


async def count_conversations_shared_with_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    organization_id: UUID | None = None,
    include_archived: bool = True,
) -> int:
    """Count conversations shared with a specific user, within their own tenants."""
    result = await db.scalar(
        select(func.count())
        .select_from(ConversationShare)
        .join(Conversation, ConversationShare.conversation_id == Conversation.id)
        .where(
            *_shared_with_member(user_id, include_archived=include_archived),
            *_in_organization(organization_id),
        )
    )
    return result or 0


async def user_has_access(
    db: AsyncSession, conversation_id: UUID, user_id: UUID
) -> ConversationShare | None:
    """Check if user has any share access to a conversation."""
    return await get_share(db, conversation_id, user_id)


async def create(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    shared_by: UUID,
    shared_with: UUID | None = None,
    share_token: str | None = None,
    permission: str = "view",
) -> ConversationShare:
    """Create a new conversation share."""
    share = ConversationShare(
        conversation_id=conversation_id,
        shared_by=shared_by,
        shared_with=shared_with,
        share_token=share_token,
        permission=permission,
    )
    db.add(share)
    await db.flush()
    await db.refresh(share)
    return share


async def update(
    db: AsyncSession,
    *,
    db_share: ConversationShare,
    update_data: dict,
) -> ConversationShare:
    """Update a conversation share."""
    for field, value in update_data.items():
        setattr(db_share, field, value)
    db.add(db_share)
    await db.flush()
    await db.refresh(db_share)
    return db_share


async def set_permission(
    db: AsyncSession, *, share: ConversationShare, permission: str
) -> ConversationShare:
    """Change what one share allows."""
    share.permission = permission
    await db.flush()
    await db.refresh(share)
    return share


async def delete(db: AsyncSession, share_id: UUID) -> bool:
    """Delete a share by ID."""
    share = await get_by_id(db, share_id)
    if not share:
        return False
    await db.delete(share)
    await db.flush()
    return True


async def lock_private_publication(
    db: AsyncSession, conversation_id: UUID, organization_id: UUID
) -> bool:
    """Fence coding-result publication against making its workspace editable."""
    return (
        await db.scalar(
            select(Conversation.id)
            .where(
                Conversation.id == conversation_id, Conversation.organization_id == organization_id
            )
            .with_for_update()
        )
        is not None
    )
