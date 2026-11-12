"""Which skills runs used: what a run records, and how often an agent used a skill."""

from datetime import date as CalendarDate
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import BaseSchema


class SkillUseRecord(BaseModel):
    """How one agent used one skill during one run.

    `run_id` and `created_at` are the run's, set when the run is written; a
    delegate's use is recorded on the run that delegated, under the delegate's
    `agent_id`, because the answer a person rated is that run's.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: UUID
    skill_id: UUID
    skill_version_id: UUID | None = None
    projected: bool = False
    loaded: bool = False
    resource_reads: int = 0
    workspace_reads: int = 0


class SkillUsageVersion(BaseSchema):
    skill_version_id: UUID | None = Field(
        description="The version served; null where the run recorded none, as before versions"
    )
    loads: int


class SkillUsageDay(BaseSchema):
    date: CalendarDate = Field(description="A day in UTC")
    loads: int


class SkillUsageAgent(BaseSchema):
    agent_id: UUID
    agent_name: str
    slug: str
    has_avatar: bool
    avatar_color: int | None
    loads: int = Field(
        description="Runs that opened the skill or read one of its files with `read_skill_resource`"
    )
    resource_reads: int
    workspace_reads: int = Field(
        description=(
            "Runs whose tool calls named a path in the skill's workspace folder and did not "
            "otherwise load it - probably used, and not counted in `loads`"
        )
    )
    last_loaded_at: datetime | None
    versions: list[SkillUsageVersion]
    daily: list[SkillUsageDay] = Field(
        description="`loads` per UTC day, every day of the window from the oldest, zeros included"
    )


class SkillUsageRead(BaseSchema):
    """How often a skill was used, by agent, over a window.

    Runs of evals and of the Builder's test panel are left out. Agents the caller
    may not see are counted, never named.
    """

    days: int
    since: datetime
    loads: int = Field(description="The sum of `loads` over the agents listed")
    agents: list[SkillUsageAgent]
    hidden_agents: int = Field(description="Agents that used the skill and the caller cannot see")
    hidden_loads: int
