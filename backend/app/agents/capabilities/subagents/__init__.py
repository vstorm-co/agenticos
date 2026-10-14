"""Delegation - handing part of a job to another agent.

An agent here is instructions, a model and a set of capabilities. Delegation is
the capability that lets one of them call *another one*: a researcher that cites
sources, a summariser, a reviewer, each on its own model with its own knowledge
and its own step limit, addressed by name.

Two shapes of delegate, and the difference is the whole reason both exist. A
**published delegate** is another agent in the organization, pinned at a version
when the parent was published - reviewable, exportable, and unchanged until
somebody publishes a new pin. An **inline specialist** is defined inside the
parent's own spec, for the "summarise this in three bullets" jobs that should not
require publishing an agent; it is not versioned and editing the parent changes
it. Both are resolved by the runner before the run starts, which is why this
capability never reaches the database: a delegate is rows - an agent, a version,
its collections, its skills, its secrets - and every one of them has to pass
`resolve_access` first.

What this capability refuses is most of its value:

- **A delegate is not a privilege escalation.** It runs as the same user in the
  same organization, on the capabilities its own spec was published with, plus
  whatever the parent explicitly shared.
- **A delegation cannot outspend the run.** Every child request goes through the
  parent's budget guard and into the parent's ledger, so the cap that was set on
  the run somebody started is the cap that binds - and each delegation's share of
  it is recorded rather than inferred.
- **A delegation cannot recurse without a ceiling.** `max_depth` bounds nesting,
  `max_fanout` bounds concurrency, and each delegate's own `max_steps` bounds its
  loop.
"""

from pydantic import BaseModel, Field

from app.agents.capabilities._registry import CapabilityBuildContext, register
from app.agents.capabilities.subagents._capability import (
    DELEGATION_TOOLS,
    Delegation,
    build_delegation,
)
from app.agents.capabilities.subagents._journal import ActingDelegate, acting_delegate
from app.agents.spec import DelegationMode, SpecialistSpec
from app.agents.subagent_runtime import SUBAGENT_RUNTIME_RESOURCE, SubagentRuntime

__all__ = [
    "DELEGATION_TOOLS",
    "ActingDelegate",
    "Delegation",
    "SubagentsConfig",
    "acting_delegate",
]


class SubagentsConfig(BaseModel):
    """How this agent delegates, and to whom it may define its own specialists.

    Which *published* agents it delegates to is not here - that is
    `AgentSpec.subagents`, at the top level, because a pinned agent version is a
    reference between two rows and belongs where publish validation, the export
    and the permission model can all see it. A list of ids buried in a capability's
    config blob is a reference nothing walks.
    """

    inline: list[SpecialistSpec] = Field(
        title="Inline specialists",
        default_factory=list,
        description=(
            "Specialists defined inside this agent, for work that does not justify "
            "publishing an agent of its own. Not versioned: editing this agent "
            "changes them, and nothing else can reference them."
        ),
    )
    # The author's choice, not the model's: the tool's own mode argument defaults to
    # sync, so auto is the way to hand the decision over. A background delegation has
    # already returned a task id, so a gated call inside it is refused, not queued.
    mode: DelegationMode = Field(
        title="Delegation mode",
        default="sync",
        description=(
            "Sync waits for the delegate's answer, async collects it later, auto lets the "
            "model choose per task. A background delegation cannot wait for an approval, "
            "so keep work that needs one on sync."
        ),
    )
    # The question carries a name the parent published, so whether it may be asked is
    # the author's decision. A background delegation has nobody left to answer, and a
    # specialist the model invents always works autonomously.
    allow_questions: bool = Field(
        title="Let delegates ask questions",
        default=False,
        description=(
            "Lets a delegate ask the person waiting a question instead of guessing. Works "
            "only for a sync delegation, and only for the specialists this agent was "
            "given. A question is not an approval and cannot grant one."
        ),
    )
    # Off by default: instructions nobody wrote are instructions nobody reviewed.
    # Keeping a specialist means publishing an agent, which stays a person's decision.
    allow_dynamic: bool = Field(
        title="Let the agent create specialists",
        default=False,
        description=(
            "Lets this agent write its own specialists while it runs. Each is "
            "instructions and one of your models, with no tools or knowledge, spends from "
            "this run's budget and is gone after the reply. Gate `create_agent` to "
            "see each one first."
        ),
    )
    # A ceiling in both directions: as somebody's delegate this agent gets the lower of
    # this and what the caller's tree has left. At the bound a delegate is built
    # without the capability rather than with one that can only refuse; disabling the
    # binding is the one off switch.
    max_depth: int = Field(
        title="Delegation depth",
        default=1,
        ge=1,
        le=3,
        description=(
            "How many levels of delegation are allowed, counting this agent. 1 lets it "
            "delegate but not its delegates; 2 allows one nested level. Each level "
            "multiplies the requests one turn can make."
        ),
    )
    max_fanout: int = Field(
        title="Delegations at once",
        default=3,
        ge=1,
        le=10,
        description=(
            "How many delegations may run at once. Reached, the next one is refused "
            "with a message the model can act on rather than an error. This is the "
            "ceiling on a background delegation launching a background delegation "
            "until a dozen agents are running against one budget."
        ),
        json_schema_extra={"x-advanced": True},
    )
    max_result_chars: int = Field(
        title="Answer length shown per delegate",
        default=2000,
        ge=200,
        le=20_000,
        description=(
            "How much of a finished delegation's answer is shown when several are "
            "collected at once. A truncated one says so and points at the tool that "
            "returns it in full, so nothing is lost - this only decides how much of "
            "five specialists' work arrives in one turn's context."
        ),
        json_schema_extra={"x-advanced": True},
    )
    # Named one by one: a delegate silently gaining the parent's credentials would be
    # the quiet route around its grants. Delegation is refused here - an heir would
    # read the parent's specialists and allow_dynamic as its own - and an MCP
    # connection is named on the spec, not bound, so it cannot be shared.
    share_with_delegates: list[str] = Field(
        title="Capabilities delegates inherit",
        default_factory=list,
        description=(
            "Capabilities this agent passes on to its delegates, such as a shared "
            "workspace so one writes a file and another reads it. Nothing is shared "
            "unless named here, and delegation itself never is."
        ),
    )


@register(
    id="subagents",
    name="Subagents",
    category="reasoning",
    description="Hand part of a job to another agent, or to a specialist defined here.",
    # All ten, including the two a default configuration does not offer. A tool
    # absent from this list cannot be gated by the approval policy or renamed by a
    # binding, and the dangerous half of that is silent.
    tools=DELEGATION_TOOLS,
    config_schema=SubagentsConfig,
    scopes=("agents:delegate",),
    # Per tool, because this capability is genuinely several things: delegating
    # and reading a task's status are not decisions of the same kind as cancelling
    # one or steering it mid-run. One flag would either make an agent ask
    # permission to check on its own delegate, or let it kill one unattended.
    side_effecting=False,
)
def _build(ctx: CapabilityBuildContext) -> Delegation | None:
    """Build from the delegation tree the runner resolved, or nothing at all.

    `None` - the capability is not attached - when there is no resolved runtime,
    or when it holds neither a delegate nor permission to invent one. That is a
    preview, a unit test, or an agent whose delegates were all removed, and in
    every case the honest answer is an agent without delegation rather than one
    carrying ten tools that can only refuse. Every tool in a list is context the
    model pays for on every turn.

    `allow_dynamic` on its own is a complete configuration and has to be treated
    as one: an orchestrator that invents every specialist it uses has nothing to
    pin, and requiring a delegate as well would have made the switch do nothing
    for exactly the author who turned it on.
    """
    runtime = ctx.resources.get(SUBAGENT_RUNTIME_RESOURCE)
    if not isinstance(runtime, SubagentRuntime) or not (
        runtime.subagents or runtime.dynamic is not None
    ):
        return None
    config = ctx.config if isinstance(ctx.config, SubagentsConfig) else SubagentsConfig()
    return build_delegation(
        runtime=runtime,
        mode=config.mode,
        allow_questions=config.allow_questions,
        max_fanout=config.max_fanout,
        max_result_chars=config.max_result_chars,
        # How far in this run's delegations already are, which is what a surface
        # needs to nest their panels. Taken from the runtime, which the runner
        # stamped while it walked the tree, rather than computed from
        # `max_depth - depth_remaining`: those two numbers come from different
        # specs - the ceiling is *this* agent's setting, the remainder is what the
        # tree has left - so any delegate that configured a different ceiling
        # reported the wrong depth and a panel nested under the wrong parent.
        depth=runtime.depth,
    )
