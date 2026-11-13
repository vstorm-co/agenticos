"""Schemas for skill versions and forks."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.db.models.skill_check import AgentState, SampleKind
from app.db.models.skill_version import SkillVersionSource
from app.schemas.base import BaseSchema
from app.schemas.resource_usage import AgentUsage


class VersionRef(BaseSchema):
    """A version as another one points at it."""

    id: UUID
    number: int
    fork_id: UUID | None = Field(description="The fork it belongs to; null for the main line")


class PersonRef(BaseSchema):
    id: UUID
    name: str | None = Field(description="Null for somebody who is no longer a member")


class SkillVersionSummary(BaseSchema):
    """One version as the History tab lists it, without its text."""

    id: UUID
    skill_id: UUID
    fork_id: UUID | None = Field(description="The fork it belongs to; null for the main line")
    number: int = Field(description="Its number within its line: main and each fork count from 1")
    source: SkillVersionSource
    previous: VersionRef | None = Field(
        description=(
            "What it was made after: the line's previous version, or for a fork's first "
            "version the main version the fork started from"
        )
    )
    restored_from: VersionRef | None = None
    merged_from: VersionRef | None = Field(
        default=None,
        description=(
            "The other line's version it took in: main's for a fork catching up, the "
            "fork's for its changes moved to main"
        ),
    )
    proposal_id: UUID | None = Field(
        default=None, description="The skill change it applied, when it came from one"
    )
    created_by: PersonRef | None = None
    created_at: datetime
    agents: int = Field(
        description="How many agents read exactly this version in an environment that serves it"
    )


class VersionResourceSummary(BaseSchema):
    name: str
    description: str | None = None
    size_bytes: int
    digest: str = Field(
        description=(
            "The SHA-256 of the file's content: two versions name the same file with "
            "the same content exactly when their digests are equal"
        )
    )


class SkillVersionRead(SkillVersionSummary):
    description: str
    content: str
    resources: list[VersionResourceSummary] = Field(
        description="The files this version carries, without their contents"
    )


class SkillVersionList(BaseSchema):
    items: list[SkillVersionSummary]
    total: int


class VersionResourceRead(BaseSchema):
    name: str
    description: str | None = None
    content: str


class SkillVersionCreate(BaseSchema):
    """An edit of the text, saved as a new version on one line."""

    fork_id: UUID | None = Field(
        default=None, description="The fork to save it on; null saves it on the main line"
    )
    base_version_id: UUID = Field(
        description=(
            "The line's newest version as the editor read it. A line that moved since is "
            "refused rather than overwritten"
        )
    )
    description: str = Field(min_length=1, max_length=500)
    content: str


class SkillVersionRestore(BaseSchema):
    base_version_id: UUID = Field(
        description="The newest version of the restored version's line, as the person read it"
    )


class VersionNumberRef(BaseSchema):
    id: UUID
    number: int


class SkillForkRead(BaseSchema):
    """A fork as the skill page lists it."""

    id: UUID
    skill_id: UUID
    name: str
    base: VersionNumberRef = Field(
        description="The main version the fork is based on: where it started, or last caught up"
    )
    started_from: VersionNumberRef = Field(description="The main version the fork started from")
    latest: VersionNumberRef | None = Field(
        description="Its newest own version; null while it has none and serves its base"
    )
    changes: int = Field(description="How many versions of its own it has")
    behind_main: int = Field(
        description=(
            "How many main versions after its base changed what the skill says; 0 when main "
            "says what its base says"
        )
    )
    agents: int = Field(
        description="How many agents read it in an environment that serves it, hidden ones included"
    )
    archive_candidate: bool = Field(
        description="No agent reads it and no run has served it for 30 days"
    )
    archived_at: datetime | None = None
    created_by: PersonRef | None = None
    created_at: datetime


class SkillForkList(BaseSchema):
    items: list[SkillForkRead]
    total: int


class SkillForkCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=64)
    from_version_id: UUID = Field(description="The main version the fork starts from")


class SkillForkUpdate(BaseSchema):
    name: str = Field(min_length=1, max_length=64)


SkillBindingState = Literal["main", "pinned", "fork"]


class ForkRef(BaseSchema):
    id: UUID
    name: str
    base_number: int = Field(description="The main version the fork started from")
    changes: int = Field(description="How many versions of its own it has")


class SkillBindingRead(BaseSchema):
    """How one agent version reads a skill, and the version that comes to now."""

    state: SkillBindingState = Field(
        description="`main` follows the newest main version, `pinned` stays on one, `fork` follows a fork"
    )
    version: VersionRef = Field(description="The version it serves now")
    fork: ForkRef | None = None
    behind_main: int = Field(
        description=(
            "How many main versions after the one it reads changed what the skill says; 0 on "
            "main, and when main says what it reads"
        )
    )


class AgentEnvironmentBinding(BaseSchema):
    id: UUID
    name: str
    agent_version: int
    binding: SkillBindingRead


class AgentCheckRef(BaseSchema):
    """What a check found on one agent, for the version that check made."""

    check_id: UUID
    version_id: UUID
    state: AgentState
    sample: SampleKind | None = Field(
        default=None,
        description="`skill_set_only` when the agent was checked on the skill's questions alone",
    )
    at: datetime


class SkillAgentUsage(BaseSchema):
    """One agent that uses a skill, and which version it reads where."""

    agent: AgentUsage
    via_specialist: str | None = Field(
        default=None, description="The inline specialist that binds it, when the agent does not"
    )
    draft_only: bool = Field(
        description="Bound only in the draft: `binding` is the draft's, and no line counts it"
    )
    binding: SkillBindingRead = Field(
        description="What its default environment serves, or the first environment serving it"
    )
    agent_version: int | None = Field(description="That environment's agent version")
    environments: list[AgentEnvironmentBinding] = Field(
        description="The environments that read the skill differently from `binding`"
    )
    draft_differs: bool = Field(description="The draft reads the skill differently")
    can_change: bool = Field(description="The caller may change the binding, in the draft at least")
    can_publish: bool = Field(description="The caller may publish, so a change goes live")
    checked: AgentCheckRef | None = Field(
        default=None,
        description=(
            "The newest check of the version this agent uses now, as it found this agent; "
            "null when that version was never checked on it"
        ),
    )
    checked_versions: list[AgentCheckRef] = Field(
        default_factory=list,
        description=(
            "Every version of the skill a check made after measuring it on this agent, "
            "newest check first - so moving the agent to one says whether it was checked"
        ),
    )
    answered_with: list[UUID] = Field(
        default_factory=list,
        description=(
            "The skill's versions this agent's own answers have used - not an eval's, not "
            "a Builder test's - so a version it never left reads as not checked yet rather "
            "than unknown. Empty without `runs:view`."
        ),
    )


class SkillAgentList(BaseSchema):
    main_latest: VersionNumberRef
    items: list[SkillAgentUsage]
    hidden: int = Field(description="Agents using the skill that the caller may not see")


class SkillRef(BaseSchema):
    id: UUID
    name: str


class BehindMain(BaseSchema):
    """A pinned agent or a fork that main has moved past."""

    kind: Literal["pinned", "fork"]
    skill: SkillRef
    agent: AgentUsage | None = Field(default=None, description="The pinned agent; null for a fork")
    via_specialist: str | None = Field(
        default=None, description="The inline specialist that pins it, when the agent does not"
    )
    fork: ForkRef | None = Field(default=None, description="The fork; null for a pinned agent")
    agents: int = Field(
        description="How many agents read it: 1 for a pinned agent, every reader of a fork"
    )
    version: VersionNumberRef = Field(
        description="The main version it is on: the pinned one, or the one the fork started from"
    )
    main_latest: VersionNumberRef
    behind_main: int = Field(description="How many main versions came after `version`")
    can_act: bool = Field(
        description=(
            "The caller may start bringing it along: edit the agent for a pinned one, "
            "edit the skill for a fork. Never for a pin in a specialist "
            "(`via_specialist`), which changes in the agent's Builder"
        )
    )


class BehindMainList(BaseSchema):
    items: list[BehindMain]
    total: int
    hidden: int = Field(description="Pinned agents behind main that the caller may not see")


class ReturnToMain(BaseSchema):
    agent_ids: list[UUID] | None = Field(
        default=None,
        description="Which of the fork's agents to move; every one the caller can see when omitted",
    )


class ReturnedAgent(BaseSchema):
    agent: AgentUsage
    published: bool = Field(description="A new agent version went live; otherwise only its draft")
    agent_version: int | None = None
    refused: str | None = Field(
        default=None, description="Why it stayed on the fork; it was not moved"
    )


class ReturnedToMain(BaseSchema):
    """What moving a fork's agents back to main did, agent by agent."""

    agents: list[ReturnedAgent]
    hidden: int = Field(description="The fork's agents the caller may not see, left as they were")
    remaining: int = Field(
        description=(
            "Agents still reading the fork, hidden ones included: a move that waits in a "
            "draft leaves the served version on the fork until it is published"
        )
    )
    archived: bool = Field(description="Nobody reads the fork any more, so it was archived")


class SkillBindingChange(BaseSchema):
    """Which version an agent should read: main's newest, a main version, or a fork."""

    state: SkillBindingState
    version: int | None = Field(default=None, ge=1, description="The main version, for `pinned`")
    fork_id: UUID | None = Field(default=None, description="The fork, for `fork`")
    note: str | None = Field(default=None, max_length=500)
    check_id: UUID | None = Field(
        default=None,
        description="For a pinned agent moving to `main`: the finished check of main's newest "
        "version on it, which marks the agent checked rather than unknown",
    )
    acknowledge_unknown: bool = Field(
        default=False, description="Required with a `check_id` that could not check the agent"
    )

    @model_validator(mode="after")
    def _names_what_its_state_needs(self) -> SkillBindingChange:
        wanted = {"main": (False, False), "pinned": (True, False), "fork": (False, True)}
        if wanted[self.state] != (self.version is not None, self.fork_id is not None):
            raise ValueError(
                "`pinned` takes a version, `fork` takes a fork_id, and `main` takes neither"
            )
        if self.check_id is not None and self.state != "main":
            raise ValueError("A check is given only for an update to `main`")
        return self


class SkillBindingChanged(BaseSchema):
    published: bool = Field(
        description="A new agent version went live; otherwise only the draft changed"
    )
    agent_version: int | None = None
    environments: list[str] = Field(
        default_factory=list, description="The environments serving the new agent version"
    )
    usage: SkillAgentUsage | None = Field(
        default=None, description="The agent's row as it reads now, when it still uses the skill"
    )
