"""How well agents answer each department's people (#2101).

The other half of a department's month: its spend says what it cost, this says
whether the answers were any good - the question a department lead asks next.
Read by the group page and the dashboard's department quality card.
"""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.repositories import agent_run_repo, group_repo, message_rating_repo
from app.schemas.group import (
    GroupAgentUse,
    GroupDownRatedAnswer,
    GroupQualityDetail,
    GroupQualityList,
    GroupQualityRead,
    as_group_icon,
)
from app.services.group_spend import leads_group
from app.services.stats import resolve_window

# As many as the group page's card shows without scrolling.
TOP_AGENTS = 5
DOWN_RATED = 5


class GroupQualityService:
    """Department answer quality, for whoever may view runs - or leads the department."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def overview(
        self, ctx: AuthContext, *, from_date: date | None, to_date: date | None
    ) -> GroupQualityList:
        """Every department whose people rated an answer, least helpful share first.

        Gated on `runs:view` at the route: comparing departments is the
        organization's view, not one lead's.
        """
        window = resolve_window(from_date, to_date)
        rated = {
            group_id: (likes, dislikes)
            for group_id, likes, dislikes in await message_rating_repo.ratings_by_group(
                self.db, organization_id=ctx.organization_id, start=window.start, end=window.end
            )
        }
        items = [
            GroupQualityRead(
                group_id=group.id,
                name=group.name,
                icon=as_group_icon(group.icon),
                likes=rated[group.id][0],
                dislikes=rated[group.id][1],
            )
            for group, _ in await group_repo.list_for_org(self.db, ctx.organization_id)
            if group.id in rated
        ]
        items.sort(key=lambda item: (item.likes / (item.likes + item.dislikes), item.name))
        return GroupQualityList(from_date=window.from_date, to_date=window.to_date, items=items)

    async def detail(
        self,
        ctx: AuthContext,
        group_id: UUID,
        *,
        from_date: date | None,
        to_date: date | None,
    ) -> GroupQualityDetail:
        """One department's split, the agents its people ran most and its worst-rated answers.

        `runs:view` reads every department's; a department's lead reads their own.
        A member of another department - or an ordinary member of this one -
        reads none of it: the comments are other people's words about answers
        they were given.

        Raises:
            NotFoundError: No such department in this organization.
            AuthorizationError: The caller neither views runs nor leads it.
        """
        group = await group_repo.get(
            self.db, organization_id=ctx.organization_id, group_id=group_id
        )
        if group is None:
            raise NotFoundError(message="Group not found", details={"group_id": group_id})
        if not ctx.has(Perm.RUNS_VIEW) and not await leads_group(self.db, ctx, group_id):
            raise AuthorizationError(
                message="Only someone who can view runs, or the group's lead, can see its answer quality"
            )
        window = resolve_window(from_date, to_date)
        org_id, start, end = ctx.organization_id, window.start, window.end
        rated = await message_rating_repo.ratings_by_group(
            self.db, organization_id=org_id, start=start, end=end, group_id=group_id
        )
        likes, dislikes = (rated[0][1], rated[0][2]) if rated else (0, 0)
        top = await agent_run_repo.group_top_agents(
            self.db,
            organization_id=org_id,
            group_id=group_id,
            start=start,
            end=end,
            limit=TOP_AGENTS,
        )
        worst = await message_rating_repo.group_down_rated(
            self.db,
            organization_id=org_id,
            group_id=group_id,
            start=start,
            end=end,
            limit=DOWN_RATED,
        )
        return GroupQualityDetail(
            group_id=group_id,
            from_date=window.from_date,
            to_date=window.to_date,
            likes=likes,
            dislikes=dislikes,
            top_agents=[
                GroupAgentUse(agent_id=agent_id, name=name, run_count=runs)
                for agent_id, name, runs in top
            ],
            down_rated=[
                GroupDownRatedAnswer(
                    rated_at=rated_at,
                    comment=comment,
                    run_id=run_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                )
                for rated_at, comment, run_id, agent_id, agent_name in worst
            ],
        )
