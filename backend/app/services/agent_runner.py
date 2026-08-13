"""Running a published agent, and recording what it cost.

Every surface - the playground, a Slack mention, the public API - goes through
here. That is deliberate: if each surface assembled its own agent, budgets and
run history would hold whatever each one remembered to record, and the first
surface someone added in a hurry would be the one with no limits.

The service owns the run lifecycle:

    resolve version -> resolve model -> build -> execute -> record cost

The cost row is written in a `finally` block. A run that crashed still spent
money, and a budget that only counts successful runs is not a budget.

The same reasoning is why the *limits* are resolved here too, not handed in.
A run is under exactly two caps - the agent's own monthly limit and the
organization's - and each is a
:class:`~app.agents.capabilities.budget.SpendLimit` carrying the lookup that
meters *its* spend: `agent.id` for the agent, `ctx.organization_id` for the
organization. Neither is collapsed into the other, because the tighter of two
numbers means nothing when the numbers count different things; whichever binds
first stops the run and names itself.

A run can also stop without an answer. When the approval gate parks a
side-effecting tool call, the run is recorded as `awaiting_approval` with
everything it needs to continue stored on the row, and :meth:`~AgentRunnerService.resume`
picks it up once a person has decided - in another process, possibly the next
day. Holding the coroutine open instead would cost a task and a connection per
pending decision, for however long the approver takes to look.

That stored position is a **tree**, because a delegate that stops for a person
stops the whole run: the delegate suspends on its gated tool, the parent suspends
on the `task` call that delegated to it, and so on up to the run somebody
started. Each level keeps its own conversation and its own parked calls
(:class:`PausedRunState`), and the resume walks it - continuing the delegate where
it stopped instead of delegating again. That is not an optimisation. The approval
a person granted names the *delegate's* tool call while the replayed parent
presents its own, so a re-run delegation is handed a verdict it never asks about
and the model is free to call something else: what a reviewer approved would not
be what executes, with nothing raising.

A run may also delegate, and that is the third thing this module owns. A
delegate is a row, its pinned version is a row, and its collections, skills and
secrets are rows - so the whole delegation tree is resolved *here*, before the
run starts, and handed to the delegation capability as
:class:`~app.agents.subagent_runtime.SubagentRuntime`. The capability holds no
session and the request's `AsyncSession` is not concurrency-safe, so a
delegation that had to fetch anything would be a query on a shared session in
the middle of a tool call. What is left at run time is a closure that builds an
agent already resolved, and a recorder that writes one row.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, UserContent
from pydantic_ai.run import AgentRun as AgentIteration
from pydantic_ai.run import AgentRunResult
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, ToolApproved
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.approval import (
    ApprovalDecision,
    ApprovalGranted,
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
)
from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    BudgetScope,
    SpendEntry,
    metered_by,
)
from app.agents.capabilities.channel_tools import (
    CHANNEL_DIRECTORY_RESOURCE,
    CHANNEL_TOOLS_CAPABILITY_ID,
    ChannelDirectory,
)
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE, WorkspaceIdentity
from app.agents.capabilities.sandbox._identity import SessionScope
from app.agents.capabilities.subagents import SubagentsConfig, acting_delegate
from app.agents.deps import AgentDeps
from app.agents.factory import BuiltAgent, build_agent
from app.agents.model_resolver import ModelRequestSpec
from app.agents.observability import current_trace_id
from app.agents.spec import (
    AgentSpec,
    CapabilityBindingSpec,
    ObservabilitySpec,
    SpecialistSpec,
    SubagentRef,
)
from app.agents.subagent_runtime import (
    SUBAGENT_RUNTIME_RESOURCE,
    DelegationOutcome,
    DelegationRecorder,
    DelegationSpend,
    DelegationStash,
    DelegationStatus,
    DynamicSpecialistBuilder,
    DynamicSpecialists,
    ParkedDelegation,
    RegisteredSpecialist,
    ResolvedSubagent,
    ResumedDelegation,
    SubagentRuntime,
)
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    RunExecutionError,
)
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import StorableSecret
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunOrder, RunStatus, RunSurface
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Message
from app.repositories import (
    agent_environment_repo,
    agent_exposure_repo,
    agent_repo,
    agent_run_repo,
    conversation_repo,
    knowledge_base_repo,
    message_rating_repo,
)
from app.repositories.agent_run import AgentSpendRow, RunFilters
from app.schemas.agent import ParkedCall
from app.services.agent_registry import (
    DEFAULT_GRANTED_SCOPES,
    DELEGATION_CAPABILITY_ID,
    AgentRegistryService,
    delegation_binding,
)
from app.services.approvals import ApprovalService
from app.services.attachments import AttachmentRouter
from app.services.channels.attachments import files_written, workspace_snapshot
from app.services.channels.base import OutgoingAttachment
from app.services.channels.prompt_variables import resolve as resolve_prompt_variables
from app.services.mcp_connection import build_toolsets_for_agent
from app.services.model_profile import ModelProfileService
from app.services.notifications import NotificationService
from app.services.organization import OrganizationService
from app.services.organization_secret import OrganizationSecretService
from app.services.sandbox_workspace import (
    SANDBOX_CAPABILITY_ID,
    OpenWorkspace,
    SandboxWorkspaceService,
)
from app.services.skill_proposal import SkillProposalService
from app.services.skill_workspace import MaterialisedSkills, collect_changes
from app.services.skill_workspace import materialise as materialise_skills
from app.services.skills import SkillService
from app.services.spend import month_start, organization_monthly_spend
from app.services.transcript import (
    RecordedToolCall,
    TranscriptService,
    settled_calls_in,
    tool_calls_in,
)

logger = logging.getLogger(__name__)

_DELEGATION_RUN_STATUS: Mapping[DelegationStatus, RunStatus] = {
    "completed": RunStatus.COMPLETED,
    "failed": RunStatus.FAILED,
    "cancelled": RunStatus.CANCELLED,
}
"""How a delegation's outcome is recorded as a run status.

Three of the six, and no fourth added for delegation: a delegated run ends the
same three ways any run ends, and a `delegated` status would answer "how did it
end" with "it was delegated". `parent_run_id` answers that.
"""


def _delegation_config(spec: AgentSpec) -> SubagentsConfig | None:
    """This spec's delegation policy, or `None` if the agent does not delegate.

    The binding comes from `delegation_binding`, which publish validation reads
    too - including its rule that a *disabled* binding is not delegation. One
    reader, so the specialists, the depth cap and the shared capabilities cannot
    be found by publish and missed by the run. This adds only the validation,
    because the runner needs the fields and the validator needs the binding.

    An agent whose spec does not bind the capability is assembled exactly as it
    was before delegation existed: nothing new reaches `resources`.
    """
    binding = delegation_binding(spec)
    return None if binding is None else SubagentsConfig.model_validate(binding.config)


def _secret_ids(spec: AgentSpec) -> list[UUID]:
    """Every secret this spec's build has to unseal.

    The capability bindings' credentials plus the observability token, which
    rides along because it is the same kind of reference resolved at the same
    moment - a second unsealing pass would be a second place for a tenant check
    to be missed.
    """
    ids = [binding.secret_id for binding in spec.capabilities if binding.secret_id]
    if spec.observability and spec.observability.token_secret_id:
        ids.append(spec.observability.token_secret_id)
    return ids


def _with_shared(spec: AgentSpec, shared: list[CapabilityBindingSpec]) -> AgentSpec:
    """The delegate's spec, plus the capabilities its caller shares with it.

    Sharing is by binding, so the delegate gets the parent's configuration of
    that capability verbatim - the same connection, the same secret reference,
    the same tool overrides. Nothing is reconfigured. In practice this exists for
    `sandbox`: the parent's workspace backend travels with it (see
    :meth:`AgentRunnerService._delegate_resources`), so a researcher writes
    `/workspace/notes.md` and a writer reads it instead of opening a session of
    its own and finding it empty.

    A capability the delegate already binds itself is left alone. Its own
    configuration is the more specific statement of intent, and a spec carrying
    the same id twice would build one of the two with no indication which.
    """
    own = {binding.id for binding in spec.capabilities}
    inherited = [binding for binding in shared if binding.id not in own]
    return spec.model_copy(update={"capabilities": [*spec.capabilities, *inherited]})


def _without_delegation(spec: AgentSpec) -> AgentSpec:
    """The spec with delegation removed, for an agent at the end of the chain.

    Used where nesting stops - the depth bound, and every inline specialist,
    which does not delegate by construction. The capability is *removed* rather
    than left in place with nothing to delegate to: a tool that always answers
    "no delegates available" is a tool description the model reads and pays for
    on every turn of every run, and the first thing it does with one is try it.
    """
    return spec.model_copy(
        update={
            "capabilities": [
                binding for binding in spec.capabilities if binding.id != DELEGATION_CAPABILITY_ID
            ],
            "subagents": [],
        }
    )


def _refuse_duplicate_names(resolved: list[ResolvedSubagent]) -> None:
    """Refuse a tree where two delegates answer to one name.

    The name is what the parent's model addresses, and
    :meth:`~app.agents.subagent_runtime.SubagentRuntime.named` answers with the
    first match - so a specialist called `researcher` beside a delegate whose
    slug is `researcher` would silently run one where the author meant the other.
    Two *delegates* cannot collide: `AgentSpec` refuses two pins of one agent and
    `uq_agent_org_slug` refuses two agents with one slug. A specialist and a
    delegate can, because a specialist's name is free text in the parent's own
    config and nothing outside this run has ever seen it.

    Raises:
        BadRequestError: Naming the collision, before any tokens are spent.
    """
    counts = Counter(entry.name for entry in resolved)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        raise BadRequestError(
            message="Two of this agent's delegates answer to the same name",
            details={"names": duplicates},
        )


class DynamicSpecialistFrame(BaseModel):
    """One specialist a level of the tree kept with `create_agent`, stored across a park.

    The library holds a `create_agent` registration in a registry it builds per
    *built* agent, and a resume is a fresh build - so without this a specialist kept
    before an approval park was gone after it, while the replayed transcript still
    said it had been created and `task` answered "unknown subagent" (agenticos#175).
    The four fields are the whole of what `create_agent` was given, which is exactly
    what a resume needs to build the specialist again on the run's shared budget.

    Where one of these is stored says which level kept it: the run's own agent's sit
    flat on `PausedRunState.dynamic_specialists`, and a nested delegate's hang off
    that delegate's :class:`DelegationFrame` the way its conversation does - which is
    what carries a nested delegate's specialist across a park too (agenticos#254). See
    :class:`app.agents.subagent_runtime.RegisteredSpecialist`.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="How the model addresses it in `task`")
    description: str = Field(description="What it is for, one line")
    instructions: str = Field(description="Its system prompt - the whole of its behaviour")
    model: str = Field(description="The organization model profile label it runs on")


class DelegationFrame(BaseModel):
    """A delegation the run parked inside, and where its delegate stopped.

    A parked run is a *tree*, because a delegate that stopped for a person stopped
    the whole run: the parent's `task` call parks too, and so does its parent's, up
    to the run somebody started. Storing only the top of that - which is what
    `paused_state` used to hold - makes the resume delegate again from nothing,
    with the granted approval keyed on a tool call the replayed run never asks
    about. The model is then free to call something else, so **what a reviewer
    approved is not what executes**, and nothing raises.

    `messages` empty means the delegate's place could not be kept - the library's
    message history is best-effort telemetry - and then this delegation is re-run
    from the start. The frame is still recorded, because the `task` call has to be
    answered on the replay whatever happens to the delegate: Pydantic AI refuses a
    resume that leaves a parked call without a result.

    The spend is carried whether the place was kept or not, and for a different
    reason: it is what the delegation has already cost, which is true of a
    delegation re-run from the start exactly as it is of one continued. Left out,
    the child run row written when the delegation ends holds only what the last
    turn spent - see :class:`app.agents.subagent_runtime.DelegationSpend`.

    `dynamic_specialists` is the same shape for `create_agent`: the specialists this
    delegate kept, so a nested `create_agent` survives the park its own delegate
    caused. It rides on the frame rather than on the flat run-level list because a
    nested delegate has its own registry, and a resume seeds each level's from its own
    key (agenticos#254).
    """

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(
        description=(
            "The `task` call in the delegating agent's transcript. The replayed run "
            "presents the same call, which is what identifies this delegation"
        )
    )
    task_id: str = Field(description="The delegation library's own id for this delegation")
    parent_task_id: str | None = Field(
        default=None,
        description=(
            "The delegation this one was made inside, or null when the run's own "
            "agent made it. What nests the tree without guessing"
        ),
    )
    subagent: str = Field(description="The name the delegating agent's model addressed")
    agent_id: UUID | None = Field(
        default=None, description="The delegate's agent, or null for an inline specialist"
    )
    agent_version_id: UUID | None = Field(
        default=None, description="The version it was pinned to, or null for an inline specialist"
    )
    child_run_id: str | None = Field(
        default=None, description="Pydantic AI's run id for the suspended delegate run"
    )
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "The delegate's conversation as of the stop. Empty means its place "
            "could not be kept, and the delegation is re-run rather than continued"
        ),
    )
    cost_usd: Decimal = Field(
        default=Decimal(0),
        description=(
            "What this delegation had cost by the moment it stopped, so the turn "
            "that continues it records the whole of it and not only the tail"
        ),
    )
    input_tokens: int = Field(default=0, description="The same, in input tokens")
    output_tokens: int = Field(default=0, description="The same, in output tokens")
    cost_is_partial: bool = Field(
        default=False,
        description=(
            "Whether a request before the stop went unpriced, making `cost_usd` a "
            "floor. Carried because `cost_is_partial` on the child's run row is read "
            "per delegation now, so the turn that resumes cannot re-derive it"
        ),
    )
    billed_cost_usd: Decimal = Field(
        default=Decimal(0),
        description=(
            "What this delegation's row is owed by the stop - its own spend plus its "
            "inline specialists', which `cost_usd` above leaves out because that is "
            "the panel number. Equal to `cost_usd` for a delegate with no inline "
            "specialist below it; carried so a published delegate that parked with "
            "one resumes with its month intact (agenticos#228). Zero on an inline "
            "specialist's own frame - it bills to its ancestor's row, not its own"
        ),
    )
    billed_input_tokens: int = Field(default=0, description="The billed share, in input tokens")
    billed_output_tokens: int = Field(default=0, description="The billed share, in output tokens")
    billed_cost_is_partial: bool = Field(
        default=False,
        description="Whether the billed share went unpriced, making `billed_cost_usd` a floor",
    )
    started_at: datetime | None = Field(
        default=None,
        description=(
            "When this delegation's delegate first began, so the row written when it "
            "ends begins at its first segment rather than at the resume. The earliest "
            "start across every segment so far; null when none was ever stamped"
        ),
    )
    delegations: list[DelegationFrame] = Field(
        default_factory=list, description="Delegations this delegate had itself parked on"
    )
    dynamic_specialists: list[DynamicSpecialistFrame] = Field(
        default_factory=list,
        description=(
            "The specialists this delegate kept with `create_agent`, re-registered "
            "into its fresh registry on resume so a nested `create_agent` survives the "
            "park too. Empty for a delegate that kept none, and for one parked before "
            "this existed"
        ),
    )


class PausedRunState(BaseModel):
    """What a parked run needs to pick up where it stopped.

    Stored on the run rather than on the approval because it describes the
    *run's* position, and a single step can park several calls at once.

    Every field but `messages` and `tool_call_ids` is optional with a default, and
    that is load-bearing rather than tidy: `extra="forbid"` is on this model, this
    is read back out of a JSONB column, and a run parked before delegation existed
    has to stay resumable. An older payload validates as a run that delegated
    nothing, which is what it was.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]] = Field(
        description="The conversation as of the parked call, in Pydantic AI's message format"
    )
    tool_call_ids: dict[str, str] = Field(
        description="Approval id -> the tool call it parked, so a decision can be replayed"
    )
    delegated_approvals: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Approval id -> the delegation whose delegate asked for it. Absent "
            "means the run's own agent asked, which is every approval on a run "
            "that did not delegate"
        ),
    )
    delegations: list[DelegationFrame] = Field(
        default_factory=list, description="The delegations this run parked inside"
    )
    dynamic_specialists: list[DynamicSpecialistFrame] = Field(
        default_factory=list,
        description=(
            "The specialists the run's own agent kept with `create_agent`, so a "
            "park does not lose them. Empty for a run that kept none, and for one "
            "parked before this existed"
        ),
    )


@dataclass(frozen=True)
class ParkedApproval:
    """One tool call waiting for a person, and everything its row will hold.

    Carries the `approvals` row id rather than the model's `tool_call_id`: the
    decision is recorded against that row, and it is the row the approvals queue
    and the notification email point at. A surface that invented its own
    identifier would be a second way to approve the same call.

    The id is allocated when the call is parked rather than by the database,
    because the row is not written until the run reaches its terminal write - see
    :meth:`ApprovalChannel.__call__`. This is the same shape, and the same reason,
    as :class:`RecordedDelegation`: a description the run collects while it runs
    and :meth:`AgentRunnerService._write_approvals` turns into rows once, off the
    shared session, when nothing is racing it.
    """

    approval_id: UUID
    tool_call_id: str
    """The model's own id for the call, so a surface can resolve the card it drew
    for it. Carried beside the row id rather than instead of it: one addresses the
    decision, the other addresses what is on screen."""

    tool_name: str
    tool_args: dict[str, Any]

    subagent: str | None = None
    """Which delegate asked, or `None` for the run's own agent."""

    subagent_agent_id: UUID | None = None
    """That delegate's own agent, or `None` for the run's own agent or an inline
    specialist, which has no agent of its own. Read from the delegation in flight
    when the call is parked and carried here, because the row that names it is
    written after the run ends, when the contextvar is long gone."""

    task_id: str | None = None
    """The delegation the ask came from, or `None` for the run's own agent.

    This is what splits one run's parked calls by the agent that made them, and it
    has to be split: Pydantic AI refuses a resume whose results name a call the
    replayed response does not contain, so a delegate's parked call handed to the
    parent's replay fails the whole continuation.
    """


@dataclass
class ApprovalChannel:
    """A run's connection to the approval queue.

    Handed to the agent as `AgentDeps.request_approval`: the gate asks, this
    answers. A first ask parks the call and returns pending; a resumed run is
    built with the recorded decisions already in hand.

    Decisions are consumed on use. If the model calls the same tool a second
    time after being approved once, that is a second act on the world and needs
    its own approval - reusing the first would let one "yes" authorise a loop.

    **Parking a call touches no database.** The row is *described* here and written
    once by :meth:`AgentRunnerService._write_approvals` from the run's terminal
    write. This is not tidiness - it is what makes the channel concurrency-safe.
    Pydantic AI runs the tool calls from one model response concurrently, and
    `parallel_tool_calls` is unset by default, so that is the provider's decision,
    not the author's - a model that answers "email the customer and email the
    account manager" in one step drives two gated calls into this channel at once.
    Both would `await` a write on the request's `AsyncSession`, which the whole run
    shares and which is not concurrency-safe; two inserts on it at once do not
    produce a slow query, they corrupt the session and take the parent run row and
    the conversation with it (agenticos#169). With the write deferred, `__call__`
    never awaits, so the two calls cannot interleave inside it.
    """

    organization_id: UUID
    agent_id: UUID
    run_id: UUID
    decided: dict[str, ApprovalDecision] = field(default_factory=dict)
    parked: dict[str, str] = field(default_factory=dict)

    requested: list[ParkedApproval] = field(default_factory=list)
    """What was parked, in enough detail for a surface to put it to somebody and
    for :meth:`AgentRunnerService._write_approvals` to write the row.

    Kept here rather than read back from the rows afterwards for two reasons: the
    rows do not exist yet while the run is going, and re-reading them would be a
    query per parked call to recover what this object already had in hand.
    """

    async def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        decision = self.decided.pop(request.tool_call_id, None)
        if decision is not None:
            return decision

        # Which delegate is asking, if the ask came from inside a delegation. Read
        # from the delegation in flight rather than carried on the request, because
        # the gate that builds the request belongs to whichever agent it was built
        # for and has no way to know it is a delegate. Two things need it: the row,
        # so a reviewer sees who is sending the email as well as that one is being
        # sent, and the parked state, which has to know which agent's replay this
        # call belongs to.
        delegate = acting_delegate()
        # Allocated here, not by the database, because the row is written after the
        # run ends. Everything below is synchronous - a `uuid4`, a dict set and a
        # list append, each atomic under the GIL - so with no `await` in the body
        # two concurrent gated calls cannot interleave and race the shared session.
        approval_id = uuid4()
        self.parked[str(approval_id)] = request.tool_call_id
        self.requested.append(
            ParkedApproval(
                approval_id=approval_id,
                tool_call_id=request.tool_call_id,
                tool_name=request.tool_name,
                tool_args=request.tool_args,
                subagent=None if delegate is None else delegate.name,
                # The delegate's own agent, which is *not* `self.agent_id`: that one
                # is the agent whose run this is and what the row is scoped by. Null
                # for an inline specialist, which has no agent of its own.
                subagent_agent_id=None if delegate is None else delegate.agent_id,
                task_id=None if delegate is None else delegate.task_id,
            )
        )
        return ApprovalPending()


def _delegation_frames(
    parked: Sequence[ParkedDelegation],
    registered: Mapping[str | None, Sequence[RegisteredSpecialist]],
) -> list[DelegationFrame]:
    """One run's parked delegations, nested the way they were made.

    Assembled from a flat list because that is what the capability can safely
    produce: a fan-out runs several delegations in several asyncio tasks, and each
    appends its own frame without knowing what any other did. The nesting is
    recovered from `parent_task_id`, which each level read where its delegation
    opened - so two concurrent chains cannot be threaded into one.

    The recursion is bounded by `max_depth`, and by the fact that a delegation's
    children all carry its task id as their parent while its own parent is
    something else.

    `registered` is what each level kept with `create_agent`, keyed by the `task`
    call the level was delegated from - the same key the capability snapshotted it
    under. A frame carries the specialists its own delegate kept, looked up by the
    frame's `tool_call_id`, so a nested `create_agent` rides on the same frame its
    conversation does and survives the park (agenticos#254). The run's own agent's
    key (`None`) is not read here - `_parked_tree` puts it on the flat run-level list.
    """
    by_parent: dict[str | None, list[ParkedDelegation]] = {}
    for entry in parked:
        by_parent.setdefault(entry.parent_task_id, []).append(entry)

    def specialists(tool_call_id: str) -> list[DynamicSpecialistFrame]:
        return [
            DynamicSpecialistFrame(
                name=kept.name,
                description=kept.description,
                instructions=kept.instructions,
                model=kept.model,
            )
            for kept in registered.get(tool_call_id, [])
        ]

    def frames(entries: list[ParkedDelegation]) -> list[DelegationFrame]:
        return [
            DelegationFrame(
                tool_call_id=entry.tool_call_id,
                task_id=entry.task_id,
                parent_task_id=entry.parent_task_id,
                subagent=entry.subagent,
                agent_id=entry.agent_id,
                agent_version_id=entry.agent_version_id,
                child_run_id=entry.child_run_id,
                messages=entry.messages,
                cost_usd=entry.spent.cost_usd,
                input_tokens=entry.spent.input_tokens,
                output_tokens=entry.spent.output_tokens,
                cost_is_partial=entry.spent.has_unpriced_models,
                billed_cost_usd=entry.spent.billed_cost_usd,
                billed_input_tokens=entry.spent.billed_input_tokens,
                billed_output_tokens=entry.spent.billed_output_tokens,
                billed_cost_is_partial=entry.spent.billed_has_unpriced_models,
                started_at=entry.started_at,
                delegations=frames(by_parent.get(entry.task_id, [])),
                dynamic_specialists=specialists(entry.tool_call_id),
            )
            for entry in entries
        ]

    return frames(by_parent.get(None, []))


@dataclass(frozen=True)
class _ResumePlan:
    """How a parked run and everything it parked inside are continued.

    Two products of one walk, because they are two halves of one answer: the run's
    own replay needs results for the calls *it* stopped on, and each delegation it
    parked inside needs the same thing for its delegate, one level in.
    """

    results: DeferredToolResults
    """For the run somebody started. Never a delegate's parked calls: Pydantic AI
    refuses a resume whose results name a call the replayed response does not
    contain, so one flat set for the whole tree fails the continuation outright -
    which is what a run parked inside a delegate did before this existed."""

    delegations: dict[str, ResumedDelegation]
    """Keyed by the `task` call each delegation was made from, which is the only
    thing the delegation capability knows about one before it starts it."""

    spent: dict[str, DelegationSpend]
    """What each delegation in the tree has already cost, on the same key.

    Every frame, including one whose delegate is re-run rather than continued: what
    it spent before the park is what it spent, and the row written when it ends is
    the only place that money is attributed to the delegate's own agent.
    """

    started: dict[str, datetime | None]
    """When each delegation in the tree first began, on the same key.

    The clock's companion to :attr:`spent`, and filled for every frame the same
    way: when the delegate first ran is a fact whether or not its place was kept,
    and the row written when the delegation ends must begin there rather than at
    the resume that settled it.
    """

    specialists: dict[str, list[RegisteredSpecialist]]
    """The specialists each *continued* delegate kept, on the same `task`-call key.

    Only for a frame whose place was kept: a delegate re-run from the start re-runs
    its own `create_agent` and registers them again, so seeding those would be a
    duplicate. A continued delegate does not re-run `create_agent` - the call is a
    completed entry in its replayed history - so its registry starts empty and has to
    be seeded, which is exactly the nested case agenticos#254 was losing. The run's
    own agent's are not here; they come off `PausedRunState.dynamic_specialists`
    under the `None` key.
    """


def _resume_plan(state: PausedRunState, decided_args: Mapping[str, dict[str, Any]]) -> _ResumePlan:
    """Split a parked run's verdicts across the agents that were waiting on them.

    `decided_args` is the arguments a person authorised, keyed by tool call. A call
    with none is a `task` call: the delegation itself was never put to anybody, and
    approving it here only means "let this call reach the tool pipeline again",
    where the capability continues the delegate instead of starting one. The gate
    remains the only thing allowed to decide whether a *gated* tool runs, which is
    why every parked call is approved here and refusals are carried separately.
    """
    by_delegation: dict[str | None, list[str]] = {}
    for approval_id, tool_call_id in state.tool_call_ids.items():
        by_delegation.setdefault(state.delegated_approvals.get(approval_id), []).append(
            tool_call_id
        )

    resuming: dict[str, ResumedDelegation] = {}
    spent: dict[str, DelegationSpend] = {}
    started: dict[str, datetime | None] = {}
    specialists: dict[str, list[RegisteredSpecialist]] = {}

    def level(frames: list[DelegationFrame], own: list[str]) -> DeferredToolResults:
        results = DeferredToolResults()
        for tool_call_id in own:
            results.approvals[tool_call_id] = ToolApproved(
                override_args=decided_args.get(tool_call_id)
            )
        for frame in frames:
            results.approvals[frame.tool_call_id] = ToolApproved()
            # Before the `continue` below, because neither what a delegation has
            # spent nor when it first began is conditional on its place having been
            # kept: a delegation re-run from the start still spent it and still
            # began when it began, and the row written when it ends is where both
            # reach the delegate's own agent.
            spent[frame.tool_call_id] = DelegationSpend(
                cost_usd=frame.cost_usd,
                input_tokens=frame.input_tokens,
                output_tokens=frame.output_tokens,
                has_unpriced_models=frame.cost_is_partial,
                # The row's share, carried alongside the panel's so a published
                # delegate that parked with an inline specialist below it resumes
                # with its month whole (agenticos#228). Zero on an inline
                # specialist's frame, which bills to its ancestor, not itself.
                billed_cost_usd=frame.billed_cost_usd,
                billed_input_tokens=frame.billed_input_tokens,
                billed_output_tokens=frame.billed_output_tokens,
                billed_has_unpriced_models=frame.billed_cost_is_partial,
            )
            started[frame.tool_call_id] = frame.started_at
            if not frame.messages:
                # The delegate's place was not kept, so there is nothing to
                # continue. The `task` call is still answered above - a parked call
                # left without a result makes the whole run unresumable - and the
                # delegation runs again from the start.
                continue
            resuming[frame.tool_call_id] = ResumedDelegation(
                task_id=frame.task_id,
                messages=ModelMessagesTypeAdapter.validate_python(frame.messages),
                results=level(frame.delegations, by_delegation.get(frame.task_id, [])),
            )
            # Seeded only for a continued delegate, and keyed by the `task` call it
            # was delegated from - which is what its own `build_delegation` reads back
            # as `enclosing_tool_call_id()` to fill its fresh registry.
            if frame.dynamic_specialists:
                specialists[frame.tool_call_id] = [
                    RegisteredSpecialist(
                        name=kept.name,
                        description=kept.description,
                        instructions=kept.instructions,
                        model=kept.model,
                    )
                    for kept in frame.dynamic_specialists
                ]
        return results

    return _ResumePlan(
        results=level(state.delegations, by_delegation.get(None, [])),
        delegations=resuming,
        spent=spent,
        started=started,
        specialists=specialists,
    )


@dataclass(frozen=True)
class RecordedDelegation:
    """One finished delegation, waiting for the run's terminal write.

    Everything a row needs that only the delegation knows. What the *parent* knows
    - the organization, the person, the conversation, the binding, the surface -
    is read off the parent's row when the rows are written, so it cannot drift
    from it.

    `id` is allocated when the delegation is reported rather than by the database,
    because the parent's model is told the id while the run is still going and the
    row is written after it ends.

    No `ModelRequestSpec` here, only the three fields a row records from it: the
    resolved spec carries a live credential, and a list that outlives the tool call
    is not a place to keep one.
    """

    id: UUID
    agent_id: UUID
    agent_version_id: UUID
    task_id: str
    status: RunStatus
    model_label: str | None
    provider: str | None
    secret_id: UUID | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    cost_is_partial: bool
    started_at: datetime
    ended_at: datetime
    error: str | None = None


@dataclass
class PreparedRun:
    """An agent ready to execute, with its run row already open.

    Returned rather than executed inline because surfaces stream differently: a
    WebSocket iterates events, a Slack handler awaits a final answer, the API
    may do either. They share the setup and the accounting, not the loop.
    """

    run: AgentRun
    agent: Agent
    spec: AgentSpec
    built: BuiltAgent
    approvals: ApprovalChannel
    workspace: OpenWorkspace | None = None
    """The sandbox this run writes to, when its spec asks for one.

    Carried on the prepared run rather than hidden in the agent because it has
    to be *closed*: a `state` workspace is only stored by the flush in
    :meth:`AgentRunnerService.finish`, and nothing else in the process knows the
    run is over.
    """

    materialised_skills: MaterialisedSkills | None = None
    """The skill files written into that workspace, as they were written.

    Kept so that `finish` can tell what the agent changed from what it was given.
    Diffing against the database instead would re-propose every change a reviewer
    already discarded, on every turn of a conversation whose workspace outlives
    the run.
    """

    workspace_at_start: set[str] | None = None
    """Every path the workspace held before the turn ran.

    What the turn *added* is the difference against this. Compared against a
    snapshot rather than modification times: a `state` workspace has none, and a
    container's clock is not ours to trust.

    `None` means there was no readable workspace to snapshot - no sandbox at all,
    or a host that would not answer - and nothing is posted back. It is not an
    empty set: the difference is computed against this, so an empty one would make
    every file already in the workspace read as the turn's own output.
    """

    outbound: list[OutgoingAttachment] = field(default_factory=list)
    """Files the turn produced, read in `finish` before the workspace closes.

    Filled there rather than returned by the run, because a `run`-scoped workspace
    is released by `close` and a caller reading it afterwards would find nothing.
    """

    outbound_refused: list[str] = field(default_factory=list)
    """Produced files a reply cannot carry - too large, or past the per-reply cap.

    Named rather than dropped: an agent told its file was delivered will tell the
    user the same.
    """

    delegations: list[RecordedDelegation] = field(default_factory=list)
    """What this run delegated, waiting to be written by `finish`.

    Filled during the run by the recorder the delegation capability calls, and
    written once at the end. Carried on the prepared run for the same reason the
    workspace is: it is something `finish` has to act on, and nothing else in the
    process knows the run is over.
    """

    stash: DelegationStash = field(default_factory=DelegationStash)
    """Where a delegate that stopped for a person left its place.

    Carried here so that :meth:`AgentRunnerService.finish` can fold it into the
    parked state, rather than each streaming surface remembering to. That is the
    same reasoning as the run's budget caps being resolved in this module: a thing
    every surface has to remember is a thing the next surface will not, and this
    one fails by silently answering a different question rather than by raising.
    """

    ctx: AuthContext | None = None
    """Who ran it, for recording a proposal in `finish`.

    A workspace flush needs no tenant - it writes a row it already holds - but a
    proposal does: it is stored against an organization and read by a reviewer
    there. Carried rather than re-derived, because `finish` is called from a
    `finally` where the request may already be gone.
    """

    @property
    def deps(self) -> AgentDeps:
        return self.built.deps

    async def execute(
        self,
        user_prompt: str | Sequence[UserContent] | None,
        *,
        message_history: Sequence[ModelMessage] | None,
        deferred_tool_results: DeferredToolResults | None,
    ) -> AgentRunResult[str | DeferredToolRequests]:
        """Run the agent to an answer, metered.

        The non-streaming half of :meth:`iterate`, and it exists for the same
        reason.
        """
        with metered_by(self.built.ledger):
            return await self.built.agent.run(
                user_prompt,
                deps=self.built.deps,
                message_history=message_history,
                deferred_tool_results=deferred_tool_results,
                usage_limits=self.built.usage_limits,
            )

    @asynccontextmanager
    async def iterate(
        self,
        user_prompt: str | Sequence[UserContent] | None,
        *,
        message_history: Sequence[ModelMessage] | None,
    ) -> AsyncIterator[AgentIteration[AgentDeps, str | DeferredToolRequests]]:
        """Iterate the agent's graph, metered, for a surface that streams.

        **The meter is here rather than at the call site because a surface that
        forgets it bills nothing and says nothing.** `metered_by` is what books
        the spend a request wrapper cannot see - the embedding call behind a
        knowledge search - to this run's ledger. Miss it and
        :func:`~app.agents.capabilities.budget.record_ambient_usage` finds no
        active ledger and drops the cost silently: the run under-reports, the
        organization's month never sees it, and nothing raises. The web chat ran
        that way for its whole life (agenticos#16), which is the argument for the
        agent being unreachable from a surface except through here.

        Yields the library's run object, so the caller drives the graph and
        decides what to forward. It stays readable after the block closes; the
        outcome is taken from it there.
        """
        with metered_by(self.built.ledger):
            async with self.built.agent.iter(
                user_prompt,
                deps=self.built.deps,
                message_history=message_history,
                usage_limits=self.built.usage_limits,
            ) as iteration:
                yield iteration


def _outcome(
    agent_run: AgentIteration[AgentDeps, str | DeferredToolRequests],
) -> AgentRunResult[str | DeferredToolRequests]:
    """What the iterated run ended with.

    Raises:
        RuntimeError: If it ended without a result. That is not a state the
            agent can reach on its own - it means whoever drove the loop stopped
            early - so it fails loudly and is recorded as a failed run, rather
            than being persisted as an empty answer.
    """
    if agent_run.result is None:
        raise RuntimeError("The agent run ended without a result")
    return agent_run.result


type RunStream = Callable[[AgentIteration[AgentDeps, str | DeferredToolRequests]], Awaitable[None]]
"""How a surface that shows an answer arriving drives the run.

Given to :meth:`AgentRunnerService.execute`, which iterates the graph instead of
awaiting it and hands the run object over. The surface decides what to forward -
the web chat forwards every event to a socket, a chat platform edits one post
every second or so - and the settle path around it is unchanged, so a streamed
run is metered exactly like one that was waited for.
"""


async def _with_exposure_prompt(
    spec: AgentSpec, exposure: AgentExposure | None, directory: ChannelDirectory | None = None
) -> AgentSpec:
    """The spec as this binding wants it, if the binding says anything.

    A binding is created holding the platform's own style - what that client
    renders, how a link is written there - as its starting text, so what the
    agent will be told is what somebody editing it can see, change and delete.
    From here it is simply the binding's text.

    **Appended, never substituted.** A surface shapes how an answer is
    delivered; what the agent is *for* belongs to the version somebody published,
    and a binding that could replace it would be a way to repurpose an approved
    agent without approving anything. The copy is local to this run -
    `model_copy` leaves the stored spec alone.
    """
    added = "" if exposure is None else (exposure.prompt or "").strip()
    if not added:
        return spec
    # `{channel_name}`, `{member_list}` - filled in from the platform, per run,
    # and only when the prose actually names one. Async for that reason: a
    # placeholder is an HTTP call to somebody's chat server, and a binding that
    # names none costs nothing at all.
    added = await resolve_prompt_variables(added, directory)
    return spec.model_copy(update={"instructions": f"{spec.instructions}\n\n{added}"})


def _with_channel_tools(spec: AgentSpec, exposure: AgentExposure | None) -> AgentSpec:
    """The spec with the lookups *this* binding grants, if it grants any.

    The one capability whose binding is not in the published spec, and the
    reason is the same one that put `prompt` on the exposure: an agent can
    answer on two Mattermost servers and three Slack workspaces, and "may it
    read what was said in this channel" has a different answer on the internal
    one and the customer one. A field on the spec has one answer for all five.

    So it is assembled here, per run, from the row that admitted the message -
    and it goes through `AgentSpec.capabilities` rather than straight into
    `resources` on purpose. That is what keeps these tools ordinary: gateable by
    the approval policy, renameable by a binding, and visible to
    `approval_required_tools`, all of which read the spec. The copy is local to
    this run; `model_copy` leaves the stored spec alone, and publishing refuses
    a stored spec that tries to carry this capability itself.
    """
    granted = [] if exposure is None else list(exposure.tools or [])
    if not granted:
        return spec
    binding = CapabilityBindingSpec(id=CHANNEL_TOOLS_CAPABILITY_ID, config={"tools": granted})
    return spec.model_copy(update={"capabilities": [*spec.capabilities, binding]})


@dataclass
class _RunBudget:
    """The run's budget guard, once the build has produced one.

    A delegate is built with `shared_budget=` the parent's guard - that is what
    puts a delegation's spend under the parent's caps and into the parent's
    ledger. The guard is a product of `build_agent`, and the resolved delegates
    have to be *inside* the `resources` that same call reads, so there is no
    ordering in which a delegate's build closure could be handed the guard
    directly. It reads this instead, at the moment the model actually delegates,
    which is always after the assignment in `_assemble`.

    The same shape, and the same reason, as
    :attr:`~app.agents.subagent_runtime.SubagentRuntime.ledger`.
    """

    guard: BudgetGuard | None = None


@dataclass(frozen=True)
class _Delegation:
    """What every level of one run's delegation tree is resolved against.

    One object rather than ten parameters threaded through four methods: all of
    it belongs to the *run* rather than to the delegate being resolved, and an
    argument list that long is how a `run_id` ends up where a `conversation_id`
    was meant to go.
    """

    ctx: AuthContext
    run: AgentRun
    agent_id: UUID
    """The agent that started the run. An inline specialist is built under it,
    having no id of its own."""

    user_id: str | None
    user_name: str | None
    approvals: ApprovalChannel
    budget: _RunBudget

    record: DelegationRecorder
    """One recorder for the whole tree, because there is one run row to hang a
    delegation off. A nested delegation's row points at the run somebody started
    rather than at its immediate caller's - which does not exist yet while the
    grandchild is running, and would never exist for an inline specialist."""

    queued: list[RecordedDelegation]
    """Where the recorder leaves a finished delegation for `finish` to write."""

    attribution: dict[UUID, ModelRequestSpec]
    """Which model each pinned delegate resolved to, keyed by version id.

    Filled while the tree is resolved and read when a delegation is recorded, so
    a child row names the model that actually answered instead of leaving the
    cost dashboard to group it under "not recorded". Keyed by version rather than
    by name, because a name is only unique within one level of the tree.
    """

    runtimes: list[SubagentRuntime]
    """Every runtime the tree produced, for the one assignment they all need."""

    stash: DelegationStash
    """One stash for the whole tree, because a delegation three levels down parks
    the run somebody started and is continued from that run's stored state."""

    profiles: dict[str, ModelRequestSpec] = field(default_factory=dict)
    """The organization's model catalog, resolved at most once and only if asked for.

    Every model a specialist a model invented may run on, keyed by the label an
    author sees - see :meth:`AgentRunnerService._model_catalog`. Empty means
    *not yet read* rather than "this organization has none", which is a state a
    run cannot be in: the delegating agent's own profile resolved before any of
    this, so the catalog always holds at least it.

    Shared across the tree because it is a fact about the organization, not about
    a level, and reading it costs a query and a vault unseal per profile. Two
    nested levels that both allow dynamic specialists would otherwise pay for it
    twice.
    """


def _register_runtime(
    delegation: _Delegation,
    subagents: list[ResolvedSubagent],
    *,
    depth_remaining: int,
    depth: int,
    dynamic: DynamicSpecialists | None,
) -> SubagentRuntime:
    """One level of the tree, and a note that its ledger is still owed.

    Collected rather than returned up the recursion because every level shares
    the run's single ledger: that makes one assignment to make, in one place,
    with nowhere for a nested level to be forgotten. The stash is shared for the
    same reason and can be handed over here, because it is not a product of the
    build.

    `depth` is how many delegations deep the agent holding this runtime already is,
    told rather than computed - see :attr:`SubagentRuntime.depth`.

    `dynamic` is per level and not inherited: whether an agent may invent a
    specialist is its own spec's `allow_dynamic`, so a delegate that switched it on
    gets it whatever its caller said, and one that did not is not handed its
    caller's permission.
    """
    runtime = SubagentRuntime(
        subagents=tuple(subagents),
        record=delegation.record,
        depth_remaining=depth_remaining,
        depth=depth,
        dynamic=dynamic,
        stash=delegation.stash,
    )
    delegation.runtimes.append(runtime)
    return runtime


def _delegate_builder(
    delegation: _Delegation,
    *,
    spec: AgentSpec,
    model: ModelRequestSpec,
    agent_id: UUID,
    resources: dict[str, Any],
    secrets: Mapping[UUID, StorableSecret],
    extra_toolsets: list[Any],
) -> Callable[[], PydanticAgent[Any, Any]]:
    """A closure that builds one delegate, with nothing left to look up.

    Everything the database can answer has been answered by the time this
    returns - the model profile, the collections, the skills, the secrets, the
    MCP toolsets - so what the closure does is CPU work and Pydantic AI. That is
    what makes it safe to call from inside a tool call, on a session the whole run
    shares.

    Lazy because a delegate the model never calls must cost nothing: building one
    constructs every capability it has and instruments the agent. The capability
    calls this at most once per run and caches the result, which a stateless
    Pydantic AI agent makes correct for a fan-out of ten calls to one delegate.
    """

    def build() -> PydanticAgent[Any, Any]:
        return build_agent(
            spec,
            model,
            organization_id=delegation.ctx.organization_id,
            agent_id=agent_id,
            run_id=delegation.run.id,
            user_id=delegation.user_id,
            user_name=delegation.user_name,
            granted_scopes=DEFAULT_GRANTED_SCOPES,
            resources=resources,
            secrets=secrets,
            extra_toolsets=extra_toolsets,
            # The person waiting on the parent is the person a delegate has to
            # ask, so the gate reaches the same queue rather than refusing
            # because a delegation has no channel of its own.
            request_approval=delegation.approvals,
            # The run's guard, so this delegate checks and records against the
            # one ledger the parent's caps are measured on. Without it a
            # delegate meters nothing the parent can see, and the parent's cap
            # stops binding at exactly the moment delegation multiplies spend.
            shared_budget=delegation.budget.guard,
        ).agent

    return build


def _dynamic_builder(
    delegation: _Delegation, *, profiles: Mapping[str, ModelRequestSpec]
) -> DynamicSpecialistBuilder:
    """How a specialist a run's model invents becomes an agent of this platform's.

    Through :func:`_delegate_builder`, which is the point rather than a
    convenience: a dynamic specialist arrives at `build_agent` with the run's
    `shared_budget`, the run's approval channel and a `ModelRequestSpec` resolved
    from one of the organization's own profiles, exactly as an inline specialist
    does. That is what makes its model request metered, and it is the whole
    difference between this and the delegation library building one itself from
    its own default model string.

    `profiles[model]` cannot raise: the library validates the model against
    `DynamicSpecialists.allowed_models`, which is the keys of this same mapping,
    before it calls the factory.

    Called immediately rather than kept, unlike a resolved delegate's closure. A
    delegate the model never addresses should cost nothing, but this specialist was
    asked for by name a moment ago - and building here is what lets `create_agent`
    report success only when there is genuinely an agent.

    `agent_id` is the *run's* agent, as it is for an inline specialist: a specialist
    has no agent row of its own, so nothing attributes a run row to it and its cost
    is the parent's. It also keys the workspace session, which is why it must not
    be invented.
    """

    def build(*, name: str, instructions: str, model: str) -> PydanticAgent[Any, Any]:
        return _delegate_builder(
            delegation,
            # Instructions and a model, and deliberately nothing else: no
            # capabilities, no collections, no skills, no MCP connections and no
            # delegates - so a specialist a model wrote cannot reach anything the
            # organization granted the agent that invented it, and cannot delegate
            # a level further.
            spec=AgentSpec(
                name=name, instructions=instructions, model_profile_id=profiles[model].profile_id
            ),
            model=profiles[model],
            agent_id=delegation.agent_id,
            resources={"kb_collection_names": [], "skills": []},
            secrets={},
            extra_toolsets=[],
        )()

    return build


def _spend_already_booked(run: AgentRun) -> SpendEntry:
    """A resumed run's opening balance, as one ledger entry.

    A resumed run keeps its own row, so its ledger has to start with what the
    run already spent. Otherwise finishing it would overwrite the cost with only
    what the continuation cost, and the per-run budget would reset every time
    somebody approved something - which is exactly the run a budget is for.
    """
    return SpendEntry(
        model_name=run.model_label or "unknown",
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cost_usd=run.cost_usd,
        priced=not run.cost_is_partial,
    )


def _observability_of(stored: dict[str, Any]) -> ObservabilitySpec | None:
    """The observability block of a stored spec, without validating the rest of it.

    One block out of the document rather than `AgentSpec.model_validate`, because
    a spec that has stopped validating - a capability dropped in a deploy, a
    narrowed rule - is exactly the agent somebody is trying to read a trace for.
    Refusing them the link would make a debugging aid fail on the runs that need
    debugging.
    """
    block = stored.get("observability")
    if not isinstance(block, dict):
        return None
    try:
        return ObservabilitySpec.model_validate(block)
    except ValidationError:
        logger.warning("run_trace_observability_unreadable")
        return None


@dataclass(frozen=True)
class RunSegment:
    """One execution of a run, and what it did while it lasted.

    A run is executed once when it is started and once more every time somebody
    approves what it parked on, so "the run" and "this execution of it" are
    different things and only the second one knows what the model just called.

    `tool_calls` is that difference made available to a caller. The resume
    endpoint is why it exists: a continuation runs over HTTP rather than the
    socket a conversation streams, so its `tool_call` frames reach nobody, and a
    client that was handed only the answer had no way to draw the steps that
    produced it. Approving a call showed nothing happening and then asked for a
    second approval nothing on screen accounted for.

    Attributes:
        output: What the agent answered, empty when it parked again or stopped.
        run: The run row, as `finish` left it.
        tool_calls: What this execution called, in order, each with what came
            back - `None` on the call the run is now parked on.
        settled: What the calls it *inherited* returned, by tool call id. A resume
            runs the call somebody approved, and that call was made by the previous
            execution - so its return arrives here without it, and it belongs to a
            step already on screen rather than to a new one.
    """

    output: str
    run: AgentRun
    tool_calls: list[RecordedToolCall]
    settled: dict[str, str]


def run_failure_summary(exc: Exception) -> str:
    """The sentence a failed run may store, for an exception it may not.

    `agent_runs.error` used to hold `str(exc)` of whatever came out of the run.
    It is a stored column on `AgentRunRead`, rendered in run history to every
    member who can read it, and what raises there is a model client with `httpx`
    underneath - so that routinely meant an endpoint, an internal host, or a URL
    with a key still in its query string, sitting in a row somebody opens weeks
    later. Same rule as #342 in an HTTP body, #423 in the ingestion columns and
    #659 in the chat frame, with the longest life of the four (#676).

    Ours is kept whole. An `AppException` raised inside the run is written in
    this repository, and its message is the most useful thing an operator can be
    shown - "No model profile is configured for this agent" beats any sentence
    composed here. (The one place that folds a foreign `__str__` into an
    `AppException` is `sandbox_workspace._reason`, deliberately and for a route's
    answer; it runs outside both `try` blocks that call this.) `BudgetExceeded`
    never reaches this function: it is caught above and its ceiling is the point
    of it.

    Anything else is a foreign `__str__` and only its *type* is safe to store,
    plus the status code when a provider answered one. That code is what keeps
    the failures a person can act on themselves actionable - 401 a credential,
    404 a model the profile names and the provider does not have, 429 a rate
    limit, 400 a request the model refused - where a bare class name would make
    all four `ModelHTTPError`. An `int` has never carried a URL.

    A group is unwrapped to its first leaf first, the same unwrapping
    `failure_summary` and `probe_error_message` do. MCP toolsets and delegated
    runs sit on anyio task groups, so their failures arrive as an
    `ExceptionGroup` whose own name diagnoses nothing at all - which would spend
    the status code above on the failures most likely to carry one.
    """
    cause: BaseException = exc
    while isinstance(cause, BaseExceptionGroup):
        cause = cause.exceptions[0]
    if isinstance(cause, AppException):
        return str(cause)
    diagnosis = type(cause).__name__
    if isinstance(cause, ModelHTTPError):
        diagnosis = f"{diagnosis}, HTTP {cause.status_code}"
    return (
        f"The run did not finish ({diagnosis}) - retry it, and check the agent's model "
        "profile if it keeps failing. The server log has the full error."
    )


class AgentRunnerService:
    """Prepare, execute and account for agent runs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.models = ModelProfileService(db)
        self.skills = SkillService(db)
        self.secrets = OrganizationSecretService(db)
        self.approvals = ApprovalService(db)
        self.organizations = OrganizationService(db)
        self.workspaces = SandboxWorkspaceService(db)
        self.proposals = SkillProposalService(db)
        self.transcript = TranscriptService(db)

    async def _collection_names(self, spec: AgentSpec, ctx: AuthContext) -> list[str]:
        """Vector-store collection names for the agent's bound collections.

        Resolved server-side and passed through deps: the model asks *what* to
        search, never *where*.
        """
        names: list[str] = []
        for collection_id in spec.collection_ids:
            collection = await knowledge_base_repo.get_by_id(self.db, collection_id)
            if collection is None or collection.organization_id != ctx.organization_id:
                # A collection deleted after publish degrades the agent's reach
                # rather than failing the run - the answer is worse, not absent.
                logger.warning(
                    "Agent references collection %s which is gone from org %s",
                    collection_id,
                    ctx.organization_id,
                )
                continue
            names.append(collection.collection_name)
        return names

    async def prepare(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        # The same default `execute` carries, so the two cannot disagree about
        # what an unnamed surface is. Every production caller passes one.
        surface: RunSurface = RunSurface.API,
        conversation_id: UUID | None = None,
        channel_key: str | None = None,
        channel_directory: ChannelDirectory | None = None,
        user_name: str | None = None,
        extra_toolsets: list[Any] | None = None,
        exposure: AgentExposure | None = None,
        model_profile_id: UUID | None = None,
        environment_id: UUID | None = None,
    ) -> PreparedRun:
        """Assemble everything a run needs and open its row.

        Args:
            channel_directory: The one channel this run is answering in, ready
                to be asked about, or `None` on every surface that is not a
                channel. Bound by the caller because binding one needs the bot
                row and its unsealed token, and a capability may reach neither -
                the same reason the workspace backend is opened here rather than
                inside `sandbox`.
            exposure: The binding that admitted this run, when one did. It is
                stamped on the run row and its caps are enforced - so a run that
                arrived through a place the agent was published to is both
                attributable to that place and bounded by it.
            model_profile_id: Run on this model instead of the one the spec
                names. What an agent *does* - its instructions, its tools, its
                approval gates - is unchanged; only which model executes it is.
                The run row records the model that actually ran, so a cheaper or
                stronger model chosen for one conversation stays attributable
                and stays inside the same budget.
            environment_id: Run the version this environment pins instead of
                the default. Falls back to the exposure's environment - a bot
                bound to `dev` serves dev without every caller re-deriving it -
                and then to the default environment's version.

        Raises:
            BadRequestError: If the agent is unpublished, archived, or its spec
                no longer validates - surfaced before any tokens are spent.
        """
        effective_environment_id = environment_id or (
            exposure.environment_id if exposure is not None else None
        )
        agent, spec, version_id = await self.registry.get_runnable_spec(
            ctx, agent_id, environment_id=effective_environment_id
        )
        spec = await self._with_environment_observability(
            ctx, spec, environment_id=effective_environment_id
        )
        spec = await _with_exposure_prompt(spec, exposure, channel_directory)
        spec = _with_channel_tools(spec, exposure)
        return await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=None,
            surface=surface,
            conversation_id=conversation_id,
            channel_key=channel_key,
            channel_directory=channel_directory,
            model_profile_id=model_profile_id,
            user_name=user_name,
            extra_toolsets=extra_toolsets,
            exposure=exposure,
            decided={},
            resuming={},
            already_spent={},
            already_started={},
            version_id=version_id,
            environment_id=effective_environment_id,
        )

    async def _assemble(
        self,
        ctx: AuthContext,
        *,
        agent: Agent,
        spec: AgentSpec,
        existing_run: AgentRun | None,
        surface: RunSurface,
        conversation_id: UUID | None,
        channel_key: str | None = None,
        channel_directory: ChannelDirectory | None = None,
        user_name: str | None,
        extra_toolsets: list[Any] | None,
        exposure: AgentExposure | None,
        decided: dict[str, ApprovalDecision],
        resuming: dict[str, ResumedDelegation],
        already_spent: dict[str, DelegationSpend],
        already_started: dict[str, datetime | None],
        specialists: Mapping[str | None, Sequence[RegisteredSpecialist]] | None = None,
        model_profile_id: UUID | None = None,
        version_id: UUID | None = None,
        environment_id: UUID | None = None,
    ) -> PreparedRun:
        """Build the agent for a run, opening its row unless one is being resumed.

        The single funnel a fresh run and a resumed one share. Splitting them
        would mean two places that decide what an agent may reach, and the
        second one would eventually forget something.

        `version_id` is the version the spec was resolved from - stamped on a
        fresh run so history records what actually answered, which an
        environment can make different from `current_version_id`. A resumed
        run keeps the version it was parked on.

        `decided` and `resuming` are the two halves of a continuation, and both go
        into the assembly rather than into the run call: a verdict is answered by
        the approval gate of whichever agent asked, and a stashed delegate is
        continued by the delegation capability of whichever agent delegated - so
        both have to be in place before anything is built. `already_spent` and
        `already_started` travel with them because all three are read at the same
        moment: the delegation is opened by the replayed `task` call, and what it
        cost before the park - and when it first began - have to be in the stash by
        then or the row it eventually writes holds only this turn's spend and begins
        at the resume.

        `specialists` is the same kind of thing for `create_agent`, keyed by the
        `task` call each level was delegated from: `None` for the run's own agent, a
        nested delegate's enclosing call otherwise. `None` on a fresh run and filled
        from `PausedRunState` on a resume, re-registered by each level's delegation
        capability before the replay so a kept specialist is reachable after the park
        that created it - at the run's own agent (agenticos#175) and inside a nested
        delegate (agenticos#254) alike.
        """
        # A caller's override wins over the spec's choice. Only the model is
        # replaced - instructions, tools, budgets and the approval gate are the
        # agent's, so this cannot be used to run something the agent is not.
        model_spec = await self.models.resolve(
            ctx, profile_id=model_profile_id or spec.model_profile_id
        )

        # The organization's ceiling is read here rather than passed in by the
        # surface, for the reason this module exists: a limit each caller has to
        # remember is a limit the next surface will not have. It used to be a
        # parameter with a default of "no cap" and no production caller, so
        # twelve agents in one organization meant twelve independent caps and no
        # ceiling. `ctx.organization_id` is also the only tenant in scope here,
        # which is what keeps the cap and the spend it is measured against - the
        # `period_spend` below - reading the same organization.
        organization = await self.organizations.get_by_id(ctx.organization_id)

        # Everything a capability needs but must not fetch itself. Resolved once,
        # server-side, so the model cannot influence what an agent reaches.
        resources: dict[str, Any] = {
            "kb_collection_names": await self._collection_names(spec, ctx),
            "skills": await self.skills.resolve_for_agent(ctx, spec.skill_ids),
        }
        # Only on a channel run, and bound to the channel the message arrived in
        # before it got here. Absent everywhere else, and `channel_tools` then
        # builds nothing at all - an agent in the dashboard has no channel to
        # ask about, and four tools that can only answer "there is no channel
        # here" are worse than none, because the model keeps trying.
        if channel_directory is not None:
            resources[CHANNEL_DIRECTORY_RESOURCE] = channel_directory

        # Unsealed here and handed straight to the factory, which hands them to
        # the capability instances that declared them. They are kept out of
        # `resources` deliberately: a resource may end up in a log line and a
        # secret may not.
        secrets = await self.secrets.resolve_for_bindings(ctx, _secret_ids(spec))

        # The MCP servers the spec binds, resolved here rather than by each
        # surface. A surface that forgot would produce an agent missing half its
        # tools with nothing to show for it, and the answer would differ between
        # the playground and Slack for no reason anybody could see.
        spec_toolsets = await build_toolsets_for_agent(
            self.db, organization_id=ctx.organization_id, connection_ids=spec.mcp_server_ids
        )

        run = existing_run
        if run is None:
            run = await agent_run_repo.create_run(
                self.db,
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                agent_version_id=version_id or agent.current_version_id,
                user_id=ctx.user_id,
                conversation_id=conversation_id,
                environment_id=environment_id,
                exposure_id=exposure.id if exposure else None,
                channel_identity_id=ctx.channel_identity_id,
                surface=surface.value,
                model_label=model_spec.label,
                provider=model_spec.provider,
                secret_id=model_spec.secret_id,
                started_at=datetime.now(UTC),
            )

        # Two lookups, because the caps they feed meter two different things. The
        # agent's own cap used to read the organization-wide number below, which
        # made `AgentSpec.budget.monthly_usd` a second organization cap wearing
        # an agent's name: an agent with a $10 limit was refused once its
        # *neighbours* had spent $10, and nothing ever isolated its own spend.
        async def agent_period_spend() -> Decimal:
            return await self.monthly_spend(ctx, agent_id=agent.id)

        async def org_period_spend() -> Decimal:
            return await self.monthly_spend(ctx)

        # Opened after the run row, because a run-scoped workspace keys on it,
        # and before the agent, because the capability reads the backend out of
        # `resources`. Nothing starts here for a container-backed one: the
        # client opens its session on the first tool call, so an agent granted a
        # workspace it never touches costs nothing.
        workspace = await self.workspaces.open(
            spec,
            ctx=ctx,
            identity=WorkspaceIdentity(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                run_id=run.id,
                conversation_id=conversation_id,
                user_id=None if ctx.user_id is None else str(ctx.user_id),
                channel_key=channel_key,
            ),
            # What the binding that admitted this run says, if it says anything.
            # The same agent in web chat and on a Slack bot is one agent in two
            # situations, and one value for both was the wrong shape.
            scope_override=(
                cast("SessionScope | None", exposure.session_scope)
                if exposure is not None and exposure.session_scope
                else None
            ),
        )
        materialised: MaterialisedSkills | None = None
        started_with: set[str] | None = None
        if workspace is not None:
            resources[WORKSPACE_BACKEND_RESOURCE] = workspace.backend
            # Skills as files, beside the shell that can run them. A skill whose
            # resource is a script was previously handed to the model as text it
            # could quote and not execute, while the same agent had `execute` one
            # tool call away.
            materialised = await materialise_skills(workspace.backend, resources["skills"])
            # After the skills are written, so materialising them does not read as
            # the turn's own output.
            started_with = await workspace_snapshot(workspace.backend)

        channel = ApprovalChannel(
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            run_id=run.id,
            decided=decided,
        )

        # Everything a delegation needs, resolved while there is still a session
        # and an auth context to resolve it with. `None` for an agent that does
        # not delegate, and then nothing new reaches `resources` at all - the
        # assembly below is what it was before delegation existed.
        run_budget = _RunBudget()
        runtimes: list[SubagentRuntime] = []
        delegations: list[RecordedDelegation] = []
        stash = DelegationStash(
            resuming=resuming,
            spent=already_spent,
            started=already_started,
            to_register={} if specialists is None else {k: list(v) for k, v in specialists.items()},
        )
        runtime = await self._delegation_runtime(
            ctx,
            spec=spec,
            agent=agent,
            run=run,
            user_name=user_name,
            resources=resources,
            approvals=channel,
            budget=run_budget,
            runtimes=runtimes,
            delegations=delegations,
            stash=stash,
        )
        if runtime is not None:
            resources[SUBAGENT_RUNTIME_RESOURCE] = runtime

        built = build_agent(
            spec,
            model_spec,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            run_id=run.id,
            # Not `str(ctx.user_id)`: a context with no subject would stringify
            # to the literal "None" and hand it to every tool as the caller's
            # id. `AgentDeps.user_id` is already optional precisely so a surface
            # without a person can say so, and "None" is the one answer that
            # looks like an answer.
            user_id=None if ctx.user_id is None else str(ctx.user_id),
            user_name=user_name,
            granted_scopes=DEFAULT_GRANTED_SCOPES,
            resources=resources,
            secrets=secrets,
            extra_toolsets=[*(extra_toolsets or []), *spec_toolsets],
            agent_period_spend=agent_period_spend,
            org_period_spend=org_period_spend,
            org_monthly_budget_usd=organization.monthly_budget_usd,
            request_approval=channel,
        )

        # Both only assignable now, and both before the run starts. The guard and
        # the ledger are products of the build, while the runtime had to be inside
        # the `resources` that build read - so the ordering is the one thing that
        # cannot be arranged in a constructor. Every level of the tree shares the
        # run's single ledger, which is what makes a delegation's spend visible to
        # the parent's cap before the next request.
        run_budget.guard = built.budget
        for entry in runtimes:
            entry.ledger = built.ledger

        return PreparedRun(
            run=run,
            agent=agent,
            spec=spec,
            built=built,
            approvals=channel,
            workspace=workspace,
            materialised_skills=materialised,
            workspace_at_start=started_with,
            delegations=delegations,
            stash=stash,
            ctx=ctx,
        )

    async def _delegation_runtime(
        self,
        ctx: AuthContext,
        *,
        spec: AgentSpec,
        agent: Agent,
        run: AgentRun,
        user_name: str | None,
        resources: dict[str, Any],
        approvals: ApprovalChannel,
        budget: _RunBudget,
        runtimes: list[SubagentRuntime],
        delegations: list[RecordedDelegation],
        stash: DelegationStash,
    ) -> SubagentRuntime | None:
        """The delegation tree this run may reach, or `None` if it delegates to none.

        Resolved here, in full, before the run starts: a delegate is a row, its
        pinned version is a row, and so are its collections, skills and secrets.
        The capability that will use this holds no session, and the one this
        service holds is shared by everything in the run and is not
        concurrency-safe - so a tree walked at run time would be a query per
        delegation from inside a tool call.

        Args:
            resources: The run's own resource dict, from which a shared
                capability's instance state travels to the delegates. Read, never
                handed on: see :meth:`_delegate_resources`.
            budget: The holder the delegates' build closures read the run's guard
                out of, filled by `_assemble` once the build has produced one.
            runtimes: Collects every level's runtime, so `_assemble` can give them
                all the run's ledger in one pass.
            delegations: Where the recorder leaves what it recorded, for `finish`
                to write. Nothing is written while the run is going: see
                :meth:`_delegation_recorder`.
            stash: The run's parked delegations, in both directions - where a
                delegate that stops for a person leaves its place, and where a
                continuation finds one. Given to every level of the tree, because
                the run being continued is the one somebody started however deep
                the delegation that parked it was.

        Raises:
            BadRequestError: If a pin names a version that is gone, if a delegate
                is already running higher up the tree, or if two delegates answer
                to one name. All three refuse the run rather than narrowing it: a
                missing collection makes an answer worse, but a delegation nobody
                can explain makes the run untrustworthy.
        """
        config = _delegation_config(spec)
        if config is None:
            return None

        attribution: dict[UUID, ModelRequestSpec] = {}
        delegation = _Delegation(
            ctx=ctx,
            run=run,
            agent_id=agent.id,
            # Not `str(ctx.user_id)`: a context with no subject would stringify to
            # the literal "None" and hand it to every delegate's tools as the
            # caller's id, for the reason `_assemble` says at greater length.
            user_id=None if ctx.user_id is None else str(ctx.user_id),
            user_name=user_name,
            approvals=approvals,
            budget=budget,
            record=self._delegation_recorder(run=run, attribution=attribution, queued=delegations),
            queued=delegations,
            attribution=attribution,
            runtimes=runtimes,
            stash=stash,
        )
        # `max_depth` counts levels of delegation *including this agent's own*, so
        # the budget left below this level is one less. The subtraction is the whole
        # of the setting's meaning and reads like an off-by-one, so: at `max_depth=1`
        # nothing is left, and every delegate is built without the capability - this
        # agent delegates and its delegates do not, which is what the field says and
        # what an author reads in the Builder. Without it, the documented behaviour
        # of `1` was what `0` did, and the default shipped one nested level of
        # delegation nobody asked for - which is the unbounded-cost path the whole
        # ceiling exists to close.
        depth_remaining = config.max_depth - 1
        subagents = await self._resolve_delegates(
            delegation,
            spec=spec,
            config=config,
            resources=resources,
            depth_remaining=depth_remaining,
            depth=0,
            ancestors=frozenset({agent.id}),
        )
        return _register_runtime(
            delegation,
            subagents,
            depth_remaining=depth_remaining,
            depth=0,
            dynamic=await self._dynamic_specialists(delegation, config),
        )

    async def _dynamic_specialists(
        self, delegation: _Delegation, config: SubagentsConfig
    ) -> DynamicSpecialists | None:
        """Whether one agent in the tree may invent specialists, and how it builds one.

        `None` for every agent whose author left `allow_dynamic` off, which is the
        default and is most of them - and then the delegation capability offers
        neither dynamic entry point at all, rather than two tools that can only
        refuse.

        This is where the setting is read, and the only place: the capability reads
        the *result* off `SubagentRuntime.dynamic`. Two readers would be two
        answers to "may this agent invent a specialist", and the one that mattered
        would be whichever ran later.
        """
        if not config.allow_dynamic:
            return None
        profiles = await self._model_catalog(delegation)
        return DynamicSpecialists(
            build=_dynamic_builder(delegation, profiles=profiles),
            allowed_models=tuple(profiles),
        )

    async def _model_catalog(self, delegation: _Delegation) -> Mapping[str, ModelRequestSpec]:
        """Every model a dynamic specialist may run on, resolved and keyed by label.

        Resolved rather than listed, because a specialist has to be *built* from
        inside a tool call, on a session the whole run shares - so the credential
        has to be out of the vault before the run starts, exactly as a pinned
        delegate's is. That is a query and an unseal per profile, which is why it
        happens only for an agent whose author asked for dynamic specialists and
        only once per run.

        The label is the handle, because it is what the Builder shows an author,
        what an organization's models are unique by, and therefore the only name a
        model can be given that a profile can be found from. A provider-qualified
        model id would be a second namespace, and one the model would be guessing
        at.

        Two consequences worth naming rather than leaving to be discovered. Every
        credential in the catalog is unsealed before the run starts, whether or not
        a specialist is ever invented - the price of the model being able to choose
        at all, and the reason this is not resolved for every agent. And it widens
        what a reviewed agent may run a specialist on to any of the organization's
        models, not only the one its author chose for itself; the run's own caps
        still bind, so what varies is the price of a request rather than the ceiling
        on the run. The whole catalog is the right scope because a model profile has
        no per-row grants to resolve - it is organization-scoped configuration, and
        `list_profiles` is scoped to the organization the run is in.

        A profile that no longer resolves is left out with a warning rather than
        failing the run - its key deleted (`BadRequestError`), or the row itself
        gone between this listing and this resolution (`NotFoundError`). The
        alternative is one misconfigured model in a catalog of ten stopping an agent
        that names none of it, which is the same reasoning `resolve` already applies
        to a fallback chain. The delegating agent's own profile is not at risk from
        this: it resolved before this method was reached, so the catalog holds at
        least it and can never come back empty.
        """
        if not delegation.profiles:
            for profile in await self.models.list_profiles(delegation.ctx):
                try:
                    delegation.profiles[profile.label] = await self.models.resolve(
                        delegation.ctx, profile_id=profile.id
                    )
                except (BadRequestError, NotFoundError):
                    logger.warning(
                        "model_profile_not_usable_for_dynamic_specialists",
                        extra={"profile_id": str(profile.id), "label": profile.label},
                    )
        return delegation.profiles

    async def _resolve_delegates(
        self,
        delegation: _Delegation,
        *,
        spec: AgentSpec,
        config: SubagentsConfig,
        resources: dict[str, Any],
        depth_remaining: int,
        depth: int,
        ancestors: frozenset[UUID],
    ) -> list[ResolvedSubagent]:
        """Every delegate one agent in the tree may address, resolved.

        `spec` and `config` belong to the agent that is *delegating* - the run's
        own at the top, a published delegate's one level down - which is what
        makes this one walk rather than two that drift apart. `ancestors` carries
        the agent ids already running above this point, `depth_remaining` how
        much further the tree may go, and `depth` how far in it already is - which
        is what a surface needs to nest a delegation panel under the right parent.

        Inline specialists come first only so the order is stable; the model
        addresses a delegate by name, and the name is refused if two share it.

        Delegation is never shared, whatever the share list says. Publish
        validation refuses the id (`_share_problems`), and this drops it again
        because a spec published before that rule existed is still stored and
        still runs: sharing it would copy this agent's binding onto a delegate
        that binds none, and `_delegation_config` would then read the *parent's*
        specialists, fan-out and `allow_dynamic` as if the delegate's author had
        chosen them.
        """
        share = set(config.share_with_delegates) - {DELEGATION_CAPABILITY_ID}
        shared = [
            binding for binding in spec.capabilities if binding.enabled and binding.id in share
        ]
        resolved: list[ResolvedSubagent] = []
        for specialist in config.inline:
            resolved.append(
                await self._resolve_specialist(
                    delegation,
                    specialist=specialist,
                    parent=spec,
                    shared=shared,
                    resources=resources,
                )
            )
        for ref in spec.subagents:
            resolved.append(
                await self._resolve_delegate(
                    delegation,
                    ref=ref,
                    shared=shared,
                    resources=resources,
                    depth_remaining=depth_remaining,
                    depth=depth,
                    ancestors=ancestors,
                )
            )
        _refuse_duplicate_names(resolved)
        return resolved

    async def _resolve_specialist(
        self,
        delegation: _Delegation,
        *,
        specialist: SpecialistSpec,
        parent: AgentSpec,
        shared: list[CapabilityBindingSpec],
        resources: dict[str, Any],
    ) -> ResolvedSubagent:
        """One inline specialist, built by the factory every agent goes through.

        `to_agent_spec` is what keeps "one spec type, one builder" true rather
        than aspirational: a specialist is a typed subset of `AgentSpec`, so the
        way to build one is to say which agent it is. It runs on the delegating
        agent's model profile when it names none, which is both the least
        surprising answer and the only one that works when the parent's profile is
        the only one the author chose.

        It resolves its **own** collections, skills and secrets. Delegation is
        stripped: a specialist does not delegate further - nesting is bounded for
        published delegates, which are reviewable - and a spec that bound the
        capability anyway would offer a tool with nothing behind it.

        `agent_id` and `agent_version_id` are left unset, which is what tells the
        recorder there is no agent to attribute a run row to. Its cost is the
        parent's, and the tool call in the transcript is the record.
        """
        ctx = delegation.ctx
        spec = _without_delegation(
            _with_shared(
                specialist.to_agent_spec(fallback_model_profile_id=parent.model_profile_id),
                shared,
            )
        )
        own_resources = await self._delegate_resources(
            ctx, spec, shared=shared, parent_resources=resources
        )
        return ResolvedSubagent(
            name=specialist.name,
            description=specialist.description,
            build=_delegate_builder(
                delegation,
                spec=spec,
                model=await self.models.resolve(ctx, profile_id=spec.model_profile_id),
                agent_id=delegation.agent_id,
                resources=own_resources,
                secrets=await self.secrets.resolve_for_bindings(ctx, _secret_ids(spec)),
                # A specialist has no MCP connections. They are
                # organization-scoped configuration, and reaching one through a
                # specialist nobody published is the wrong door - bind it on the
                # parent and share it.
                extra_toolsets=[],
            ),
            max_steps=specialist.max_steps,
            preferred_mode=specialist.preferred_mode,
            collection_names=tuple(own_resources["kb_collection_names"]),
        )

    async def _resolve_delegate(
        self,
        delegation: _Delegation,
        *,
        ref: SubagentRef,
        shared: list[CapabilityBindingSpec],
        resources: dict[str, Any],
        depth_remaining: int,
        depth: int,
        ancestors: frozenset[UUID],
    ) -> ResolvedSubagent:
        """One published delegate, on the version it is pinned to.

        The pin is loaded directly rather than through `get_runnable_spec`, and
        that is what pinning means: `get_runnable_spec` resolves an
        *environment*, so a delegate would otherwise follow the parent's, and the
        same published parent would run a different delegate in `dev` than in
        production with nothing recording that anything differed.

        Its name is the delegate's `slug`, which is the agent's one public
        handle: it is what a channel mention resolves, what the Builder shows the
        author beside the pin, and it is unique per organization by database
        constraint (`uq_agent_org_slug`). Slugifying the pinned spec's *name*
        instead would be a second handle for one concept - stable, but neither
        unique (two names can slugify alike, which the constraint would never
        have allowed) nor the name the author was shown, so instructions saying
        "delegate to research-bot" would address something the model was never
        offered. The row owns the slug: `save_draft` updates `name` and never
        `slug`, so it does not move when the agent is renamed either.

        `AGENTS_RUN` on the delegate was checked when the parent was published; a
        delegation is not a privilege boundary, and re-checking it per caller
        would make the same published agent work for one person and not another -
        so the row is read tenant-scoped rather than through the registry.

        Its **status** is another matter, and is checked. Archiving is this
        product's one take-out-of-service action: `get_runnable_spec` refuses a
        direct run of an archived agent and `_resolve_pins` refuses a pin to one
        at publish. An agent archived *after* a parent pinned it would otherwise
        keep answering as that parent's delegate indefinitely - the caller hardest
        to notice, and the one whose author has already been told the agent is
        retired. This is a lifecycle check on the delegate, not the per-caller
        permission re-check the paragraph above declines to do: it answers the
        same way for everyone who runs the parent.

        Raises:
            BadRequestError: If the delegate or its pinned version is gone or
                belongs to another organization, if the delegate has been
                archived, if the pin names a version of a different agent, or if
                this delegate is already running higher up the tree.
        """
        ctx = delegation.ctx
        if ref.agent_id in ancestors:
            # Pinning makes a cycle hard to reach by accident - a pin cannot name
            # a version published after it - but not impossible, and a cycle at
            # run time is a run that ends when the step limit does, having spent
            # everything up to it.
            raise BadRequestError(
                message="An agent cannot delegate to one already running in this run",
                details={"agent_id": str(ref.agent_id), "run_id": str(delegation.run.id)},
            )
        delegate = await agent_repo.get(self.db, ref.agent_id, organization_id=ctx.organization_id)
        if delegate is None:
            # Deleted since the parent was published, or never in this
            # organization. Refused rather than run from the pinned spec alone:
            # the row is where the handle the parent addresses it by lives, and a
            # delegate nobody can name is a delegate nobody can call.
            raise BadRequestError(
                message="A delegate this agent is pinned to no longer exists",
                details={"agent_id": str(ref.agent_id)},
            )
        if delegate.status == AgentStatus.ARCHIVED.value:
            # Named, unlike the two refusals around it: the pin was valid when it
            # was published and somebody has since retired the delegate, so the
            # fix is to unarchive it or republish the parent without it.
            raise BadRequestError(
                message=f"A delegate this agent is pinned to, '{delegate.name}', is archived",
                details={"agent_id": str(ref.agent_id), "slug": delegate.slug},
            )
        version = await agent_repo.get_version(
            self.db, ref.agent_version_id, organization_id=ctx.organization_id
        )
        if version is None or version.agent_id != ref.agent_id:
            # Never a fall back to the delegate's current version. The reason to
            # pin is that nothing changes without somebody deciding, and a silent
            # upgrade is worse than a refusal because nobody finds out.
            raise BadRequestError(
                message="The pinned version of one of this agent's delegates no longer exists",
                details={
                    "agent_id": str(ref.agent_id),
                    "agent_version_id": str(ref.agent_version_id),
                },
            )

        pinned = _with_shared(AgentSpec.model_validate(version.spec), shared)
        delegate_resources = await self._delegate_resources(
            ctx, pinned, shared=shared, parent_resources=resources
        )
        runnable = pinned
        nested_config = _delegation_config(pinned)
        if nested_config is not None:
            if depth_remaining > 0:
                # The more restrictive of the two ceilings, and the reason there are
                # two: what the tree has left below this level, and what *this
                # delegate's* author allowed. `depth_remaining - 1` alone took only
                # the root's, so a caller with `max_depth=3` handed a delegate whose
                # own spec says 1 enough budget for its delegates to delegate again
                # - the delegate's reviewed ceiling exceeded by a caller it has
                # never seen, and a ceiling a caller can widen is not a ceiling.
                # `max_depth - 1` because that field counts the configured agent's
                # own level, exactly as it does at the top of the tree in
                # `_subagent_runtime`; both are at least 0, since the field is
                # validated `ge=1`.
                nested_remaining = min(depth_remaining - 1, nested_config.max_depth - 1)
                delegate_resources[SUBAGENT_RUNTIME_RESOURCE] = _register_runtime(
                    delegation,
                    await self._resolve_delegates(
                        delegation,
                        spec=pinned,
                        config=nested_config,
                        resources=delegate_resources,
                        depth_remaining=nested_remaining,
                        depth=depth + 1,
                        ancestors=ancestors | {ref.agent_id},
                    ),
                    depth_remaining=nested_remaining,
                    depth=depth + 1,
                    # This delegate's own setting, not its caller's. A published
                    # delegate is reviewed on its own spec, so whether it may
                    # invent specialists is a question its author answered - and
                    # `nested_config` is that answer only because delegation is
                    # the one capability `_resolve_delegates` will not share.
                    # Shared, the parent's binding would land on a delegate that
                    # binds none and be read here as the delegate's own.
                    dynamic=await self._dynamic_specialists(delegation, nested_config),
                )
            else:
                # The bound. Built without the capability rather than with one
                # that refuses: see `_without_delegation`. Which also closes the
                # dynamic entry points - a delegate at the bound may not invent a
                # specialist either, because a specialist is a level like any
                # other.
                runnable = _without_delegation(pinned)

        model = await self.models.resolve(ctx, profile_id=runnable.model_profile_id)
        # Recorded now so the child's run row can name the model that answered.
        delegation.attribution[ref.agent_version_id] = model
        toolsets = await build_toolsets_for_agent(
            self.db,
            organization_id=ctx.organization_id,
            connection_ids=runnable.mcp_server_ids,
        )
        secrets = await self.secrets.resolve_for_bindings(ctx, _secret_ids(runnable))
        return ResolvedSubagent(
            name=delegate.slug,
            # What the parent's model reads before deciding to delegate. The name
            # is the fallback because a delegate with no description still has to
            # be describable - "helper" gets ignored, but an empty string is not
            # a choice the model can act on at all.
            description=pinned.description or pinned.name,
            build=_delegate_builder(
                delegation,
                spec=runnable,
                model=model,
                agent_id=ref.agent_id,
                resources=delegate_resources,
                secrets=secrets,
                extra_toolsets=toolsets,
            ),
            max_steps=runnable.max_steps,
            preferred_mode=ref.preferred_mode,
            agent_id=ref.agent_id,
            agent_version_id=ref.agent_version_id,
            # Beside the agent as well as inside its deps, because the library
            # replaces those deps with a clone of the parent's - see
            # `ResolvedSubagent.collection_names`.
            collection_names=tuple(delegate_resources["kb_collection_names"]),
        )

    async def _delegate_resources(
        self,
        ctx: AuthContext,
        spec: AgentSpec,
        *,
        shared: list[CapabilityBindingSpec],
        parent_resources: dict[str, Any],
    ) -> dict[str, Any]:
        """A resource dict of the delegate's own, resolved from the delegate's spec.

        A fresh dict every time, and never the caller's. `build_agent` reads
        `kb_collection_names` straight out of whatever it is given, and that dict
        is mutable and shared for the length of the run - so handing a delegate
        the parent's would silently grant it every collection the parent has, and
        a specialist is a tempting place to reach a collection nobody granted
        precisely because it does not look like an agent.

        What does travel is the state a shared capability's instance depends on.
        In practice that is one entry, the workspace backend, and it is the whole
        point of sharing `sandbox`: without it a delegate builds a workspace of
        its own and finds the file the parent wrote missing. `None` if the parent
        opened none, which the capability answers with an in-memory workspace
        exactly as it does for a preview.

        Two consequences worth stating, because both are silent. A delegate that
        binds `sandbox` itself *and* is shared the parent's gets its own tool
        configuration over the parent's session - sharing a workspace means
        sharing the files, and a delegate reading a different filesystem is the
        thing sharing exists to prevent. And a delegate that binds `sandbox`
        without being shared one gets the in-memory workspace, because no
        workspace is opened per delegate: only the run has one. Sharing is how a
        delegate reaches a durable workspace at all.
        """
        resources: dict[str, Any] = {
            "kb_collection_names": await self._collection_names(spec, ctx),
            "skills": await self.skills.resolve_for_agent(ctx, spec.skill_ids),
        }
        if any(binding.id == SANDBOX_CAPABILITY_ID for binding in shared):
            resources[WORKSPACE_BACKEND_RESOURCE] = parent_resources.get(WORKSPACE_BACKEND_RESOURCE)
        return resources

    @staticmethod
    def _delegation_recorder(
        *,
        run: AgentRun,
        attribution: Mapping[UUID, ModelRequestSpec],
        queued: list[RecordedDelegation],
    ) -> DelegationRecorder:
        """How a finished delegation becomes a run row of its own - eventually.

        **Nothing here touches the database, and that is the whole design.** The
        request's `AsyncSession` is shared by everything in the run and is not
        concurrency-safe, and two delegations can be in flight at once *in `sync`
        mode*: a `sync` delegation holds its own tool call, but pydantic-ai runs
        several tool calls from one model response concurrently, so a parent whose
        model emits two `task` calls in one step overlaps two of them without
        either being asynchronous - and `parallel_tool_calls` is unset by default,
        so that is the provider's decision, not the author's. Two inserts on that
        session at once do not produce a slow query; they corrupt the session and
        take the parent's run row and the conversation with it. `max_fanout` bounds
        how many delegations there are, not whether they overlap.

        So the delegation is *described* here and written by
        :meth:`_write_delegations` from the run's single terminal write. The id is
        allocated here so the return value still answers the question the surface
        asks it - which run history entry does this delegation panel link to - and
        the row it names appears when the run ends.

        Only a delegation to a *published* agent is recorded. An inline specialist
        has no agent to attribute a row to - it is not versioned, nothing else can
        reference it, and inventing an identity for it would create a second notion
        of "agent" that the permission model cannot see. Its cost is the parent's,
        and the tool call in the transcript is the record.

        What the row is for: the delegate's own monthly total, which is otherwise
        unanswerable, and the run history entry a delegation panel links to. It is
        deliberately *not* part of the organization's monthly total - the parent's
        row already contains these tokens, because a run has one ledger - and
        `agent_run_repo.sum_cost_since` is where that division lives.

        The span is the delegation's own, off the task handle: `started_at` when
        the delegate started and `ended_at` when it reached a terminal status,
        carried through :class:`DelegationOutcome`. Neither is the settlement
        instant, which for a background delegation is the poll that collected it -
        arbitrarily later than the delegate finished, and what once gave every
        background row a duration of zero ordered after work that preceded it
        (agenticos#191). A delegation that parked on an approval and resumed spans
        both turns: `started_at` is the first segment's, carried across the park the
        way its cost is, and `ended_at` the last (agenticos#245). A terminal handle
        that ended without a start - a delegate cancelled or failed before executing
        - falls back to that end, and a handle carrying neither falls back to `now`:
        both columns are non-null and a delegation with no recorded span still has
        to write one. (A refusal *before* a handle exists writes no row at all -
        :meth:`DelegationJournal.settle` returns first.) The parent's row remains the
        authority on the run's real span.
        """

        async def record(outcome: DelegationOutcome) -> UUID | None:
            if outcome.agent_id is None or outcome.agent_version_id is None:
                return None
            model = attribution.get(outcome.agent_version_id)
            if model is None:
                # A delegation to something this run never resolved. Nothing here
                # can say what it was or what it ran on, and a row attributed by
                # guess is worse than no row: it would count towards a real
                # agent's monthly total.
                logger.warning(
                    "delegation_outcome_for_unresolved_delegate",
                    extra={"run_id": str(run.id), "subagent": outcome.subagent},
                )
                return None

            # The delegation's own span, off the handle. `now` only when the handle
            # carried none - a delegation the library refused before it started a
            # task never ran, and both columns are non-null. `ended_at` falls back
            # to the start rather than to `now`, so a handle missing its end reads
            # as a zero-duration run at the right time, never a negative span.
            now = datetime.now(UTC)
            started_at = outcome.started_at or outcome.ended_at or now
            ended_at = outcome.ended_at or started_at
            delegated = RecordedDelegation(
                id=uuid4(),
                agent_id=outcome.agent_id,
                agent_version_id=outcome.agent_version_id,
                task_id=outcome.task_id,
                status=_DELEGATION_RUN_STATUS[outcome.status],
                model_label=model.label,
                provider=model.provider,
                secret_id=model.secret_id,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                cost_usd=outcome.cost_usd,
                # Whether *this delegation's* own requests were priced, not the
                # run's. A parent on a model `genai-prices` does not know makes the
                # parent's row a floor and says nothing about a delegate that ran
                # on a priced one.
                cost_is_partial=outcome.cost_is_partial,
                started_at=started_at,
                ended_at=ended_at,
                error=outcome.error,
            )
            # `append` is atomic under the GIL and this coroutine never awaits, so
            # two overlapping delegations cannot interleave inside it. That is the
            # property the queue buys: no lock, and no database.
            queued.append(delegated)
            return delegated.id

        return record

    async def _write_delegations(self, prepared: PreparedRun) -> None:
        """Write the rows the run's delegations left behind.

        Called from the same place the parent's row is written, which is the run's
        one terminal write and the only point at which the session is certainly
        not being shared with a tool call.

        Ordered after the parent's row on purpose: these rows carry
        `parent_run_id`, so the row they point at has to exist. It does - `_assemble`
        inserts it before the run starts - and the parent's own accounting is
        written first regardless, because that row is the authority for what the run
        cost while a child row is attribution.

        Never raises. It shares a `finally` with the parent's cost row, and a
        delegate deleted mid-run would otherwise turn a completed run into a
        storage error; the money is on the parent's row either way. The same
        reasoning, and the same guard, as :meth:`_propose_skill_changes`.

        Catching the exception is not enough on its own, which is why each row
        goes in inside its own savepoint. `agent_runs.agent_id` is a foreign key,
        so a delegate deleted between resolution and here makes the insert fail
        *in Postgres* - and an aborted transaction refuses every statement after
        it, including the commit. Guarding the loop with one `try` therefore
        destroyed exactly what it was written to protect: the parent's finished
        row and its cost rolled back with the child row that could not be
        written, and the delegations after it were never attempted. A savepoint
        per delegation loses that one row and nothing else.
        """
        parent = prepared.run
        for delegation in prepared.delegations:
            try:
                async with self.db.begin_nested():
                    await agent_run_repo.record_delegated_run(
                        self.db,
                        run_id=delegation.id,
                        organization_id=parent.organization_id,
                        agent_id=delegation.agent_id,
                        agent_version_id=delegation.agent_version_id,
                        parent_run_id=parent.id,
                        subagent_task_id=delegation.task_id,
                        # Read off the parent's row rather than kept on the queued
                        # record: they describe the run, not the delegation, and two
                        # copies of one fact drift.
                        user_id=parent.user_id,
                        conversation_id=parent.conversation_id,
                        # The binding that admitted the run admitted this too, so "what
                        # has this Slack app spent" keeps a delegated turn.
                        exposure_id=parent.exposure_id,
                        surface=parent.surface,
                        model_label=delegation.model_label,
                        provider=delegation.provider,
                        secret_id=delegation.secret_id,
                        status=delegation.status.value,
                        input_tokens=delegation.input_tokens,
                        output_tokens=delegation.output_tokens,
                        cost_usd=delegation.cost_usd,
                        cost_is_partial=delegation.cost_is_partial,
                        started_at=delegation.started_at,
                        ended_at=delegation.ended_at,
                        error=delegation.error,
                    )
            except Exception:
                logger.exception(
                    "delegation_row_not_written",
                    extra={"run_id": str(parent.id), "delegation_id": str(delegation.id)},
                )

    async def _write_approvals(self, prepared: PreparedRun) -> None:
        """Write the approval rows the run parked, once, off the shared session.

        The rows are *described* while the run runs and written here, from the
        run's terminal write - the one point at which the session is certainly not
        being shared with a concurrent tool call. Parking a call on the channel
        touches no database precisely so that two gated calls in one model step
        cannot race two inserts on the request's `AsyncSession` (agenticos#169);
        this is where that deferral is paid back. The loop is sequential, so the
        writes it makes do not race each other either.

        Unlike :meth:`_write_delegations`, a failure here is not swallowed. A
        delegation row is attribution - the money is on the parent's row whether or
        not the child row lands - but an approval row is what a resume reads to
        learn a call is waiting and what it was asked to approve. A parked run
        missing one of its rows cannot be continued for that call, so a write that
        fails has to fail the run rather than strand it awaiting a decision nothing
        recorded.

        The one failure that must *not* strand the run is a delegate deleted since
        its call was parked. `subagent_agent_id` is a `SET NULL` foreign key -
        deleting the delegate is meant to leave the record of what it was authorised
        to do, not take it down - but that only fires for a delete that lands after
        the row exists. Deferring the write widened the window to the whole run, so
        a delete that lands *before* it would instead make the insert violate the
        key and roll the parked run back. So the delegates still present are
        resolved and locked first (:func:`agent_repo.existing_ids_locked`), and an
        id whose agent is gone is written null - exactly what `SET NULL` would have
        done - keeping the row, the delegate's name and the resumable run.

        Each row is written with the id allocated when the call was parked, so it
        matches the `paused_state` that names it and the :class:`ParkedApproval` a
        surface already drew a card from. An unparked run leaves `requested` empty
        and this does nothing.
        """
        channel = prepared.approvals
        named = {p.subagent_agent_id for p in channel.requested if p.subagent_agent_id is not None}
        present = await agent_repo.existing_ids_locked(
            self.db, named, organization_id=channel.organization_id
        )
        for parked in channel.requested:
            await self.approvals.request(
                approval_id=parked.approval_id,
                organization_id=channel.organization_id,
                run_id=channel.run_id,
                agent_id=channel.agent_id,
                # The tool the model called, not the capability that owns it: the
                # approver is looking at "send_email", not at "email".
                tool_id=parked.tool_name,
                tool_args=parked.tool_args,
                subagent_name=parked.subagent,
                # Null when the delegate's agent was deleted after the call was
                # parked: the record of what it was authorised to do outlives it.
                subagent_agent_id=(
                    parked.subagent_agent_id if parked.subagent_agent_id in present else None
                ),
            )

    @staticmethod
    async def _collect_outbound(prepared: PreparedRun) -> None:
        """Read what the turn wrote, for a surface that can deliver it.

        Read for every run rather than only for the channels that use it, because
        the alternative is a flag threaded from three surfaces into `prepare` to
        decide whether a glob happens - and a glob of a workspace the process is
        already holding is cheaper than that plumbing. A surface with nowhere to
        put a file simply ignores the list.
        """
        if prepared.workspace is None:
            return
        delivered = await files_written(prepared.workspace.backend, prepared.workspace_at_start)
        prepared.outbound.extend(delivered.attachments)
        prepared.outbound_refused.extend(delivered.refused)

    async def _propose_skill_changes(self, prepared: PreparedRun) -> None:
        """Record what this run wrote to its skills, as something a person decides.

        Never raises. It is called from the same `finally` that records what the
        run cost, so a failure here - a name taken since, a workspace that cannot
        be listed - must not replace whatever actually happened to the run.

        The change is not applied. A skill is instructions every agent bound to it
        follows on every run, so an agent that could edit one directly could
        rewrite what another agent does, inside a conversation nobody is
        reviewing. `app/db/models/skill_proposal.py` has the rest of the
        reasoning.
        """
        workspace = prepared.workspace
        state = prepared.materialised_skills
        if workspace is None or state is None or prepared.ctx is None:
            return
        try:
            changes = await collect_changes(workspace.backend, state)
            if changes:
                await self.proposals.record(
                    prepared.ctx,
                    changes,
                    agent_id=prepared.agent.id,
                    conversation_id=prepared.run.conversation_id,
                )
        except Exception:
            logger.exception("skill_proposal_record_failed", extra={"run_id": str(prepared.run.id)})

    async def finish(
        self,
        prepared: PreparedRun,
        *,
        status: RunStatus,
        error: str | None = None,
        paused_state: PausedRunState | None = None,
        budget_scope: BudgetScope | None = None,
    ) -> AgentRun:
        """Record what the run consumed and how it ended.

        Called from a `finally` block by every surface: a crashed run still
        spent money, and a budget that ignores failures is not a budget. That is
        also what makes this the right place to read the **trace id**: it is
        reached however the run ended, and the run somebody most wants a trace for
        is the one that failed.

        The id is read here rather than accepted as a parameter, which is what it
        used to be. No caller ever passed one, so the write was guarded by a
        condition that was always false and `AgentRunRead.logfire_trace_id` -
        documented as a deep link into the trace - was null on every row ever
        written (#206).

        `paused_state` is what a parked run is resumed from. Passing nothing
        clears it, which is what makes a finished run un-resumable rather than
        replayable. What each surface supplies is its own position - the messages
        and the parked calls it can see; the delegation tree underneath is folded
        in here, from the stash on the prepared run, because a surface cannot see
        it and one that had to remember it would answer the next turn from a
        delegation nobody continued.

        `budget_scope` names which cap bound, for a `BUDGET_EXCEEDED` status. It
        is carried from the `except` clause that caught the refusal rather than
        re-derived here, because the alternative is matching a prefix on the
        error message - and it decides who gets mailed: an agent's cap is its
        author's to raise, the organization's is not.
        """
        # Both before the workspace closes, because a run-scoped one is released
        # by `close` and its files are gone afterwards.
        await self._collect_outbound(prepared)
        await self._propose_skill_changes(prepared)

        # Before the run row is written, so a workspace flush that fails cannot
        # leave the run un-finished, and after the run has certainly stopped
        # using it. `close` never raises; it logs.
        await self.workspaces.close(prepared.workspace)

        # The approval rows the run parked, written here rather than while it ran:
        # parking on the channel is deferred off the shared session so two gated
        # calls in one model step cannot race two inserts (agenticos#169), and this
        # is where the deferral is paid back. Before the parent's terminal write,
        # so the rows the `paused_state` names exist by the time it is stored.
        await self._write_approvals(prepared)

        parked = None if paused_state is None else self._parked_tree(prepared, paused_state)
        ledger = prepared.built.ledger
        finished = await agent_run_repo.finish_run(
            self.db,
            run=prepared.run,
            status=status.value,
            input_tokens=ledger.input_tokens,
            output_tokens=ledger.output_tokens,
            cost_usd=ledger.total_usd,
            cost_is_partial=ledger.has_unpriced_models,
            ended_at=datetime.now(UTC),
            error=error,
            logfire_trace_id=current_trace_id(),
            paused_state=None if parked is None else parked.model_dump(mode="json"),
        )
        # After the parent's row and on every path out of the run, for the reason
        # the parent's row is written on every path: a delegation that spent money
        # and recorded nothing is the hole a cancellation would otherwise open.
        await self._write_delegations(prepared)
        # Guarded, because `finish` is called from a `finally` block: an
        # exception raised while telling somebody about a failed run would
        # replace the failure itself, and the operator would debug the mail
        # server instead of the run.
        try:
            await self._notify(
                finished,
                agent=prepared.agent,
                spec=prepared.spec,
                status=status,
                error=error,
                budget_scope=budget_scope,
            )
        except Exception:
            logger.exception("run_notification_failed", extra={"run_id": str(finished.id)})
        return finished

    @staticmethod
    def _parked_tree(prepared: PreparedRun, paused_state: PausedRunState) -> PausedRunState:
        """The parked state a surface reported, plus the delegations underneath it.

        A surface knows its own agent's position and nothing about the tree below
        it: a delegation is a tool call named `task` that either answers or does
        not. So the frames come from the run's stash, and which agent each parked
        approval belongs to comes from the channel that wrote the rows - both of
        which live on the prepared run, and neither of which any surface has to
        remember.

        The alternative was a second argument on every `finish` call, and the two
        surfaces that park a run are the two that would have to agree about it
        forever. One of them would eventually not, and the failure is a resumed run
        that delegates again from nothing and answers a question nobody asked.

        The kept specialists come from the same stash, snapshotted by the delegation
        capability's `wrap_run` when the run ended and keyed by the `task` call each
        level was delegated from. The run's own agent's (`None`) go flat on
        `dynamic_specialists`; a nested delegate's ride on its own `DelegationFrame`,
        which is what carries them across a park too (agenticos#254, agenticos#175).
        """
        return paused_state.model_copy(
            update={
                "delegated_approvals": {
                    str(parked.approval_id): parked.task_id
                    for parked in prepared.approvals.requested
                    if parked.task_id is not None
                },
                "delegations": _delegation_frames(prepared.stash.parked, prepared.stash.registered),
                "dynamic_specialists": [
                    DynamicSpecialistFrame(
                        name=specialist.name,
                        description=specialist.description,
                        instructions=specialist.instructions,
                        model=specialist.model,
                    )
                    for specialist in prepared.stash.registered.get(None, [])
                ],
            }
        )

    async def _notify(
        self,
        run: AgentRun,
        *,
        agent: Agent,
        spec: AgentSpec,
        status: RunStatus,
        error: str | None,
        budget_scope: BudgetScope | None,
    ) -> None:
        """Tell somebody, when the run ended in a way nobody is watching for.

        Here rather than at the two places that raise, because this is where
        every surface converges and where the fact is already durable: a person
        told about a budget breach that the transaction then rolled back would
        go looking for a run that does not exist.

        A chat user watching the stream is told twice - once on screen, once by
        email - and that is the right trade: the alternative is guessing from
        the surface whether anybody was looking, and being wrong in the
        direction of silence.
        """
        notifications = NotificationService(self.db)
        if status is RunStatus.BUDGET_EXCEEDED:
            await notifications.budget_exceeded(
                run,
                agent=agent,
                spec=spec,
                reason=error or "A spending limit was reached.",
                # An agent's own cap unless the refusal said otherwise. A
                # `BUDGET_EXCEEDED` row with no scope recorded predates this
                # being carried, and the agent's audience is the narrower of the
                # two - so an unknown scope tells fewer people rather than
                # mailing the whole administration about somebody's draft.
                scope=budget_scope or BudgetScope.AGENT,
            )
        elif status is RunStatus.AWAITING_APPROVAL:
            approvals = await agent_run_repo.list_approvals_for_run(
                self.db, run_id=run.id, organization_id=run.organization_id
            )
            pending = [
                approval.tool_id
                for approval in approvals
                if approval.status == ApprovalStatus.PENDING.value
            ]
            await notifications.approval_requested(run, agent=agent, spec=spec, tools=pending)

    async def execute(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        prompt: str,
        *,
        said: str | None = None,
        surface: RunSurface = RunSurface.API,
        conversation_id: UUID | None = None,
        channel_key: str | None = None,
        channel_directory: ChannelDirectory | None = None,
        message_history: list[Any] | None = None,
        exposure: AgentExposure | None = None,
        environment_id: UUID | None = None,
        attachments: list[ChatFile] | None = None,
        outbound: list[OutgoingAttachment] | None = None,
        outbound_refused: list[str] | None = None,
        tool_calls: list[RecordedToolCall] | None = None,
        stream: RunStream | None = None,
    ) -> tuple[str, AgentRun]:
        """Run an agent to completion and return its answer.

        The non-streaming path, used by the API and chat channels. Surfaces that
        stream call :meth:`prepare` and :meth:`finish` around their own loop.

        `environment_id` runs the version that environment pins - the API's way
        of exercising a dev environment before promoting it.

        `attachments` are files that arrived with the message. They are routed
        here rather than by the caller because where an attachment *goes* depends
        on whether the agent has a workspace, and only `prepare` knows that - the
        same reason the streaming path routes them after preparing rather than
        before. They are also linked to the turn they arrived with, so a file
        posted in a channel is a file in the transcript rather than a sentence
        about one.

        `said` is what the person actually wrote, when `prompt` is something this
        caller assembled around it - a widget's placement note, a channel's
        restored slash. It is what goes in the transcript; `prompt` is what goes
        to the model. Defaults to `prompt`, which is right for every surface that
        assembles nothing.

        `outbound` and `outbound_refused` are filled with what the agent produced
        and what a reply cannot carry. Lists the caller passes in rather than a
        third return value: the workspace is closed before this returns - a
        run-scoped one is released outright - so a caller cannot read it
        afterwards, and every other caller of this method would have to unpack a
        tuple it has no use for.

        An empty answer with the run in `awaiting_approval` means a tool call
        is parked; the caller shows the queue rather than an answer.
        """
        prepared = await self.prepare(
            ctx,
            agent_id,
            surface=surface,
            conversation_id=conversation_id,
            channel_key=channel_key,
            channel_directory=channel_directory,
            exposure=exposure,
            environment_id=environment_id,
        )
        # `str | list[Any]`, not `str`: an attached image is folded in as
        # `BinaryContent` beside the text, and narrowing that back to a string
        # would hand the model a path where it should have been handed a picture.
        assembled: str | list[Any] = prompt
        if attachments:
            assembled = await AttachmentRouter(
                prepared.workspace.backend if prepared.workspace is not None else None
            ).build_prompt(prompt, attachments)
        segment = await self._run(
            prepared,
            user_prompt=assembled,
            # The prompt as it was *given*, not as it was assembled: the files
            # are recorded as rows below, and a surface that prepends its own
            # note passes what the person typed.
            said=prompt if said is None else said,
            attachments=attachments or (),
            message_history=message_history,
            deferred_tool_results=None,
            stream=stream,
        )
        if outbound is not None:
            outbound.extend(prepared.outbound)
        if outbound_refused is not None:
            outbound_refused.extend(prepared.outbound_refused)
        # Handed back the same way as the files: a surface that can draw a chart
        # needs what the turn called, and reading it off the row afterwards is
        # not open to a channel run, which writes no messages (#205).
        if tool_calls is not None:
            tool_calls.extend(segment.tool_calls)
        return segment.output, segment.run

    async def parked_calls(self, ctx: AuthContext, run: AgentRun) -> list[ParkedCall]:
        """What this run is waiting on a decision for, right now.

        Read back off the row rather than returned from the run that parked it,
        because the caller that needs it is the *resume*: a continuation runs the
        agent, and the agent can reach a second gated call and park again. A client
        told only `status` was handed "still awaiting approval" and nothing to
        approve, so the run could not be finished from the surface that started it -
        the continuation runs over HTTP rather than the socket a conversation
        streams, so there is no frame carrying the new calls either.

        `tool_call_id` comes from the run's own paused state, which maps approval id
        to the call it parked; the approval row does not carry one. Null where a run
        was parked before that map was stored, which is a step a surface cannot mark
        rather than a call it cannot decide.
        """
        if run.status != "awaiting_approval":
            return []
        approvals = await agent_run_repo.list_approvals_for_run(
            self.db, run_id=run.id, organization_id=ctx.organization_id
        )
        state = run.paused_state or {}
        by_approval = state.get("tool_call_ids", {}) if isinstance(state, dict) else {}
        return [
            ParkedCall(
                id=approval.id,
                tool_call_id=by_approval.get(str(approval.id)),
                tool_name=approval.tool_id,
                tool_args=approval.tool_args or {},
            )
            for approval in approvals
            if approval.status == "pending"
        ]

    async def resume(self, ctx: AuthContext, run_id: UUID) -> RunSegment:
        """Continue a parked run now that its tool calls have been decided.

        Runs the *version the run was parked on*, not whatever is published now:
        the stored conversation was produced by that spec, and continuing it
        under a different one would answer a question nobody asked.

        A run parked *inside a delegation* is continued the same way one level
        further in: the delegate's own conversation and the verdicts on the calls it
        stopped on go into the stash, the replayed `task` call finds them there, and
        the delegate carries on from where it was rather than starting again. That
        is the only shape in which the person's decision applies to the call they
        were shown - the parent parks on `task`, so a re-run delegation would be
        handed an approval naming a tool call it never asks about, and the model
        would be free to call something else.

        A continuation that cannot be built leaves the run parked. The version's
        spec is fetched and assembled *before* the row leaves the queue, so a
        secret deleted since the park, a removed model profile or a capability
        dropped in a deploy refuses this attempt rather than the run: the
        decision stands, and resuming works again once the spec does.

        Returns:
            The continuation as a :class:`RunSegment` - what it answered, the row,
            and **what it called on the way there**. The last of those is the only
            record a caller gets: the continuation runs over HTTP rather than the
            socket a conversation streams, so nothing announces its tool calls, and
            a surface handed just the answer drew a turn in which approving a call
            was followed by a second approval request for work it could not show.

        Raises:
            NotFoundError: If the run is not in this organization.
            BadRequestError: If the run is not parked, has no stored state, or
                still has a decision outstanding. All three mean the caller is
                about to replay something it should not. Also if the spec it was
                parked on can no longer be built - see above.
        """
        run = await agent_run_repo.claim_parked_run(
            self.db, run_id, organization_id=ctx.organization_id
        )
        if run is None:
            raise NotFoundError(message="Run not found", details={"run_id": str(run_id)})
        if run.status != RunStatus.AWAITING_APPROVAL.value:
            raise BadRequestError(
                message="This run is not waiting for approval",
                details={"run_id": str(run_id), "status": run.status},
            )
        if run.paused_state is None:
            raise BadRequestError(
                message="This run was parked without the state needed to continue it",
                details={"run_id": str(run_id)},
            )
        state = PausedRunState.model_validate(run.paused_state)

        decided, plan = await self._decisions(ctx, run=run, state=state)

        agent, spec = await self._parked_spec(ctx, run)
        # The continuation traces where the original did: the environment that
        # routed the run still owns its observability.
        spec = await self._with_environment_observability(
            ctx, spec, environment_id=run.environment_id
        )
        # The binding that admitted the run enriches its spec two ways `prepare`
        # does: the platform's own formatting prompt and the `channel_tools`
        # capability. A continuation that skipped them would answer a channel
        # approval without channel tools and formatted for the wrong platform
        # (#513 was S14 - "an approval is answered in the thread that asked for
        # it"). The exposure id is stamped on the row, so it can be reloaded and
        # the same two helpers run. The directory stays `None`: an
        # approve-then-resume has no live channel handle, and
        # `_with_channel_tools` still restores the binding for wherever one is.
        exposure = (
            await agent_exposure_repo.get(
                self.db, run.exposure_id, organization_id=ctx.organization_id
            )
            if run.exposure_id is not None
            else None
        )
        spec = await _with_exposure_prompt(spec, exposure)
        spec = _with_channel_tools(spec, exposure)
        prepared = await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=run,
            surface=RunSurface(run.surface),
            conversation_id=run.conversation_id,
            user_name=None,
            extra_toolsets=None,
            # A resumed run reuses its row, and the binding is reloaded above to
            # re-enrich the spec, so there is nothing left for `_assemble` to
            # stamp from the exposure here.
            exposure=None,
            decided=decided,
            resuming=plan.delegations,
            already_spent=plan.spent,
            already_started=plan.started,
            # The specialists each level kept before it parked, rebuilt into that
            # level's fresh registry before the replay so `task` reaches them again.
            # `None` is the run's own agent, off the flat state list; a nested
            # delegate's come from its `DelegationFrame`, keyed by its `task` call
            # (agenticos#254). One map, so `_assemble` seeds every level in one pass.
            specialists={
                None: [
                    RegisteredSpecialist(
                        name=frame.name,
                        description=frame.description,
                        instructions=frame.instructions,
                        model=frame.model,
                    )
                    for frame in state.dynamic_specialists
                ],
                **plan.specialists,
            },
        )
        prepared.built.ledger.book(_spend_already_booked(run))

        # Out of the queue once the build has succeeded, and before anything is
        # replayed. Two different things keep two different resumes out, which is
        # why this line sits between the build and the run rather than at either
        # end:
        #
        # A resume arriving *while this one is still building* waits at
        # `claim_parked_run` - the row lock is held for the whole transaction -
        # and then reads the status written here, so building first widens no
        # window. A resume arriving *after this transaction commits* has no lock
        # to wait on, and what refuses it is finding the run no longer parked; so
        # the status has to change before the tool call is replayed, not after.
        #
        # It is written last because a build refuses for reasons that have
        # nothing to do with this run: a secret a binding names deleted since the
        # park, a model profile removed, a capability dropped in a deploy, an
        # MCP connection unshared. Flipping the row first left every one of those
        # with a run stuck in `running`, which `claim_parked_run` never hands out
        # again - a decision a person made, recorded against work that cannot
        # continue. Nothing above has touched the row, so the run is still parked
        # and still resumable, and no failure path can commit a status that was
        # never written.
        await agent_run_repo.mark_running(self.db, run=run)

        try:
            return await self._run(
                prepared,
                # No new prompt: the conversation resumes at the tool call it stopped
                # on, and inventing a user turn here would put words in their mouth.
                user_prompt=None,
                said=None,
                message_history=ModelMessagesTypeAdapter.validate_python(state.messages),
                deferred_tool_results=plan.results,
            )
        except Exception as exc:
            # The continuation raised. `_run` has recorded the run terminal and
            # committed before re-raising, so this re-raise carries the failure to
            # the caller rather than swallowing it - but it also carries the
            # recorded status, which the raising path used to throw away. The resume
            # answer is where a web-chat surface learns a delegate's outcome (the
            # continuation ran over HTTP, not the socket the conversation streams);
            # without the status the surface leaves an `awaiting_approval` panel
            # waiting on a decision already spent, and the run cannot be resumed
            # again because it is now terminal (agenticos#262). A build refusal
            # raised *before* `_run` leaves the run parked and is retryable, so it
            # is deliberately outside this `try` - it must keep surfacing as itself.
            # `CancelledError` is a `BaseException` and not caught: over HTTP it
            # means the request itself went away, so there is nobody to hand a
            # status to, and catching it would break the cancellation it signals.
            raise RunExecutionError(details={"run_id": str(run.id), "status": run.status}) from exc

    async def _decisions(
        self, ctx: AuthContext, *, run: AgentRun, state: PausedRunState
    ) -> tuple[dict[str, ApprovalDecision], _ResumePlan]:
        """The verdicts on this run's parked calls, and where each one has to arrive.

        Two products, because a run's parked calls do not all belong to the same
        agent. The verdicts are flat and keyed by tool call - every approval gate in
        the tree reads the one channel, and a tool call id is unique to the agent
        that made it - while the *replay* is per agent: Pydantic AI refuses a resume
        whose results name a call the replayed response does not contain, so a
        delegate's parked call handed to the parent's replay fails the whole
        continuation. That is what a run parked inside a delegate used to do.

        Raises:
            BadRequestError: If any of them is still pending. Resuming with a
                decision outstanding would drop that call silently.
        """
        approvals = await agent_run_repo.list_approvals_for_run(
            self.db, run_id=run.id, organization_id=ctx.organization_id
        )
        undecided = [a for a in approvals if a.status == ApprovalStatus.PENDING.value]
        if undecided:
            raise BadRequestError(
                message=f"{len(undecided)} tool call(s) on this run are still awaiting a decision",
                details={"run_id": str(run.id), "pending": [str(a.id) for a in undecided]},
            )

        decided: dict[str, ApprovalDecision] = {}
        approved_args: dict[str, dict[str, Any]] = {}
        for approval in approvals:
            tool_call_id = state.tool_call_ids.get(str(approval.id))
            if tool_call_id is None:
                # Decided during an earlier park of the same run and already
                # replayed. Answering it again would repeat the side effect.
                continue
            decided[tool_call_id] = (
                ApprovalGranted(tool_args=approval.tool_args)
                if approval.status == ApprovalStatus.APPROVED.value
                else ApprovalRejected(note=approval.note)
            )
            # "Approved" here means "let this call reach the tool pipeline", not
            # "do it": the gate is the only place allowed to decide that, and it
            # reads the verdict above. Denying here instead would give refusals
            # two sources of truth.
            approved_args[tool_call_id] = approval.tool_args
        return decided, _resume_plan(state, approved_args)

    async def _with_environment_observability(
        self, ctx: AuthContext, spec: AgentSpec, *, environment_id: UUID | None
    ) -> AgentSpec:
        """The spec, with the environment's tracing choices folded in.

        An environment can point its runs at their own Logfire project - the
        client's production traces in the client's project, dev noise in the
        operator's. The token and service name fall through to the spec's own
        block field by field; the Logfire environment tag is always the
        environment's *name*, never configured separately, so the tag and the
        environment cannot disagree. A run with no token from either source
        stays untraced rather than tagged into nowhere.
        """
        if environment_id is None:
            return spec
        environment = await agent_environment_repo.get(
            self.db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None:
            return spec
        base = spec.observability
        token_secret_id = environment.logfire_token_secret_id or (
            base.token_secret_id if base else None
        )
        if token_secret_id is None:
            return spec
        merged = ObservabilitySpec(
            token_secret_id=token_secret_id,
            service_name=environment.service_name or (base.service_name if base else None),
            environment=environment.name,
        )
        return spec.model_copy(update={"observability": merged})

    async def _parked_spec(self, ctx: AuthContext, run: AgentRun) -> tuple[Agent, AgentSpec]:
        """The agent and the exact spec version this run was executing.

        Raises:
            BadRequestError: If the version is gone. A run cannot be continued
                on a guess about what it was running.
        """
        agent = await self.registry.get(ctx, run.agent_id, perm=Perm.AGENTS_RUN)
        version = (
            None
            if run.agent_version_id is None
            else await agent_repo.get_version(
                self.db, run.agent_version_id, organization_id=ctx.organization_id
            )
        )
        if version is None:
            raise BadRequestError(
                message="The agent version this run was parked on no longer exists",
                details={"run_id": str(run.id)},
            )
        return agent, AgentSpec.model_validate(version.spec)

    @staticmethod
    async def _answer(
        prepared: PreparedRun,
        *,
        user_prompt: str | list[Any] | None,
        message_history: list[Any] | None,
        deferred_tool_results: DeferredToolResults | None,
        stream: RunStream | None,
    ) -> AgentRunResult[Any]:
        """One turn, streamed if the surface can show one arriving.

        Both halves settle through the same `_run` around this call - the same
        usage, the same budget stop, the same transcript row - so a channel that
        watches an answer being written is metered identically to an HTTP caller
        that waits for it. The alternative was a second copy of the settle path,
        which is how the streaming chat came to bill nothing for a year
        (agenticos#16).

        `deferred_tool_results` wins over `stream`: `iterate()` cannot carry
        them, and a resumed run is a run somebody already waited for. It resumes
        the way it always has, and the surface gets its answer at the end.
        """
        if stream is None or deferred_tool_results is not None:
            return await prepared.execute(
                user_prompt,
                message_history=message_history,
                deferred_tool_results=deferred_tool_results,
            )
        async with prepared.iterate(user_prompt, message_history=message_history) as agent_run:
            await stream(agent_run)
        return _outcome(agent_run)

    async def _run(
        self,
        prepared: PreparedRun,
        *,
        user_prompt: str | list[Any] | None,
        said: str | None,
        attachments: Sequence[ChatFile] = (),
        message_history: list[Any] | None,
        deferred_tool_results: DeferredToolResults | None,
        stream: RunStream | None = None,
    ) -> RunSegment:
        """Execute the agent and account for it, however it ends.

        `user_prompt` is what the model is given and `said` is what the person
        wrote, which are not the same string on any surface that assembles one:
        `AttachmentRouter` appends a briefing about each file, and an embedded
        widget prepends the operator's placement note. Recording the assembled
        version put the model's own briefing in the transcript as the user's words.
        `said` is `None` on a resume, where nothing new was said at all.

        The one place a run is executed, so a parked call, a budget stop, a
        cancellation and a crash are all recorded the same way whether the run is
        new or resumed.

        **It is also where the transcript is written, for the same reason.** Every
        surface that does not stream reaches this method, and every one of them
        used to be responsible for recording what the run said: the embedded
        widget, a channel mention, the HTTP API and every resumed run recorded
        nothing at all, so an organization was billed for answers no row
        described. A thing four surfaces have to remember is a thing the fifth
        will not. The streaming chat does not come through here and keeps writing
        its own, because it has events to attach and a socket to answer on.

        **A cancellation is one of those endings, and it needs both halves.**
        `asyncio.CancelledError` is a `BaseException`, so it reaches neither
        handler below on its own: the status stayed at its initial `FAILED` with
        no error text, which sends an operator filtering run history for problems
        through runs that were working correctly and were stopped - exactly what
        `BUDGET_EXCEEDED` was given its own status to avoid. And the commit is not
        optional either. `get_db_session` commits on a clean exit, and a
        propagating `BaseException` is not one, so the terminal write was rolled
        back and the row stayed `RUNNING` for ever - taking the delegation rows
        :meth:`finish` queues with it, which is how a delegate that spent real
        money came to be recorded nowhere. Committing here is what makes the row
        survive; re-raising is what lets whoever cancelled see it happen.
        """
        status = RunStatus.FAILED
        error: str | None = None
        output = ""
        paused: PausedRunState | None = None
        budget_scope: BudgetScope | None = None
        called: list[RecordedToolCall] = []
        settled: dict[str, str] = {}
        try:
            result = await self._answer(
                prepared,
                user_prompt=user_prompt,
                message_history=message_history,
                deferred_tool_results=deferred_tool_results,
                stream=stream,
            )
            # `new_messages`, not `all_messages`: a resumed run is handed
            # everything up to the park as history, and the wider list would
            # write the first attempt's calls again under the same run.
            new_messages = result.new_messages()
            called = tool_calls_in(new_messages)
            # And what the *inherited* calls returned. On a resume the approved
            # call was made by the previous execution, so only its return is new -
            # `tool_calls_in` has nothing to hang it on and drops it, which left
            # the one call a person reviewed as the one call with no recorded
            # output anywhere (agenticos#506).
            settled = settled_calls_in(new_messages)
            if isinstance(result.output, DeferredToolRequests):
                paused = PausedRunState(
                    messages=ModelMessagesTypeAdapter.dump_python(
                        result.all_messages(), mode="json"
                    ),
                    tool_call_ids=prepared.approvals.parked,
                )
                status = RunStatus.AWAITING_APPROVAL
                logger.info(
                    "Run %s parked on %d approval(s)", prepared.run.id, len(paused.tool_call_ids)
                )
            else:
                output = result.output
                status = RunStatus.COMPLETED
        except asyncio.CancelledError:
            # The caller went away, or a delegation this run sits under was
            # stopped. Cancelled is not failed, and the tokens spent up to here
            # were still spent.
            status = RunStatus.CANCELLED
            logger.info("Run %s cancelled", prepared.run.id)
            raise
        except BudgetExceeded as exc:
            # Not a malfunction - the platform working. Recorded separately so
            # an operator filtering for problems does not wade through it.
            status = RunStatus.BUDGET_EXCEEDED
            error = str(exc)
            budget_scope = exc.scope
            logger.info("Run %s stopped by budget: %s", prepared.run.id, exc)
        except Exception as exc:
            error = run_failure_summary(exc)
            logger.exception("Agent run %s failed", prepared.run.id)
            raise
        finally:
            await self.finish(
                prepared,
                status=status,
                error=error,
                paused_state=paused,
                budget_scope=budget_scope,
            )
            # In the `finally`, so a run that failed, parked or was stopped still
            # says what was asked and what it managed to do. Those are the runs
            # somebody opens.
            await self.transcript.record(
                prepared.run,
                prompt=said,
                answer=output,
                attachments=attachments,
                tool_calls=called,
                settled=settled,
                # So the step the run stopped on reads "awaiting approval" when
                # the conversation is read back, not as a call that ran (#601).
                parked=frozenset(paused.tool_call_ids.values()) if paused else frozenset(),
                model_label=prepared.built.model_label,
            )
            # Committed here rather than left to the session context: that exit
            # rolls back on any exception, and cancellation never reaches it at
            # all, since `CancelledError` is not an `Exception`. A run that
            # failed, was stopped or ran out of budget still spent money, and a
            # run missing from history is a run nobody is accountable for.
            await self.db.commit()

        return RunSegment(output=output, run=prepared.run, tool_calls=called, settled=settled)

    async def list_runs(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID | None = None,
        parent_run_id: UUID | None = None,
        include_delegations: bool = False,
        filters: RunFilters | None = None,
        order_by: RunOrder = RunOrder.STARTED_AT,
        descending: bool = True,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentRun], int]:
        """Runs for the organization, newest first, optionally for one agent.

        Scoped to the caller's organization here rather than in the route, so
        run history is read through the same tenant boundary the rest of this
        service enforces - there is no second place a listing could widen.

        Top-level runs only by default: a delegated row and a run somebody
        started are never summed down one column, because a parent's cost
        already contains its children's. `parent_run_id` lists one run's own
        delegations; `include_delegations` keeps them in an agent's own history.

        `filters` is the caller's narrowing, and the tenant clause is applied
        here regardless of it: a filter can only ever shrink what this returns,
        never reach outside the organization.

        `filters.statuses` narrows to a set of outcomes and composes with all
        three. The route validates the words against `RunStatus` before they
        reach here, so an unknown one is refused by name rather than becoming a
        filter that silently matches nothing. It travels *inside* `RunFilters`
        rather than beside it, because `conditions()` is what the page query and
        the count query share - a status clause applied on its own is the one way
        those two could come to describe different rows.
        """
        return await agent_run_repo.list_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            parent_run_id=parent_run_id,
            include_delegations=include_delegations,
            filters=filters,
            order_by=order_by,
            descending=descending,
            skip=skip,
            limit=limit,
        )

    async def down_rated_run_ids(self, ctx: AuthContext, run_ids: Sequence[UUID]) -> set[UUID]:
        """Which of these runs an assistant answer was rated down on.

        The marker run history draws its 👎 from, computed for a whole page at
        once and again for a single run read - the same answer either way.
        Scoped to the caller's organization, like every read in this service, so
        the marker cannot be a place a listing widens past its tenant boundary.
        """
        return await agent_run_repo.down_rated_run_ids(
            self.db, organization_id=ctx.organization_id, run_ids=run_ids
        )

    async def get_run(self, ctx: AuthContext, run_id: UUID) -> AgentRun:
        """One run in the caller's organization.

        A run belonging to another organization reads as absent, not forbidden:
        the repository filters on `organization_id`, so a foreign id returns no
        row and this raises the same `NotFoundError` an unknown id would - a
        tenant cannot tell a neighbour's run from one that never existed.
        """
        run = await agent_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if run is None:
            raise NotFoundError(message="Run not found", details={"run_id": str(run_id)})
        return run

    async def get_run_transcript(
        self, ctx: AuthContext, run_id: UUID, *, skip: int = 0, limit: int = 100
    ) -> tuple[AgentRun, list[Message], int]:
        """One run, and the turns it produced - authorized, not owned.

        Reading a run is the organization's right rather than its starter's: a
        colleague holding `runs:view` reads a run somebody else began, which is
        the whole reason this is a route of its own and not a filter on the
        conversation endpoint. That endpoint stays scoped to the owner, so
        widening *it* to reach a colleague's run would widen who can read the
        private thread the run sits in.

        The two refusals are ordered so that the first cannot be used to defeat
        the second. Existence is resolved against the organization *before* the
        permission is read, so a run in another tenant reads as absent - the same
        `NotFoundError` an id that never existed raises, down to its `details` -
        rather than as forbidden, which would confirm the id to a stranger. Only
        once the run is known to be the caller's organization's does a missing
        `runs:view` become a 403: a refusal that necessarily tells a member the
        run exists, and only ever reaches a member.

        A run with no conversation has no transcript by construction - the runner
        never writes a turn for one (:meth:`TranscriptService.record` returns at
        once when `conversation_id` is `None`) - so its emptiness is reported
        through `run.conversation_id` being `None`, and the message read is
        skipped rather than run to confirm a certainty.

        Returns:
            The run, its turns oldest-first, and the total number of them - the
            last so a paged read still knows the size of the whole.

        Raises:
            NotFoundError: The run is not in the caller's organization - whether
                it belongs to another tenant or to nobody.
            AuthorizationError: The caller's organization holds the run but the
                caller does not hold `runs:view`.
        """
        run = await agent_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        if run is None:
            raise NotFoundError(message="Run not found", details={"run_id": str(run_id)})
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Insufficient permissions",
                details={"required": [Perm.RUNS_VIEW.value], "run_id": str(run_id)},
            )
        if run.conversation_id is None:
            return run, [], 0
        messages = await conversation_repo.get_messages_by_run(
            self.db, run.id, skip=skip, limit=limit, include_tool_calls=True
        )
        total = await conversation_repo.count_messages_by_run(self.db, run.id)
        return run, messages, total

    async def transcript_ratings(
        self, ctx: AuthContext, message_ids: list[UUID]
    ) -> dict[UUID, dict[str, Any]]:
        """Per-turn rating detail for a run transcript, batched.

        The run-detail feedback panel reads three things off each turn, and this
        gathers all three in one query each rather than one per message: a
        transcript is read a page at a time, and a per-row lookup would turn a
        page into a page of round trips.

        - `user_rating` is the reading caller's own thumb - `1`, `-1`, or absent.
          Usually absent here: a transcript is read by whoever holds `runs:view`,
          not by whoever the run ran as. A caller with no user behind it at all (a
          service-to-service key) has no own thumb, so that lookup is skipped
          rather than asked with a null id.
        - `rating_count` is how the organization rated the turn, likes and
          dislikes, which is what lets the panel mark a turn nobody-but-me
          objected to.
        - `rating_comment` is the most recent down rating's comment, or absent.
          The panel shows "what people said was wrong", so an up rating's note is
          not it, and when more than one person objected the latest word is shown.

        Every id in `message_ids` gets an entry, so a caller can attach the result
        to each turn without a membership test; a turn nobody rated maps to three
        empty answers, which is how a plain turn stays indistinguishable from a
        rated one until somebody actually rated it.
        """
        if not message_ids:
            return {}
        user_ratings = (
            await message_rating_repo.get_user_ratings_for_messages(
                self.db, message_ids=message_ids, user_id=ctx.user_id
            )
            if ctx.user_id is not None
            else {}
        )
        counts = await message_rating_repo.get_rating_counts_for_messages(
            self.db, message_ids=message_ids
        )
        comments = await message_rating_repo.get_down_rating_comments_for_messages(
            self.db, message_ids=message_ids
        )
        return {
            message_id: {
                "user_rating": user_ratings.get(message_id),
                "rating_count": counts.get(message_id),
                "rating_comment": comments.get(message_id),
            }
            for message_id in message_ids
        }

    async def trace_url(self, ctx: AuthContext, run: AgentRun) -> str | None:
        """Where this run's trace can be read, if anywhere can.

        `None` on three honest paths, and a client renders no link for any of
        them: the run has no trace id (nothing was tracing), no slugs are
        configured, or the agent redirects its traces to a project whose slugs
        nobody told us. All three are configuration facts. The trace id stays on
        the row regardless, because it is useful to anybody with Logfire access
        even with no URL in the product.

        Resolved per run rather than once per deployment because
        `ObservabilitySpec` exists to send *one agent's* traces to a client's own
        project - so a link built from the deployment's slugs would point at a
        project that does not contain this run. The agent's own slugs win; the
        deployment's are the fallback for every agent that redirects nothing.

        Offered on the detail read only. Resolving it needs the version's stored
        spec, which is a lookup per row, and a list of fifty runs has no use for
        fifty trace links.

        `ctx` is taken rather than derived from the run because the version lookup
        is tenant-scoped and every read in this service goes through the same
        boundary - a spec fetched by id alone would be one place a listing could
        widen.
        """
        if run.logfire_trace_id is None:
            return None
        organization, project = settings.LOGFIRE_ORGANIZATION, settings.LOGFIRE_PROJECT
        if run.agent_version_id is not None:
            version = await agent_repo.get_version(
                self.db, run.agent_version_id, organization_id=ctx.organization_id
            )
            observability = None if version is None else _observability_of(version.spec)
            if observability is not None and observability.organization and observability.project:
                organization, project = observability.organization, observability.project
        if not organization or not project:
            return None
        return (
            f"{settings.LOGFIRE_BASE_URL.rstrip('/')}/{organization}/{project}"
            f"?q=trace_id%3D%27{run.logfire_trace_id}%27"
        )

    async def monthly_spend(self, ctx: AuthContext, *, agent_id: UUID | None = None) -> Decimal:
        """Spend so far this calendar month, for the org or one agent.

        One entry point, two genuinely different sums - and the two behaving
        alike is the bug, not the simplification.

        The organization's number includes what ingestion spent on embeddings,
        because that is money too and the organization's cap is a cap on the
        bill, not on one kind of line item. It **excludes the runs a delegation
        opened**: every run has one spend ledger, so a delegate's tokens are
        already inside the parent run's cost, and counting the child row as well
        would bill the organization twice for one request.

        The agent's number is the mirror image. It carries no ingestion -
        indexing a shared knowledge base is nobody's agent's spend - and it
        *does* count the runs it was delegated into, because those rows are the
        only record of what that agent cost. An agent used as a delegate
        accumulates against its own monthly cap that way; the cap does not stop a
        run mid-delegation (inside a delegation the parent's caps bind) but it is
        what makes "the researcher agent cost $40 this month" answerable and what
        a budget alert on that agent fires on.
        """
        if agent_id is not None:
            return await agent_run_repo.sum_cost_since(
                self.db,
                organization_id=ctx.organization_id,
                since=month_start(),
                agent_id=agent_id,
                include_delegations=True,
            )
        return await organization_monthly_spend(self.db, ctx.organization_id)

    async def spend_by_provider(
        self, ctx: AuthContext, *, since: datetime, until: datetime | None = None
    ) -> list[tuple[str | None, Decimal, int]]:
        """What each model provider was paid over a window.

        Every run contributes its **own** spend, its delegations' share taken
        back out, so a delegate on a second vendor appears under that vendor
        rather than under the one its parent happened to use. The rows still sum
        to the bill.

        The window is passed in rather than derived from a day count, so this and
        the per-agent rows beside it always describe the same runs. Two figures
        on one screen over two windows is the defect #198 is about, one panel
        further down.
        """
        return await agent_run_repo.spend_by_provider(
            self.db, organization_id=ctx.organization_id, since=since, until=until
        )

    async def spend_by_key(
        self, ctx: AuthContext, *, since: datetime, until: datetime | None = None
    ) -> list[tuple[UUID | None, str | None, Decimal, int]]:
        """What each stored key was spent through over a window.

        Own spend per run, as :meth:`spend_by_provider` - a delegate running on a
        different stored key is the same question about the same money.
        """
        return await agent_run_repo.spend_by_key(
            self.db, organization_id=ctx.organization_id, since=since, until=until
        )

    async def spend_by_agent(
        self, ctx: AuthContext, *, since: datetime, until: datetime | None = None
    ) -> list[AgentSpendRow]:
        """One row per agent for the Spend tab - the window, the month, the cap.

        The month-to-date figure is always the calendar month regardless of the
        window asked for, because that is the period a cap is a cap on. A tile
        comparing a rolling seven days against a monthly ceiling would read as
        20% used on the day the cap was actually reached.
        """
        return await agent_run_repo.spend_by_agent(
            self.db,
            organization_id=ctx.organization_id,
            since=since,
            until=until,
            month_since=month_start(),
        )
