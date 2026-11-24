"""Personal appearance, addressed only through the authenticated person.

An organization administrator cannot name a colleague here. A platform agent
needs a live, unshared private conversation owned by its credential's subject;
a background run, project room or channel cannot guess which member meant "me".
MCP OAuth callers are bound to the account that authorized them. Writes retain
the platform tool's normal approval gate.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.user import User
from app.repositories import conversation_repo, conversation_share_repo, user_repo
from app.schemas.user_appearance import UserAppearance


class UserAppearanceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _account(self, ctx: AuthContext, *, for_write: bool = False) -> User:
        if (
            ctx.user_id is None
            or ctx.subject_is_publisher_fallback
            or ctx.fired_as_creator is not None
            or ctx.routine_id is not None
            or ctx.is_workflow
            or ctx.channel_identity_id is not None
            or ctx.is_impersonated
            or current_impersonator() is not None
            or (ctx.key_internal and ctx.source_conversation_id is None)
        ):
            raise AuthorizationError(
                message="Appearance belongs to the person asking in their own session or private chat"
            )
        if ctx.source_conversation_id is not None:
            conversation = await conversation_repo.get_conversation_by_id(
                self.db, ctx.source_conversation_id, fresh=True
            )
            if (
                conversation is None
                or conversation.user_id != ctx.user_id
                or conversation.organization_id != ctx.organization_id
                or conversation.project_id is not None
                or conversation.workflow_id is not None
                or conversation.origin is not None
            ):
                raise AuthorizationError(message="Change appearance from your own private chat")
            if await conversation_repo.channel_thread_ids(self.db, [conversation.id]):
                raise AuthorizationError(message="Change appearance from your own private chat")
            if await conversation_share_repo.get_shares_for_conversation(
                self.db, conversation.id, organization_id=ctx.organization_id
            ):
                raise AuthorizationError(message="Change appearance from your own private chat")
        account = (
            await user_repo.get_by_id_for_update(self.db, ctx.user_id, fresh=True)
            if for_write
            else await user_repo.get_by_id(self.db, ctx.user_id)
        )
        if account is None:
            raise NotFoundError(message="User not found")
        return account

    async def get(self, ctx: AuthContext) -> UserAppearance:
        account = await self._account(ctx)
        return UserAppearance.model_validate(account.appearance or {})

    async def update(self, ctx: AuthContext, data: UserAppearance) -> UserAppearance:
        """Merge only supplied tokens while holding the person's row lock."""
        account = await self._account(ctx, for_write=True)
        current = UserAppearance.model_validate(account.appearance or {})
        changes = data.model_dump(exclude_unset=True)
        updated = UserAppearance.model_validate({**current.model_dump(), **changes})
        await user_repo.update(
            self.db, db_user=account, update_data={"appearance": updated.model_dump()}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="user.appearance_updated",
            target_type="user",
            target_id=str(ctx.subject_id),
            details={"fields": sorted(changes)},
        )
        return updated

    async def reset(self, ctx: AuthContext) -> UserAppearance:
        account = await self._account(ctx, for_write=True)
        await user_repo.update(self.db, db_user=account, update_data={"appearance": None})
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="user.appearance_reset",
            target_type="user",
            target_id=str(ctx.subject_id),
        )
        return UserAppearance()
