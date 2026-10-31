"""The workflows capability against a real database: what an agent may start, and how."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.workflows import _toolset
from app.agents.capabilities.workflows._toolset import build_workflows_toolset
from app.agents.deps import AgentDeps
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStatus, WorkflowRunTrigger
from app.schemas.workflow import WorkflowPublish
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import seed_member

pytestmark = pytest.mark.anyio

FIELDS = [
    {"name": "email", "type": "text", "required": True, "description": "Who to follow up"},
    {"name": "tier", "type": "choice", "required": False, "options": ["gold", "silver"]},
]


def _graph(definition_id: str, config: dict[str, Any]) -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config,
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


_UNSET = object()


class _World:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def seed(self) -> None:
        async with self.factory() as db:
            self.owner, self.org = await seed_member(db)
            await db.commit()

    @property
    def ctx(self) -> AuthContext:
        return AuthContext(user_id=self.owner.id, organization_id=self.org.id, role="owner")

    async def workflow(
        self, name: str, graph: WorkflowGraph | None, *, description: str | None = None
    ) -> Workflow:
        """A workflow, published with `graph` unless that is `None`."""
        async with self.factory() as db:
            workflow = Workflow(
                id=uuid.uuid4(),
                organization_id=self.org.id,
                owner_user_id=self.owner.id,
                slug=f"wf-{uuid.uuid4().hex[:8]}",
                name=name,
                description=description,
                status=WorkflowStatus.DRAFT.value,
                visibility=Visibility.ORG.value,
            )
            db.add(workflow)
            await db.commit()
        if graph is not None:
            async with self.factory() as db:
                current = await db.get(Workflow, workflow.id)
                assert current is not None
                current.draft_graph = graph.model_dump(mode="json")
                await db.flush()
                await WorkflowRegistryService(db).publish(
                    self.ctx, workflow.id, WorkflowPublish(expected_revision=current.draft_revision)
                )
                await db.commit()
        return workflow

    def run_ctx(
        self,
        *,
        user_id: str | None = None,
        run_id: uuid.UUID | None = None,
        retry: int = 0,
        run_person: uuid.UUID | object | None = _UNSET,
        impersonated: bool = False,
    ):
        acting = str(self.owner.id) if user_id is None else user_id
        person = uuid.UUID(acting) if run_person is _UNSET else run_person
        assert person is None or isinstance(person, uuid.UUID)
        return RunContext(
            deps=AgentDeps(
                organization_id=self.org.id,
                user_id=acting,
                run_id=run_id,
                run_person=person,
                impersonated=impersonated,
            ),
            model=TestModel(),
            usage=RunUsage(),
            retry=retry,
            max_retries=1,
            tool_call_id="call-1",
        )


@pytest.fixture
async def world(engine: AsyncEngine) -> AsyncIterator[_World]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    made = _World(factory)
    await made.seed()
    with patch.object(_toolset, "get_db_context", side_effect=lambda: factory.begin()):
        yield made


def _tools(*workflows: Workflow, wait_seconds: int = 0):
    toolset = build_workflows_toolset(
        workflow_ids=tuple(workflow.id for workflow in workflows), wait_seconds=wait_seconds
    )
    return {name: tool.function for name, tool in toolset.tools.items()}


async def _runs(world: _World) -> list[WorkflowRun]:
    async with world.factory() as db:
        return list((await db.execute(select(WorkflowRun))).scalars())


async def test_it_lists_the_workflows_it_may_start_with_their_input(world: _World):
    import json

    follow_up = await world.workflow(
        "Follow up", _graph("trigger.manual", {"fields": FIELDS}), description="After a call"
    )
    called = await world.workflow("Called", _graph("trigger.workflow_call", {"fields": []}))
    by_hand = await world.workflow("Bare", _graph("core.input", {}))
    # An entry that is no trigger starts by hand, and declares nothing.
    plain = await world.workflow("Plain", _graph("debug.echo", {"message": "hi"}))
    scheduled = await world.workflow(
        "Nightly", _graph("trigger.schedule", {"interval_seconds": 3600})
    )
    draft = await world.workflow("Draft", None)
    archived = await world.workflow("Old", _graph("trigger.manual", {}))
    async with world.factory() as db:
        await db.execute(
            update(Workflow)
            .where(Workflow.id == archived.id)
            .values(status=WorkflowStatus.ARCHIVED.value)
        )
        await db.commit()
    tools = _tools(follow_up, called, by_hand, plain, scheduled, draft, archived, uuid_workflow())

    listed = json.loads(await tools["list_workflows"](world.run_ctx()))

    assert [entry["name"] for entry in listed] == ["Follow up", "Called", "Bare", "Plain"]
    assert listed[0]["description"] == "After a call"
    assert listed[0]["input"] == [
        {"name": "email", "type": "text", "required": True, "description": "Who to follow up"},
        {"name": "tier", "type": "choice", "required": False, "options": ["gold", "silver"]},
    ]
    assert listed[1]["input"] == listed[2]["input"] == listed[3]["input"] == []


def uuid_workflow() -> Workflow:
    """A workflow id no organization holds."""
    return Workflow(id=uuid.uuid4())


async def test_it_starts_a_workflow_as_the_member_with_the_input_checked(world: _World):
    import json

    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {"fields": FIELDS}))
    tools = _tools(follow_up)

    answer = json.loads(
        await tools["run_workflow"](
            world.run_ctx(), follow_up.id, fields={"email": "ada@example.com"}, wait=False
        )
    )

    (run,) = await _runs(world)
    assert answer["run_id"] == str(run.id)
    assert answer["status"] == run.status
    assert "Still running" in answer["note"]
    assert run.triggered_by == WorkflowRunTrigger.AGENT.value
    assert run.input == {"email": "ada@example.com"}
    assert run.execution_principal_user_id == world.owner.id


async def test_input_that_does_not_fit_is_steered_back_to_the_model(world: _World):
    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {"fields": FIELDS}))
    tools = _tools(follow_up)

    with pytest.raises(ModelRetry, match="does not fit"):
        await tools["run_workflow"](world.run_ctx(), follow_up.id, fields={"tier": "gold"})
    # On the last attempt the same words come back as the answer instead.
    answer = await tools["run_workflow"](world.run_ctx(retry=1), follow_up.id, fields={})
    assert "does not fit" in answer
    assert await _runs(world) == []


async def test_a_wait_reads_the_run_again_until_it_ends(world: _World, monkeypatch):
    import json

    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))
    tools = _tools(follow_up, wait_seconds=30)

    async def worker_finishes(_seconds: float) -> None:
        async with world.factory() as db:
            await db.execute(
                update(WorkflowRun).values(
                    status=WorkflowRunStatus.SUCCEEDED.value, output={"sent": True}
                )
            )
            await db.commit()

    monkeypatch.setattr(_toolset.asyncio, "sleep", worker_finishes)

    answer = json.loads(await tools["run_workflow"](world.run_ctx(), follow_up.id))

    assert answer["status"] == "succeeded"
    assert answer["output"] == {"sent": True}
    assert "note" not in answer


@pytest.mark.security
@pytest.mark.parametrize("impersonated", [True, False])
async def test_a_run_started_under_impersonation_starts_its_workflow_that_way(
    world: _World, impersonated: bool
):
    """No request is left to ask when a resumed run or a spawned task calls the tool."""
    import json

    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))
    tools = _tools(follow_up)

    started = json.loads(
        await tools["run_workflow"](
            world.run_ctx(impersonated=impersonated), follow_up.id, wait=False
        )
    )

    async with world.factory() as db:
        run = await db.get(WorkflowRun, uuid.UUID(started["run_id"]))
    assert run is not None
    assert run.impersonated is impersonated


async def test_a_run_is_read_back_with_its_error(world: _World):
    import json

    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))
    tools = _tools(follow_up)
    started = json.loads(await tools["run_workflow"](world.run_ctx(), follow_up.id, wait=False))
    async with world.factory() as db:
        await db.execute(
            update(WorkflowRun).values(
                status=WorkflowRunStatus.FAILED.value,
                error={"code": "BOOM", "message": "It broke", "details": {"secret": "x"}},
            )
        )
        await db.commit()

    read = json.loads(
        await tools["get_workflow_run"](world.run_ctx(), uuid.UUID(started["run_id"]))
    )

    assert read == {
        "run_id": started["run_id"],
        "status": "failed",
        "error": {"code": "BOOM", "message": "It broke"},
    }


@pytest.mark.security
async def test_a_workflow_the_binding_does_not_name_is_neither_started_nor_read(world: _World):
    import json

    named = await world.workflow("Named", _graph("trigger.manual", {}))
    other = await world.workflow("Other", _graph("trigger.manual", {}))
    started = json.loads(await _tools(other)["run_workflow"](world.run_ctx(), other.id, wait=False))
    tools = _tools(named)

    refused = await tools["run_workflow"](world.run_ctx(), other.id)
    read = await tools["get_workflow_run"](world.run_ctx(), uuid.UUID(started["run_id"]))

    assert "may not start that workflow" in refused
    assert "may not start that workflow" in read
    assert len(await _runs(world)) == 1


@pytest.mark.security
async def test_a_member_who_may_not_run_it_or_is_gone_starts_nothing(world: _World):
    private = await world.workflow("Private", _graph("trigger.manual", {}))
    async with world.factory() as db:
        await db.execute(
            update(Workflow)
            .where(Workflow.id == private.id)
            .values(visibility=Visibility.PRIVATE.value, owner_user_id=None)
        )
        colleague = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(colleague)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=world.org.id, user_id=colleague.id, role="member"
            )
        )
        await db.commit()
    tools = _tools(private)

    stranger = await tools["run_workflow"](world.run_ctx(user_id=str(colleague.id)), private.id)
    outsider = await tools["run_workflow"](world.run_ctx(user_id=str(uuid.uuid4())), private.id)
    visitor = await tools["run_workflow"](
        world.run_ctx(user_id=str(world.owner.id), run_person=None), private.id
    )

    assert "cannot run it" in stranger
    assert visitor == "Workflows can only be started by a run acting for a member."
    assert "member of an organization" in outsider
    assert await _runs(world) == []


async def test_a_workflow_that_starts_some_other_way_is_not_started(world: _World):
    scheduled = await world.workflow(
        "Nightly", _graph("trigger.schedule", {"interval_seconds": 3600})
    )

    answer = await _tools(scheduled)["run_workflow"](world.run_ctx(), scheduled.id)

    assert "not published to start by hand" in answer


@pytest.mark.security
async def test_a_start_spends_the_workflow_run_allowance_and_is_refused_over_it(world: _World):
    from app.services import rate_limit

    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {"fields": FIELDS}))
    tools = _tools(follow_up)
    over = rate_limit.Decision(allowed=False, retry_after_seconds=17)

    with patch.object(_toolset.rate_limit, "consume", AsyncMock(return_value=over)) as consume:
        answer = await tools["run_workflow"](
            world.run_ctx(), follow_up.id, fields={"email": "ada@example.com"}, wait=False
        )

    assert "Too many workflow runs" in answer and "17 seconds" in answer
    assert await _runs(world) == []
    assert consume.await_args.kwargs["surface"] == "workflow_run"
    assert consume.await_args.kwargs["caller"] == f"user:{world.owner.id}"


@pytest.mark.security
async def test_an_agent_running_as_a_workflow_step_starts_no_workflow(world: _World):
    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))
    async with world.factory() as db:
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=world.org.id,
            slug=f"step-{uuid.uuid4().hex[:8]}",
            name="Step",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=world.org.id,
            agent_id=agent.id,
            user_id=world.owner.id,
            status=RunStatus.RUNNING.value,
            surface=RunSurface.WORKFLOW.value,
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.commit()

    answer = await _tools(follow_up)["run_workflow"](world.run_ctx(run_id=run.id), follow_up.id)

    assert "a workflow.run step calls one" in answer
    assert await _runs(world) == []

    # The same agent in a conversation starts it.
    async with world.factory() as db:
        await db.execute(
            update(AgentRun).where(AgentRun.id == run.id).values(surface=RunSurface.WEB.value)
        )
        await db.commit()
    await _tools(follow_up)["run_workflow"](world.run_ctx(run_id=run.id), follow_up.id, wait=False)
    assert len(await _runs(world)) == 1


async def test_a_run_it_cannot_find_is_refused_by_its_code(world: _World):
    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))

    answer = await _tools(follow_up)["get_workflow_run"](world.run_ctx(), uuid.uuid4())

    assert answer.startswith("Refused (WORKFLOW_RUN_NOT_FOUND)")


@pytest.mark.security
async def test_a_widget_run_starts_no_workflow(world: _World):
    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))

    answer = await _tools(follow_up)["run_workflow"](
        world.run_ctx(user_id=str(world.owner.id), run_person=None), follow_up.id
    )

    assert answer == "Workflows can only be started by a run acting for a member."
    assert await _runs(world) == []


async def test_a_member_run_still_starts_a_workflow(world: _World):
    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))

    await _tools(follow_up)["run_workflow"](world.run_ctx(), follow_up.id, wait=False)

    assert len(await _runs(world)) == 1


async def test_a_widget_run_can_still_list_workflows(world: _World):
    import json

    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))

    listed = json.loads(await _tools(follow_up)["list_workflows"](world.run_ctx(run_person=None)))

    assert [entry["id"] for entry in listed] == [str(follow_up.id)]


@pytest.mark.security
async def test_a_workflow_step_in_a_public_run_still_hears_the_step_text(world: _World):
    follow_up = await world.workflow("Follow up", _graph("trigger.manual", {}))
    async with world.factory() as db:
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=world.org.id,
            slug=f"step-{uuid.uuid4().hex[:8]}",
            name="Step",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=world.org.id,
            agent_id=agent.id,
            user_id=world.owner.id,
            status=RunStatus.RUNNING.value,
            surface=RunSurface.WORKFLOW.value,
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.commit()

    answer = await _tools(follow_up)["run_workflow"](
        world.run_ctx(run_id=run.id, run_person=None), follow_up.id
    )

    assert answer == (
        "An agent running as a workflow's step starts no workflow; a workflow.run step calls one."
    )
    assert await _runs(world) == []
