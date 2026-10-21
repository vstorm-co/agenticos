"""Call minutes for the dashboard figure (#54), read from `voice_calls`."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.permissions import AuthContext
from app.repositories import voice_call_repo


@dataclass(frozen=True)
class AgentMinutes:
    """One agent's calls in the window; no id and no name for agents since deleted."""

    agent_id: UUID | None
    agent_name: str | None
    seconds: int
    calls: int


@dataclass(frozen=True)
class VoiceUsage:
    """A window's call seconds, by agent."""

    start: datetime
    end: datetime
    seconds: int
    calls: int
    by_agent: list[AgentMinutes]


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
        return VoiceUsage(
            start=start,
            end=end,
            seconds=sum(agent.seconds for agent in by_agent),
            calls=sum(agent.calls for agent in by_agent),
            by_agent=by_agent,
        )
