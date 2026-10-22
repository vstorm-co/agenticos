"""Running a system agent for a typed result, and every way it refuses.

`AgentRunnerService.execute` is replaced: what it does with a budget, a guardrail
or a model is its own suite's subject. What is proven here is what the runner
asks it for and what it makes of each answer.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from app.agents.isolation import RunIsolation
from app.agents.system_agents import JUDGE
from app.core.exceptions import (
    AiAssistanceDisabledError,
    NotFoundError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import RunStatus, RunSurface
from app.services import system_agent_runner
from app.services.system_agent_runner import (
    SystemAgentRunner,
    _unreadable,
    output_contract,
    parse_output,
)

pytestmark = pytest.mark.anyio


class Verdict(BaseModel):
    passed: bool
    reason: str


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER)


def _agent(**overrides) -> MagicMock:
    values = {
        "id": uuid.uuid4(),
        "name": JUDGE.name,
        "status": AgentStatus.PUBLISHED.value,
        "current_version_id": uuid.uuid4(),
    }
    return MagicMock(**{**values, **overrides})


def _run(status: RunStatus = RunStatus.COMPLETED) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), status=status.value)


def _runner(
    monkeypatch,
    *,
    enabled: bool = True,
    agent: MagicMock | None = None,
    may_run: bool = True,
    answer: str = '{"passed": true, "reason": "cites the policy"}',
    run: MagicMock | None = None,
) -> tuple[SystemAgentRunner, AsyncMock]:
    runner = SystemAgentRunner(AsyncMock())
    monkeypatch.setattr(
        system_agent_runner.AiAssistanceService, "is_enabled", AsyncMock(return_value=enabled)
    )
    runner.agents.ensure = AsyncMock(return_value=agent or _agent())
    monkeypatch.setattr(system_agent_runner, "resolve_access", AsyncMock(return_value=may_run))
    monkeypatch.setattr(
        system_agent_runner.agent_repo,
        "get_version",
        AsyncMock(return_value=SimpleNamespace(spec={"model_profile_id": str(uuid.uuid4())})),
    )
    monkeypatch.setattr(system_agent_runner.ModelProfileService, "resolve", AsyncMock())
    execute = AsyncMock(return_value=(answer, run or _run()))
    monkeypatch.setattr(system_agent_runner.AgentRunnerService, "execute", execute)
    return runner, execute


class TestOutput:
    def test_the_contract_carries_the_result_schema(self) -> None:
        contract = output_contract(Verdict)

        assert '"passed"' in contract
        assert '"reason"' in contract

    def test_a_fenced_answer_is_read(self) -> None:
        answer = '```json\n{"passed": false, "reason": "wrong date"}\n```'

        assert parse_output(answer, Verdict) == Verdict(passed=False, reason="wrong date")

    def test_prose_is_not_an_answer(self) -> None:
        with pytest.raises(ValidationError):
            parse_output("It passes.", Verdict)


class TestRun:
    async def test_the_answer_comes_back_typed_with_its_run(self, monkeypatch) -> None:
        run = _run()
        runner, _ = _runner(monkeypatch, run=run)

        result = await runner.run(_ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict)

        assert result.output == Verdict(passed=True, reason="cites the policy")
        assert result.run is run

    async def test_it_runs_as_the_caller_on_the_eval_surface(self, monkeypatch) -> None:
        agent = _agent()
        profile_id = uuid.uuid4()
        runner, execute = _runner(monkeypatch, agent=agent)
        ctx = _ctx()

        await runner.run(
            ctx,
            key=JUDGE.key,
            prompt="Grade it",
            output_type=Verdict,
            model_profile_id=profile_id,
        )

        args, kwargs = execute.call_args
        assert args == (ctx, agent.id, f"Grade it\n\n{output_contract(Verdict)}")
        isolation = kwargs.pop("isolation")
        assert kwargs == {"surface": RunSurface.EVAL, "model_profile_id": profile_id}
        # Held like an eval's writes, and answered from no recording.
        assert isinstance(isolation, RunIsolation)
        assert (isolation.recording, isolation.intercepted) == (None, [])

    async def test_switched_off_nothing_runs(self, monkeypatch) -> None:
        runner, execute = _runner(monkeypatch, enabled=False)

        with pytest.raises(AiAssistanceDisabledError):
            await runner.run(_ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict)

        execute.assert_not_awaited()
        runner.agents.ensure.assert_not_awaited()

    @pytest.mark.parametrize(
        ("agent", "may_run", "reason"),
        [
            (_agent(status=AgentStatus.ARCHIVED.value), True, "archived"),
            (_agent(status=AgentStatus.DRAFT.value, current_version_id=None), True, "unpublished"),
            (_agent(), False, "no_access"),
        ],
    )
    async def test_an_agent_that_cannot_run_says_why(
        self, monkeypatch, agent, may_run, reason
    ) -> None:
        runner, execute = _runner(monkeypatch, agent=agent, may_run=may_run)

        with pytest.raises(SystemAgentUnavailableError) as raised:
            await runner.run(_ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict)

        assert raised.value.reason == reason
        execute.assert_not_awaited()

    async def test_a_runnable_agent_is_handed_back_without_a_run(self, monkeypatch) -> None:
        agent = _agent()
        runner, execute = _runner(monkeypatch, agent=agent)

        assert await runner.require_runnable(_ctx(), key=JUDGE.key) is agent
        execute.assert_not_awaited()

    async def test_an_unreachable_model_is_refused_before_any_run(self, monkeypatch) -> None:
        runner, execute = _runner(monkeypatch)
        monkeypatch.setattr(
            system_agent_runner.ModelProfileService,
            "resolve",
            AsyncMock(side_effect=NotFoundError(message="Model profile not found")),
        )

        with pytest.raises(SystemAgentUnavailableError) as raised:
            await runner.run(_ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict)

        assert raised.value.reason == "no_model"
        execute.assert_not_awaited()

    @pytest.mark.parametrize(
        "status",
        [RunStatus.BUDGET_EXCEEDED, RunStatus.GUARDRAIL_BLOCKED, RunStatus.AWAITING_APPROVAL],
    )
    async def test_a_run_that_ended_without_an_answer_names_its_run(
        self, monkeypatch, status
    ) -> None:
        run = _run(status)
        runner, _ = _runner(monkeypatch, answer="", run=run)

        with pytest.raises(SystemAgentRunError) as raised:
            await runner.run(_ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict)

        assert raised.value.run_id == run.id
        assert raised.value.status == status.value

    async def test_an_unreadable_answer_names_its_run_and_is_not_retried(self, monkeypatch) -> None:
        run = _run()
        runner, execute = _runner(monkeypatch, answer="Looks fine to me.", run=run)

        with pytest.raises(SystemAgentOutputError) as raised:
            await runner.run(_ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict)

        assert raised.value.run_id == run.id
        execute.assert_awaited_once()


def test_an_unreadable_answer_leaves_why_on_its_run_and_never_the_answer() -> None:
    class Shape(BaseModel):
        grades: list[int]

    with pytest.raises(ValidationError) as refused:
        Shape.model_validate_json('{"grades": ["the private question"]}')

    kept = _unreadable(refused.value)

    assert kept.startswith("The answer did not match the shape asked for - grades.0: ")
    assert "private question" not in kept
