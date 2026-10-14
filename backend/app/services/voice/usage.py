"""Call minutes for the dashboard figure and the organization's Voice card (#54).

Read from `voice_calls`, the same rows the monthly limit counts, so the figure
and the refusal at the limit never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.permissions import AuthContext
from app.repositories import organization as organization_repo
from app.repositories import voice_call_repo
from app.services.spend import month_start


@dataclass(frozen=True)
class AgentMinutes:
    """One agent's calls in the window; no id and no name for agents since deleted."""

    agent_id: UUID | None
    agent_name: str | None
    seconds: int
    calls: int


@dataclass(frozen=True)
class VoiceUsage:
    """A window's call seconds by agent, and this month's against the limit."""

    start: datetime
    end: datetime
    seconds: int
    calls: int
    by_agent: list[AgentMinutes]
    month_seconds: int
    monthly_minutes: int | None


def _aware(moment: datetime) -> datetime:
    """A timestamp without a zone is read as UTC, the zone every stored time is in."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


class VoiceUsageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def usage(self, ctx: AuthContext, *, start: datetime, end: datetime) -> VoiceUsage:
        """Calls started in `[start, end)` in the caller's organization, by agent.

        Raises:
            ValidationError: `end` is not after `start`.
        """
        start, end = _aware(start), _aware(end)
        if end <= start:
            raise ValidationError(
                message="The window must end after it starts",
                details={"start": start, "end": end},
            )
        rows = await voice_call_repo.usage_by_agent(
            self.db, organization_id=ctx.organization_id, start=start, end=end
        )
        by_agent = [
            AgentMinutes(agent_id=agent_id, agent_name=name, seconds=seconds, calls=calls)
            for agent_id, name, seconds, calls in rows
        ]
        month_seconds = await voice_call_repo.seconds_since(
            self.db, organization_id=ctx.organization_id, since=month_start()
        )
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        return VoiceUsage(
            start=start,
            end=end,
            seconds=sum(agent.seconds for agent in by_agent),
            calls=sum(agent.calls for agent in by_agent),
            by_agent=by_agent,
            month_seconds=month_seconds,
            monthly_minutes=None if organization is None else organization.voice_monthly_minutes,
        )
