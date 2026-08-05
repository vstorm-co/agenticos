"""Two gated tool calls in one model step, against a real session.

The bug this pins (agenticos#169): a model that answers one step with two gated
tool calls drives two calls into `ApprovalChannel` at once, because Pydantic AI
runs the tool calls from one response concurrently. When the channel wrote the
approval row itself, both writes landed on the request's `AsyncSession` - which
the whole run shares and which is not concurrency-safe - and two flushes on it at
once corrupt the session and take the parent run row and the conversation with it.

A mocked session cannot show this: it flushes whatever it is told and knows
nothing about what concurrent statements do to the transaction around it. Postgres
does, which is why this lives here. The fix moves the write out of the concurrent
path entirely - the channel only *describes* the parked call - so what this proves
is the shape after the fix: the run parks once naming both calls, two rows are
written with distinct ids at the run's terminal write, and the session is still
usable, which the parent's committed terminal row is the evidence of.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import DeferredToolRequests
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.capabilities import (
    REGISTRY,
    CapabilityBuildContext,
    CapabilityToolInfo,
    load_builtins,
    register,
)
from app.agents.capabilities.budget import SpendLedger
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.secret_kinds import ApiKeySecret
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import agent_run_repo
from app.services.agent_runner import (
    AgentRunnerService,
    ApprovalChannel,
    ParkedApproval,
    PausedRunState,
    PreparedRun,
)

pytestmark = pytest.mark.anyio

GATED_CAPABILITY = "test_concurrent_gated_action"
GATED_TOOL = "send_email"


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


@pytest.fixture(autouse=True)
def gated_capability():
    """A capability with one side-effecting tool, so every call parks on the gate."""

    @register(
        id=GATED_CAPABILITY,
        name="Gated action",
        category="test",
        description="A side-effecting action that must be approved",
        side_effecting=True,
        tools=(CapabilityToolInfo(id=GATED_TOOL, description="Sends an email."),),
    )
    def _build(ctx: CapabilityBuildContext) -> _GatedAction:
        return _GatedAction()

    yield
    REGISTRY.pop(GATED_CAPABILITY)


class _GatedAction(AbstractCapability[Any]):
    """One tool that runs only after a human says yes - and never does here."""

    def get_toolset(self) -> AbstractToolset[Any]:
        def send_email(to: str) -> str:
            """Send an email to someone."""
            return f"sent to {to}"

        toolset: FunctionToolset[Any] = FunctionToolset()
        toolset.add_function(send_email, takes_ctx=False)
        return toolset


def _two_gated_caller() -> FunctionModel:
    """A model that answers one step with two calls to the gated tool.

    "Email the customer and email the account manager" - the honest example from
    the issue, and the one that drives two calls into the channel concurrently.
    """

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(tool_name=GATED_TOOL, args={"to": "customer"}, tool_call_id="call-a"),
                ToolCallPart(tool_name=GATED_TOOL, args={"to": "manager"}, tool_call_id="call-b"),
            ]
        )

    return FunctionModel(respond)


def _model_spec() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1 (prod)",
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
        ),
        fallbacks=[],
    )


async def _org(db: AsyncSession) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return org


async def _published(db: AsyncSession, org: Organization) -> tuple[Agent, AgentVersion]:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={"name": agent.name},
    )
    db.add(version)
    await db.flush()
    return agent, version


async def test_two_gated_calls_in_one_step_park_once_and_write_two_rows(db, engine):
    """The regression: park once, two distinct rows, session still usable.

    Before the fix the two concurrent tool calls each wrote their row on the shared
    session and corrupted it; here the writes are deferred to the run's terminal
    write, so the parent's finished row committing beside the two approval rows is
    what proves the session survived.
    """
    org = await _org(db)
    agent, version = await _published(db, org)
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=None,
        conversation_id=None,
        surface="api",
        model_label="gpt-4.1",
        provider="openai",
        secret_id=None,
        started_at=datetime.now(UTC),
    )

    spec = AgentSpec(name="Clerk", capabilities=[{"id": GATED_CAPABILITY, "approval": "required"}])
    channel = ApprovalChannel(organization_id=org.id, agent_id=agent.id, run_id=run.id)
    built = build_agent(
        spec,
        _model_spec(),
        organization_id=org.id,
        agent_id=agent.id,
        run_id=run.id,
        request_approval=channel,
    )

    with built.agent.override(model=_two_gated_caller()):
        result = await built.agent.run(
            "email the customer and the account manager", deps=built.deps
        )

    # One step, both calls gated: the run parks rather than answering, and names
    # both. Concurrent execution of the two calls is what used to race the session.
    assert isinstance(result.output, DeferredToolRequests)
    assert sorted(call.tool_call_id for call in result.output.approvals) == ["call-a", "call-b"]
    assert len(channel.requested) == 2

    prepared = PreparedRun(run=run, agent=agent, spec=spec, built=built, approvals=channel)
    await AgentRunnerService(db).finish(
        prepared,
        status=RunStatus.AWAITING_APPROVAL,
        paused_state=PausedRunState(
            messages=ModelMessagesTypeAdapter.dump_python(result.all_messages(), mode="json"),
            tool_call_ids=channel.parked,
        ),
    )
    await db.commit()

    # Read in another session: the question is what was committed, and this one's
    # identity map would answer with what it holds regardless.
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as fresh:
        finished = await fresh.get(AgentRun, run.id)
        rows = (
            (await fresh.execute(select(ToolApproval).where(ToolApproval.run_id == run.id)))
            .scalars()
            .all()
        )

    # The session survived two concurrent gated calls: its terminal write committed.
    assert finished is not None
    assert finished.status == RunStatus.AWAITING_APPROVAL.value
    # Two rows, with distinct ids - not one row written twice, nor one lost to a
    # race - and both against the gated tool.
    assert len(rows) == 2
    assert len({row.id for row in rows}) == 2
    assert {row.tool_id for row in rows} == {GATED_TOOL}
    # And the ids the row-writes used are the ones the channel allocated when it
    # parked, which are what the stored state names for the resume to find them.
    assert {row.id for row in rows} == {parked.approval_id for parked in channel.requested}
    assert set(finished.paused_state["tool_call_ids"]) == {str(row.id) for row in rows}


async def test_a_delegate_deleted_before_the_write_leaves_the_approval_with_a_null_id(db, engine):
    """A delegate gone by `finish()` must not roll the parked run back.

    Found reviewing #169. Deferring the write to the run's terminal write means a
    delegate whose gated call was parked can be deleted before the row is written.
    `subagent_agent_id` is a `SET NULL` foreign key precisely so deleting a delegate
    leaves the record of what it was authorised to do - but that only fires once the
    row exists. The insert has to do the same for a delete that lands first: write
    the id null, keep the delegate's name, and leave the run resumable rather than
    letting the foreign key roll the whole parked run back. A surviving delegate on
    the same run keeps its id, so the null is the deletion's doing, not a blanket drop.
    """
    org = await _org(db)
    parent, parent_version = await _published(db, org)
    gone, _ = await _published(db, org)
    kept, _ = await _published(db, org)
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=parent.id,
        agent_version_id=parent_version.id,
        user_id=None,
        conversation_id=None,
        surface="api",
        model_label="gpt-4.1",
        provider="openai",
        secret_id=None,
        started_at=datetime.now(UTC),
    )

    channel = ApprovalChannel(organization_id=org.id, agent_id=parent.id, run_id=run.id)
    parked_by_call: dict[str, ParkedApproval] = {}
    for tool_call_id, delegate in (("call-gone", gone), ("call-kept", kept)):
        approval_id = uuid.uuid4()
        channel.parked[str(approval_id)] = tool_call_id
        parked = ParkedApproval(
            approval_id=approval_id,
            tool_call_id=tool_call_id,
            tool_name="send_email",
            tool_args={"to": "customer"},
            subagent="researcher",
            subagent_agent_id=delegate.id,
        )
        channel.requested.append(parked)
        parked_by_call[tool_call_id] = parked

    # Somebody deletes one delegate while the run is still parked. Its id is already
    # on the ParkedApproval the terminal write will use.
    await db.delete(gone)
    await db.flush()

    prepared = PreparedRun(
        run=run,
        agent=parent,
        spec=AgentSpec(name="Clerk"),
        built=MagicMock(ledger=SpendLedger()),
        approvals=channel,
    )
    await AgentRunnerService(db).finish(
        prepared,
        status=RunStatus.AWAITING_APPROVAL,
        paused_state=PausedRunState(messages=[], tool_call_ids=channel.parked),
    )
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as fresh:
        finished = await fresh.get(AgentRun, run.id)
        rows = {
            row.id: row
            for row in (
                await fresh.execute(select(ToolApproval).where(ToolApproval.run_id == run.id))
            )
            .scalars()
            .all()
        }

    # The parked run committed rather than rolling back on the missing delegate.
    assert finished is not None
    assert finished.status == RunStatus.AWAITING_APPROVAL.value
    assert len(rows) == 2
    # The deleted delegate's row survives, its id nulled and its name kept, so a
    # reviewer still sees what was authorised and the run can still be resumed.
    gone_row = rows[parked_by_call["call-gone"].approval_id]
    assert gone_row.subagent_agent_id is None
    assert gone_row.subagent_name == "researcher"
    assert gone_row.status == ApprovalStatus.PENDING.value
    # The delegate that still exists keeps its id - the null above is the deletion's
    # doing, not a blanket drop of every delegate's attribution.
    kept_row = rows[parked_by_call["call-kept"].approval_id]
    assert kept_row.subagent_agent_id == kept.id
