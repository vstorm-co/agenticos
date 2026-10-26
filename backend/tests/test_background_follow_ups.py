"""Post-answer suggestions: independent authority, accounting and message identity."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

from app.agents.capabilities.budget import BudgetGuard, SpendLedger
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.db.models.agent_run import RunStatus
from app.services import follow_ups as module
from app.services.follow_ups import FollowUpService, model_profile, write_next_steps

pytestmark = pytest.mark.anyio


@pytest.fixture
def scenario(monkeypatch):
    org, agent, run, conversation, message, user, version, profile = [uuid4() for _ in range(8)]
    db = AsyncMock()
    row = SimpleNamespace(
        id=message, role="assistant", content="The answer", run_id=run, conversation_id=conversation
    )
    parent = SimpleNamespace(
        id=run,
        agent_id=agent,
        status="completed",
        user_id=user,
        initiated_by_publisher_fallback=False,
        conversation_id=conversation,
        surface="web",
        test_spec=None,
        agent_version_id=version,
        key_scopes=None,
        environment_id=None,
        is_test=False,
    )
    spec = AgentSpec(
        name="Helper",
        capabilities=[{"id": "follow_ups", "config": {"model_profile_id": str(profile)}}],
    )
    mocks = {}
    for repo, name, value in [
        (module.conversation_repo, "get_message_by_id", row),
        (module.agent_run_repo, "get_run", parent),
        (module.agent_run_repo, "associate_auxiliary_conversation", None),
        (
            module.conversation_repo,
            "get_conversation_by_id",
            SimpleNamespace(organization_id=org, is_archived=False),
        ),
        (module.agent_repo, "get_version", SimpleNamespace(spec=spec.model_dump(mode="json"))),
        (module.member_repo, "get_active", SimpleNamespace(role="owner")),
        (
            module.user_repo,
            "get_by_id",
            SimpleNamespace(id=user, is_active=True, is_app_admin=False),
        ),
        (module.conversation_repo, "prompt_for_answer", "The question"),
        (module.conversation_repo, "store_next_steps", True),
        (module.chat_room, "next_steps", None),
    ]:
        mock = AsyncMock(return_value=value)
        monkeypatch.setattr(repo, name, mock)
        mocks[name] = mock
    runner = MagicMock()
    runner.prepare = AsyncMock(return_value=SimpleNamespace(run=SimpleNamespace()))
    monkeypatch.setattr(module, "AgentRunnerService", lambda _db: runner)
    service = FollowUpService(db)
    service._generate = AsyncMock(return_value=["Make a table"])
    return SimpleNamespace(
        org=org,
        agent=agent,
        profile=profile,
        db=db,
        row=row,
        parent=parent,
        spec=spec,
        mocks=mocks,
        runner=runner,
        service=service,
    )


async def test_saved_answer_gets_its_own_run_and_targeted_event(scenario):
    s = scenario
    s.parent.key_scopes = ["agents:run", "no-longer-known"]
    await s.service.write(s.row.id, s.org)
    s.runner.prepare.assert_awaited_once()
    args = s.runner.prepare.await_args
    assert args.kwargs["model_profile_id"] == s.profile
    assert args.kwargs["aside"] is True
    assert args.kwargs["surface"].value == "follow_ups"
    s.mocks["associate_auxiliary_conversation"].assert_awaited_once_with(
        s.db, s.runner.prepare.return_value.run, s.row.conversation_id
    )
    assert "conversation_id" not in args.kwargs
    assert {scope.value for scope in args.args[0].key_scopes} == {"agents:run"}
    assert s.service._generate.await_args.args[2:] == ("The question", "The answer")
    s.mocks["store_next_steps"].assert_awaited_once_with(
        s.db, message_id=s.row.id, organization_id=s.org, steps=["Make a table"]
    )
    s.mocks["next_steps"].assert_awaited_once_with(
        str(s.row.conversation_id), str(s.row.id), ["Make a table"]
    )
    assert s.db.commit.await_count == 2


@pytest.mark.parametrize(
    "missing",
    [
        "message",
        "role",
        "run",
        "parent",
        "status",
        "user",
        "conversation_id",
        "conversation",
        "tenant",
        "archived",
        "version",
        "spec",
        "profile",
        "membership",
        "account",
        "inactive",
    ],
)
async def test_refusals_never_call_the_model(scenario, missing):
    s = scenario
    if missing == "message":
        s.mocks["get_message_by_id"].return_value = None
    elif missing == "role":
        s.row.role = "user"
    elif missing == "run":
        s.row.run_id = None
    elif missing == "parent":
        s.mocks["get_run"].return_value = None
    elif missing == "status":
        s.parent.status = "cancelled"
    elif missing == "user":
        s.parent.user_id = None
    elif missing == "conversation_id":
        s.parent.conversation_id = uuid4()
    elif missing == "conversation":
        s.mocks["get_conversation_by_id"].return_value = None
    elif missing == "tenant":
        s.mocks["get_conversation_by_id"].return_value.organization_id = uuid4()
    elif missing == "archived":
        s.mocks["get_conversation_by_id"].return_value.is_archived = True
    elif missing == "version":
        s.mocks["get_version"].return_value = None
    elif missing == "spec":
        s.parent.agent_version_id = None
    elif missing == "profile":
        s.parent.test_spec = AgentSpec(name="Helper").model_dump(mode="json")
    elif missing == "membership":
        s.mocks["get_active"].return_value = None
    elif missing == "account":
        s.mocks["get_by_id"].return_value = None
    elif missing == "inactive":
        s.mocks["get_by_id"].return_value.is_active = False
    await s.service.write(s.row.id, s.org)
    s.runner.prepare.assert_not_awaited()
    s.service._generate.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["gone", "empty", "deleted", "draft"])
async def test_optional_failures_and_draft_snapshot(scenario, outcome):
    s = scenario
    if outcome == "gone":
        s.runner.prepare.side_effect = NotFoundError(message="Gone")
    if outcome == "empty":
        s.service._generate.return_value = []
    if outcome == "deleted":
        s.mocks["store_next_steps"].return_value = False
    if outcome == "draft":
        s.parent.test_spec = s.spec.model_dump(mode="json")
        s.parent.agent_version_id = None
    await s.service.write(s.row.id, s.org)
    if outcome == "draft":
        assert s.runner.prepare.await_args.kwargs["draft"] is True
        s.mocks["get_version"].assert_not_awaited()
    elif outcome == "empty":
        s.mocks["next_steps"].assert_awaited_once_with(
            str(s.row.conversation_id), str(s.row.id), []
        )
    else:
        s.mocks["next_steps"].assert_not_awaited()


@pytest.mark.parametrize(
    "capabilities",
    [[], [{"id": "follow_ups"}], [{"id": "follow_ups", "enabled": False}], [{"id": "clock"}]],
)
def test_missing_separate_model_disables_suggestions(capabilities):
    assert model_profile(AgentSpec(name="Helper", capabilities=capabilities)) is None


@asynccontextmanager
async def no_heartbeat(_run):
    yield


def prepared_run(model=None):
    ledger = SpendLedger()
    budget = BudgetGuard(ledger=ledger)
    host = Agent(model or TestModel(custom_output_args={"steps": [" Make a table ", "x" * 81]}))
    return SimpleNamespace(
        run=SimpleNamespace(id=uuid4()),
        built=SimpleNamespace(
            agent=host,
            budget=budget,
            ledger=ledger,
            deps=AgentDeps(),
            usage_limits=UsageLimits(request_limit=5),
        ),
    )


async def test_real_helper_has_no_main_agent_tools_or_instructions_and_is_metered(monkeypatch):
    monkeypatch.setattr(module, "run_heartbeat", no_heartbeat)
    prepared = prepared_run()
    runner = SimpleNamespace(finish=AsyncMock())
    service = FollowUpService(AsyncMock())
    assert await service._generate(runner, prepared, "Question", "Answer") == ["Make a table"]
    assert prepared.built.ledger.input_tokens > 0
    assert prepared.built.ledger.output_tokens > 0
    assert runner.finish.await_args.kwargs["status"] == RunStatus.COMPLETED
    service.db.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "failure", [RuntimeError("provider"), TimeoutError(), asyncio.CancelledError()]
)
async def test_failure_timeout_and_cancellation_always_settle(monkeypatch, failure):
    monkeypatch.setattr(module, "run_heartbeat", no_heartbeat)
    prepared = prepared_run()
    helper = SimpleNamespace(run=AsyncMock(side_effect=failure))
    monkeypatch.setattr(module, "_helper", lambda _prepared: helper)
    runner = SimpleNamespace(finish=AsyncMock())
    service = FollowUpService(AsyncMock())
    if isinstance(failure, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await service._generate(runner, prepared, "q", "a")
        assert runner.finish.await_args.kwargs["status"] == RunStatus.CANCELLED
    else:
        assert await service._generate(runner, prepared, "q", "a") == []
        assert runner.finish.await_args.kwargs["status"] == RunStatus.FAILED
    service.db.commit.assert_awaited_once()


async def test_unusable_model_still_settles(monkeypatch):
    prepared = prepared_run()
    prepared.built.agent = SimpleNamespace(model=None)
    runner = SimpleNamespace(finish=AsyncMock())
    assert await FollowUpService(AsyncMock())._generate(runner, prepared, "q", "a") == []
    runner.finish.assert_awaited_once()


async def test_optional_work_never_waits_for_capacity(monkeypatch):
    semaphore = asyncio.Semaphore(0)
    monkeypatch.setattr(module, "suggestion_slots", semaphore)
    db_context = MagicMock()
    monkeypatch.setattr(module, "get_db_context", db_context)
    await write_next_steps(uuid4(), uuid4())
    db_context.assert_not_called()


async def test_post_commit_task_owns_its_session(monkeypatch):
    db = AsyncMock()

    @asynccontextmanager
    async def context():
        yield db

    monkeypatch.setattr(module, "get_db_context", context)
    write = AsyncMock()
    monkeypatch.setattr(FollowUpService, "write", write)
    message, org = uuid4(), uuid4()
    await write_next_steps(message, org)
    write.assert_awaited_once_with(message, org)


async def test_channel_waits_until_its_answer_is_delivered(scenario):
    s = scenario
    s.parent.surface = "slack"
    await s.service.write(s.row.id, s.org)
    s.runner.prepare.assert_not_awaited()
    await s.service.write(s.row.id, s.org, channel=True)
    s.runner.prepare.assert_awaited_once()


async def test_repeated_shutdown_cancellation_drains_paid_settlement(monkeypatch):
    monkeypatch.setattr(module, "run_heartbeat", no_heartbeat)
    prepared = prepared_run()
    entered, release = asyncio.Event(), asyncio.Event()

    async def finish(*args, **kwargs):
        entered.set()
        await release.wait()

    runner = SimpleNamespace(finish=finish)
    service = FollowUpService(AsyncMock())
    task = asyncio.create_task(service._generate(runner, prepared, "q", "a"))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    service.db.commit.assert_awaited_once()


async def test_saved_answer_defers_the_helper_until_commit(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core import background
    from app.schemas.conversation import MessageCreate
    from app.services.conversation import ConversationService

    called = AsyncMock()
    monkeypatch.setattr(module, "write_next_steps", called)
    db = AsyncSession()
    service = ConversationService(db)
    conversation, org, message, run = [uuid4() for _ in range(4)]
    monkeypatch.setattr(
        service,
        "get_conversation",
        AsyncMock(
            return_value=SimpleNamespace(id=conversation, is_archived=False, project_id=None)
        ),
    )
    monkeypatch.setattr(
        module.conversation_repo,
        "create_message",
        AsyncMock(return_value=SimpleNamespace(id=message)),
    )
    await service.add_message(
        conversation,
        MessageCreate(role="assistant", content="Answer"),
        organization_id=org,
        run_id=run,
    )
    called.assert_not_awaited()
    background.start_deferred(db)
    await background.drain(timeout=1)
    called.assert_awaited_once_with(message, org)
    await db.close()


async def test_budget_refusal_never_calls_the_suggestion_model(monkeypatch):
    from decimal import Decimal

    from app.agents.capabilities.budget import BudgetScope, SpendLimit

    monkeypatch.setattr(module, "run_heartbeat", no_heartbeat)
    prepared = prepared_run()
    prepared.built.budget.limits = [
        SpendLimit(scope=BudgetScope.ORGANIZATION, limit_usd=Decimal(0))
    ]
    runner = SimpleNamespace(finish=AsyncMock())
    assert (
        await FollowUpService(AsyncMock())._generate(runner, prepared, "Question", "Answer") == []
    )
    assert prepared.built.ledger.input_tokens == 0
    assert runner.finish.await_args.kwargs["status"] == RunStatus.BUDGET_EXCEEDED
    assert runner.finish.await_args.kwargs["budget_scope"] == BudgetScope.ORGANIZATION
