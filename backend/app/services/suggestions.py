"""A person's suggestions: reading them, and deciding (#2301).

Accepting does what a person can do without the console's help: a profile
update is written to their account here, and a role pack is queued to install
in the background. A routine or an agent needs the person's own last look - the
routine dialog opens pre-filled, the Architect is asked - so for those accepting
only records the decision, and the console does the rest.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.suggestion import Suggestion, SuggestionKind, SuggestionStatus
from app.db.models.user import User
from app.db.updates import writable
from app.repositories import member_repo, suggestion_repo, user_repo
from app.schemas.user import UserUpdate
from app.services.proactive import ProactiveService

# How far back Settings shows the proposals a person already answered.
HISTORY_LIMIT = 100


class SuggestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _person(ctx: AuthContext) -> UUID:
        if ctx.user_id is None:
            raise AuthenticationError(message="Suggestions are made to a signed-in person")
        return ctx.user_id

    async def list_mine(self, ctx: AuthContext, *, decided: bool = False) -> list[Suggestion]:
        """The person's open proposals - or, with `decided`, every one, answered or not."""
        if decided:
            return await suggestion_repo.list_all(
                self.db,
                organization_id=ctx.organization_id,
                user_id=self._person(ctx),
                limit=HISTORY_LIMIT,
            )
        return await suggestion_repo.list_open(
            self.db, organization_id=ctx.organization_id, user_id=self._person(ctx)
        )

    async def starters(self, ctx: AuthContext) -> list[str]:
        """The first messages written for the person in this organization, or none yet."""
        member = await member_repo.get(
            self.db, organization_id=ctx.organization_id, user_id=self._person(ctx)
        )
        return list(member.personal_starters or []) if member is not None else []

    async def restore(self, ctx: AuthContext, suggestion_id: UUID) -> Suggestion:
        """Bring back one the person dismissed, to answer again.

        Only a dismissed one: an accepted proposal has been acted on - a profile
        saved, a pack installed - and offering it again would do it twice.
        """
        suggestion = await suggestion_repo.get_own(
            self.db,
            suggestion_id,
            organization_id=ctx.organization_id,
            user_id=self._person(ctx),
        )
        if suggestion is None or suggestion.status != SuggestionStatus.DISMISSED.value:
            raise NotFoundError(
                message="No such dismissed suggestion", details={"suggestion_id": suggestion_id}
            )
        return await suggestion_repo.reopen(self.db, suggestion=suggestion)

    async def _own_open(self, ctx: AuthContext, suggestion_id: UUID) -> Suggestion:
        suggestion = await suggestion_repo.get_own(
            self.db,
            suggestion_id,
            organization_id=ctx.organization_id,
            user_id=self._person(ctx),
        )
        if suggestion is None or suggestion.status != SuggestionStatus.OPEN.value:
            raise NotFoundError(
                message="No such suggestion is waiting", details={"suggestion_id": suggestion_id}
            )
        return suggestion

    async def dismiss(self, ctx: AuthContext, suggestion_id: UUID) -> Suggestion:
        """Decline it - and, kept as dismissed, it is not proposed again."""
        suggestion = await self._own_open(ctx, suggestion_id)
        return await suggestion_repo.decide(
            self.db, suggestion=suggestion, status=SuggestionStatus.DISMISSED
        )

    async def accept(self, ctx: AuthContext, suggestion_id: UUID) -> Suggestion:
        """Take it: write a profile update, queue a role pack, or record the decision.

        Raises:
            NotFoundError: If it is not this person's, or no longer waiting.
            ValidationError: If a profile update it carries no longer validates -
                it is checked exactly as the profile form's own save is.
        """
        suggestion = await self._own_open(ctx, suggestion_id)
        person = self._person(ctx)
        if suggestion.kind == SuggestionKind.PROFILE.value:
            await self._apply_profile(person, UserUpdate.model_validate(suggestion.payload))
        elif suggestion.kind == SuggestionKind.ROLE_PACK.value:
            await ProactiveService(self.db).queue_role_pack(
                ctx.organization_id, person, str(suggestion.payload.get("pack", ""))
            )
        return await suggestion_repo.decide(
            self.db, suggestion=suggestion, status=SuggestionStatus.ACCEPTED
        )

    async def _apply_profile(self, user_id: UUID, update: UserUpdate) -> None:
        user = await user_repo.get_by_id(self.db, user_id)
        if user is None:
            raise NotFoundError(message="User not found", details={"user_id": user_id})
        fields = {"job_title", "about", "working_hours"}
        changes = {
            name: value for name, value in writable(update, over=User).items() if name in fields
        }
        await user_repo.update(self.db, db_user=user, update_data=changes)
