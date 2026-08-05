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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessagesTypeAdapter
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
from app.agents.capabilities.sandbox import WORKSPACE_BACKEND_RESOURCE, WorkspaceIdentity
from app.agents.capabilities.sandbox._identity import SessionScope
from app.agents.capabilities.subagents import SubagentsConfig, acting_delegate
from app.agents.deps import AgentDeps
from app.agents.factory import BuiltAgent, build_agent
from app.agents.model_resolver import ModelRequestSpec
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
    ResolvedSubagent,
    ResumedDelegation,
    SubagentRuntime,
)
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import StorableSecret
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_exposure import AgentExposure
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, RunSurface
from app.db.models.chat_file import ChatFile
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    agent_run_repo,
    knowledge_base_repo,
)
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


def _delegation_frames(parked: Sequence[ParkedDelegation]) -> list[DelegationFrame]:
    """One run's parked delegations, nested the way they were made.

    Assembled from a flat list because that is what the capability can safely
    produce: a fan-out runs several delegations in several asyncio tasks, and each
    appends its own frame without knowing what any other did. The nesting is
    recovered from `parent_task_id`, which each level read where its delegation
    opened - so two concurrent chains cannot be threaded into one.

    The recursion is bounded by `max_depth`, and by the fact that a delegation's
    children all carry its task id as their parent while its own parent is
    something else.
    """
    by_parent: dict[str | None, list[ParkedDelegation]] = {}
    for entry in parked:
        by_parent.setdefault(entry.parent_task_id, []).append(entry)

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
                started_at=entry.started_at,
                delegations=frames(by_parent.get(entry.task_id, [])),
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
        return results

    return _ResumePlan(
        results=level(state.delegations, by_delegation.get(None, [])),
        delegations=resuming,
        spent=spent,
        started=started,
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
        surface: RunSurface = RunSurface.PLAYGROUND,
        conversation_id: UUID | None = None,
        channel_key: str | None = None,
        user_name: str | None = None,
        extra_toolsets: list[Any] | None = None,
        exposure: AgentExposure | None = None,
        model_profile_id: UUID | None = None,
        environment_id: UUID | None = None,
    ) -> PreparedRun:
        """Assemble everything a run needs and open its row.

        Args:
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
        return await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=None,
            surface=surface,
            conversation_id=conversation_id,
            channel_key=channel_key,
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
        user_name: str | None,
        extra_toolsets: list[Any] | None,
        exposure: AgentExposure | None,
        decided: dict[str, ApprovalDecision],
        resuming: dict[str, ResumedDelegation],
        already_spent: dict[str, DelegationSpend],
        already_started: dict[str, datetime | None],
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
        stash = DelegationStash(resuming=resuming, spent=already_spent, started=already_started)
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

        Each row is written with the id allocated when the call was parked, so it
        matches the `paused_state` that names it and the :class:`ParkedApproval` a
        surface already drew a card from. An unparked run leaves `requested` empty
        and this does nothing.
        """
        channel = prepared.approvals
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
                subagent_agent_id=parked.subagent_agent_id,
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
        logfire_trace_id: str | None = None,
        paused_state: PausedRunState | None = None,
        budget_scope: BudgetScope | None = None,
    ) -> AgentRun:
        """Record what the run consumed and how it ended.

        Called from a `finally` block by every surface: a crashed run still
        spent money, and a budget that ignores failures is not a budget.

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
            logfire_trace_id=logfire_trace_id,
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
        """
        return paused_state.model_copy(
            update={
                "delegated_approvals": {
                    str(parked.approval_id): parked.task_id
                    for parked in prepared.approvals.requested
                    if parked.task_id is not None
                },
                "delegations": _delegation_frames(prepared.stash.parked),
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
        surface: RunSurface = RunSurface.API,
        conversation_id: UUID | None = None,
        channel_key: str | None = None,
        message_history: list[Any] | None = None,
        exposure: AgentExposure | None = None,
        environment_id: UUID | None = None,
        attachments: list[ChatFile] | None = None,
        outbound: list[OutgoingAttachment] | None = None,
        outbound_refused: list[str] | None = None,
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
        before.

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
        answered = await self._run(
            prepared,
            user_prompt=assembled,
            message_history=message_history,
            deferred_tool_results=None,
        )
        if outbound is not None:
            outbound.extend(prepared.outbound)
        if outbound_refused is not None:
            outbound_refused.extend(prepared.outbound_refused)
        return answered

    async def resume(self, ctx: AuthContext, run_id: UUID) -> tuple[str, AgentRun]:
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

        Raises:
            NotFoundError: If the run is not in this organization.
            BadRequestError: If the run is not parked, has no stored state, or
                still has a decision outstanding. All three mean the caller is
                about to replay something it should not.
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
        # Out of the queue before anything is replayed: the row lock above only
        # holds until this transaction commits, and what makes a second resume
        # refuse afterwards is the status it finds.
        await agent_run_repo.mark_running(self.db, run=run)

        agent, spec = await self._parked_spec(ctx, run)
        # The continuation traces where the original did: the environment that
        # routed the run still owns its observability.
        spec = await self._with_environment_observability(
            ctx, spec, environment_id=run.environment_id
        )
        prepared = await self._assemble(
            ctx,
            agent=agent,
            spec=spec,
            existing_run=run,
            surface=RunSurface(run.surface),
            conversation_id=run.conversation_id,
            user_name=None,
            extra_toolsets=None,
            # A resumed run reuses its row, and the binding that admitted it was
            # stamped on that row when it was opened - there is nothing left for
            # the exposure to contribute here.
            exposure=None,
            decided=decided,
            resuming=plan.delegations,
            already_spent=plan.spent,
            already_started=plan.started,
        )
        prepared.built.ledger.book(_spend_already_booked(run))

        return await self._run(
            prepared,
            # No new prompt: the conversation resumes at the tool call it stopped
            # on, and inventing a user turn here would put words in their mouth.
            user_prompt=None,
            message_history=ModelMessagesTypeAdapter.validate_python(state.messages),
            deferred_tool_results=plan.results,
        )

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

    async def _run(
        self,
        prepared: PreparedRun,
        *,
        user_prompt: str | list[Any] | None,
        message_history: list[Any] | None,
        deferred_tool_results: DeferredToolResults | None,
    ) -> tuple[str, AgentRun]:
        """Execute the agent and account for it, however it ends.

        The one place a run is executed, so a parked call, a budget stop, a
        cancellation and a crash are all recorded the same way whether the run is
        new or resumed.

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
        try:
            # `metered_by` books what the request wrapper cannot see - the
            # embedding calls a knowledge search makes - to this run's ledger,
            # so they land in `cost_usd` next to the model requests.
            with metered_by(prepared.built.ledger):
                result = await prepared.built.agent.run(
                    user_prompt,
                    deps=prepared.built.deps,
                    message_history=message_history,
                    deferred_tool_results=deferred_tool_results,
                    usage_limits=prepared.built.usage_limits,
                )
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
            error = str(exc)
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
            # Committed here rather than left to the session context: that exit
            # rolls back on any exception, and cancellation never reaches it at
            # all, since `CancelledError` is not an `Exception`. A run that
            # failed, was stopped or ran out of budget still spent money, and a
            # run missing from history is a run nobody is accountable for.
            await self.db.commit()

        return output, prepared.run

    async def list_runs(
        self,
        ctx: AuthContext,
        *,
        agent_id: UUID | None = None,
        parent_run_id: UUID | None = None,
        include_delegations: bool = False,
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
        """
        return await agent_run_repo.list_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            parent_run_id=parent_run_id,
            include_delegations=include_delegations,
            skip=skip,
            limit=limit,
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
        self, ctx: AuthContext, *, days: int = 30
    ) -> list[tuple[str | None, Decimal, int]]:
        """What each model provider was paid over a window."""
        return await agent_run_repo.spend_by_provider(
            self.db,
            organization_id=ctx.organization_id,
            since=datetime.now(UTC) - timedelta(days=days),
        )

    async def spend_by_key(
        self, ctx: AuthContext, *, days: int = 30
    ) -> list[tuple[UUID | None, str | None, Decimal, int]]:
        """What each stored key was spent through over a window."""
        return await agent_run_repo.spend_by_key(
            self.db,
            organization_id=ctx.organization_id,
            since=datetime.now(UTC) - timedelta(days=days),
        )

    async def cost_breakdown(
        self, ctx: AuthContext, *, days: int = 30
    ) -> list[tuple[UUID, str | None, Decimal, int]]:
        """Spend per agent and model over a window - the dashboard's data."""
        since = datetime.now(UTC) - timedelta(days=days)
        return await agent_run_repo.cost_breakdown(
            self.db, organization_id=ctx.organization_id, since=since
        )
