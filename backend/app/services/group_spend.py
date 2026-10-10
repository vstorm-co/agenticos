"""What each department spent this month, against its cap (#2072).

Read by the dashboard's department widget and the group page. A person in two
departments counts in both: each is measured against its own cap, the way the
budget guard measures it, so these figures are not a split of the bill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.repositories import agent_run_repo, group_repo
from app.schemas.group import GroupSpendList, GroupSpendRead, as_group_icon
from app.services.exporting import ExportResult, csv_document
from app.services.spend import month_start

_EXPORT_HEADER = ["member", "agent", "runs", "cost_usd"]


class GroupSpendService:
    """Department spend, for whoever may read the organization's spend - or lead the department."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def month(self, ctx: AuthContext) -> GroupSpendList:
        """Every department's month to date, costliest first, capped or not."""
        since = month_start()
        groups = await group_repo.list_for_org(self.db, ctx.organization_id)
        spent = {
            group_id: (cost, runs)
            for group_id, cost, runs in await agent_run_repo.spend_by_group(
                self.db, organization_id=ctx.organization_id, since=since
            )
        }
        items = [
            GroupSpendRead(
                group_id=group.id,
                name=group.name,
                icon=as_group_icon(group.icon),
                member_count=count,
                monthly_budget_usd=group.monthly_budget_usd,
                spent_usd=spent.get(group.id, (Decimal(0), 0))[0],
                run_count=spent.get(group.id, (Decimal(0), 0))[1],
            )
            for group, count in groups
        ]
        items.sort(key=lambda item: (-item.spent_usd, item.name))
        return GroupSpendList(since=since, items=items)

    async def export(self, ctx: AuthContext, group_id: UUID) -> ExportResult:
        """One department's month as CSV, a row per member and agent.

        `runs:view` reads every department's; a department's lead reads their own,
        since answering for the cap is the reason they lead it.
        """
        group = await group_repo.get(
            self.db, organization_id=ctx.organization_id, group_id=group_id
        )
        if group is None:
            raise NotFoundError(message="Group not found", details={"group_id": group_id})
        if not ctx.has(Perm.RUNS_VIEW) and not await self._leads(ctx, group_id):
            raise AuthorizationError(
                message="Only someone who can see the organization's spend, or the group's lead, can export it"
            )
        rows = await agent_run_repo.group_spend_rows(
            self.db, organization_id=ctx.organization_id, group_id=group_id, since=month_start()
        )
        stamp = datetime.now(UTC).strftime("%Y-%m")
        return ExportResult(
            content=csv_document(_EXPORT_HEADER, [list(row) for row in rows]),
            filename=f"{group.name}-spend-{stamp}.csv",
            row_count=len(rows),
        )

    async def _leads(self, ctx: AuthContext, group_id: UUID) -> bool:
        if ctx.user_id is None:
            return False
        member = await group_repo.get_member(self.db, group_id=group_id, user_id=ctx.user_id)
        return member is not None and member.is_lead
