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
from app.agents.spec import DelegationMode, SpecialistSpec
from app.agents.subagent_runtime import SUBAGENT_RUNTIME_RESOURCE, SubagentRuntime

__all__ = ["DELEGATION_TOOLS", "Delegation", "SubagentsConfig"]


class SubagentsConfig(BaseModel):
    """How this agent delegates, and to whom it may define its own specialists.

    Which *published* agents it delegates to is not here - that is
    `AgentSpec.subagents`, at the top level, because a pinned agent version is a
    reference between two rows and belongs where publish validation, the export
    and the permission model can all see it. A list of ids buried in a capability's
    config blob is a reference nothing walks.
    """

    inline: list[SpecialistSpec] = Field(
        default_factory=list,
        description=(
            "Specialists defined inside this agent, for work that does not justify "
            "publishing an agent of its own. Not versioned: editing this agent "
            "changes them, and nothing else can reference them."
        ),
    )
    mode: DelegationMode = Field(
        default="sync",
        description=(
            "Whether a delegation blocks this agent until it answers (sync), runs "
            "in the background and is collected later (async), or is decided per "
            "task from what the model says about it (auto). The author's choice, "
            "not the model's: the delegation tool's own mode argument defaults to "
            "sync, so a model that says nothing and a model that chose sync are "
            "the same call - auto is how you hand the decision to the model."
        ),
    )
    allow_dynamic: bool = Field(
        default=False,
        description=(
            "Whether this agent may invent specialists at run time rather than only "
            "using the ones it was given. Off, and off is the default for the same "
            "reason this product exists: an agent whose instructions nobody wrote "
            "is an agent nobody can review, budget or explain."
        ),
    )
    max_depth: int = Field(
        default=1,
        ge=0,
        le=3,
        description=(
            "How many levels of delegation are allowed. 1 lets this agent delegate "
            "and its delegates not; 0 turns delegation off while keeping the "
            "configuration. Bounded low on purpose - each level multiplies the "
            "requests one turn can make."
        ),
    )
    max_fanout: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "How many delegations may run at once. Reached, the next one is refused "
            "with a message the model can act on rather than an error. This is the "
            "ceiling on a background delegation launching a background delegation "
            "until a dozen agents are running against one budget."
        ),
    )
    include_general_purpose: bool = Field(
        default=False,
        description=(
            "Whether to offer the delegation library's own unspecialised delegate "
            "alongside the ones this agent pinned. Off, against the library's "
            "default: it is a copy of the parent with no instructions of its own, "
            "on the library's default model rather than one of this deployment's "
            "profiles - so it is neither reviewable nor priced like everything else "
            "here."
        ),
    )
    max_result_chars: int = Field(
        default=2000,
        ge=200,
        le=20_000,
        description=(
            "How much of a finished delegation's answer is shown when several are "
            "collected at once. A truncated one says so and points at the tool that "
            "returns it in full, so nothing is lost - this only decides how much of "
            "five specialists' work arrives in one turn's context."
        ),
    )
    share_with_delegates: list[str] = Field(
        default_factory=list,
        description=(
            "Capability ids bound on this agent that its inline specialists inherit, "
            "such as an MCP connection or a sandbox. Named one by one rather than "
            "shared by default: a specialist that silently gained the parent's "
            "credentials would be the quiet route around what the parent was "
            "granted."
        ),
    )


@register(
    id="subagents",
    name="Delegation",
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

    `None` - the capability is not attached - when there is no resolved runtime or
    it holds no delegates. That is a preview, a unit test, or an agent whose
    delegates were all removed, and in every case the honest answer is an agent
    without delegation rather than one carrying seven tools that can only refuse.
    Every tool in a list is context the model pays for on every turn.
    """
    runtime = ctx.resources.get(SUBAGENT_RUNTIME_RESOURCE)
    if not isinstance(runtime, SubagentRuntime) or not runtime.subagents:
        return None
    config = ctx.config if isinstance(ctx.config, SubagentsConfig) else SubagentsConfig()
    return build_delegation(
        runtime=runtime,
        mode=config.mode,
        max_fanout=config.max_fanout,
        include_general_purpose=config.include_general_purpose,
        max_result_chars=config.max_result_chars,
        # How far in this run's delegations already are, which is what a surface
        # needs to nest their panels. The runner hands down what is left of the
        # nesting budget, so the difference from the ceiling this spec set is the
        # level: a top-level run has spent none of it and delegates at depth 0.
        depth=max(config.max_depth - runtime.depth_remaining, 0),
    )
