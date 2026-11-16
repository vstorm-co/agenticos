"""Running a system agent for a typed result, and every way it refuses.

`AgentRunnerService.execute` is replaced: what it does with a budget, a guardrail
or a model is its own suite's subject. What is proven here is what the runner
asks it for and what it makes of each answer.
"""

import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from app.agents.isolation import RunIsolation
from app.agents.system_agents import IMPROVER, JUDGE
from app.core.exceptions import (
    NotFoundError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.resource_grant import GrantLevel, Visibility
from app.repositories import resource_grant_repo
from app.services import access, system_agent_runner
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
    agent: MagicMock | None = None,
    may_run: bool = True,
    answer: str = '{"passed": true, "reason": "cites the policy"}',
    run: MagicMock | None = None,
) -> tuple[SystemAgentRunner, AsyncMock]:
    runner = SystemAgentRunner(AsyncMock())
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

        bases = [uuid.uuid4()]

        await runner.run(
            ctx,
            key=JUDGE.key,
            prompt="Grade it",
            output_type=Verdict,
            model_profile_id=profile_id,
            knowledge_base_ids=bases,
        )

        args, kwargs = execute.call_args
        assert args == (ctx, agent.id, f"Grade it\n\n{output_contract(Verdict)}")
        isolation = kwargs.pop("isolation")
        assert kwargs == {
            "surface": RunSurface.EVAL,
            "model_profile_id": profile_id,
            "candidate": None,
            "reports_failure": True,
        }
        # Held like an eval's writes, answered from no recording, and searching
        # only the knowledge bases the caller picked for the run.
        assert isinstance(isolation, RunIsolation)
        assert (isolation.recording, isolation.intercepted) == (None, [])
        assert isolation.knowledge is not None
        assert isolation.knowledge.knowledge_base_ids == tuple(bases)

    async def test_dataset_instructions_and_model_are_passed_without_changing_the_published_agent(
        self, monkeypatch
    ) -> None:
        agent = _agent()
        runner, execute = _runner(monkeypatch, agent=agent)
        model_id = uuid.uuid4()
        await runner.run(
            _ctx(),
            key=JUDGE.key,
            prompt="Grade it",
            output_type=Verdict,
            model_profile_id=model_id,
            instructions="Use this dataset's policy.",
        )
        candidate = execute.call_args.kwargs["candidate"]
        assert candidate.version_id == agent.current_version_id
        assert candidate.instructions == "Use this dataset's policy."
        assert execute.call_args.kwargs["model_profile_id"] == model_id
        runner.agents.ensure.assert_awaited_once()

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


@pytest.fixture
def chosen_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AuthContext, MagicMock, SystemAgentRunner, AsyncMock]:
    ctx = _ctx()
    helper = _agent(
        kind=IMPROVER.kind.value,
        organization_id=ctx.organization_id,
        owner_user_id=uuid.uuid4(),
        visibility=Visibility.PRIVATE.value,
    )
    runner, execute = _runner(monkeypatch, agent=helper)
    monkeypatch.setattr(system_agent_runner, "resolve_access", access.resolve_access)
    monkeypatch.setattr(system_agent_runner.agent_repo, "get", AsyncMock(return_value=helper))
    monkeypatch.setattr(resource_grant_repo, "get_level", AsyncMock(return_value=None))
    return ctx, helper, runner, execute


class TestChosenHelper:
    @pytest.mark.security
    @pytest.mark.parametrize(
        "unavailable",
        ["private", "missing", "foreign", "no_subject", "run_only_key", "archived", "wrong_kind"],
    )
    async def test_an_unreadable_helper_is_missing_before_its_settings_are_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        chosen_helper: tuple[AuthContext, MagicMock, SystemAgentRunner, AsyncMock],
        unavailable: str,
    ) -> None:
        ctx, helper, runner, execute = chosen_helper
        if unavailable == "missing":
            monkeypatch.setattr(system_agent_runner.agent_repo, "get", AsyncMock(return_value=None))
        elif unavailable == "foreign":
            helper.organization_id = uuid.uuid4()
        elif unavailable == "no_subject":
            ctx = replace(ctx, user_id=None, role=OrgRoleName.OWNER)
        elif unavailable == "run_only_key":
            ctx = replace(ctx, key_scopes=frozenset({Perm.AGENTS_RUN}))
            monkeypatch.setattr(
                resource_grant_repo, "get_level", AsyncMock(return_value=GrantLevel.USE)
            )
        elif unavailable == "archived":
            helper.status = AgentStatus.ARCHIVED.value
        elif unavailable == "wrong_kind":
            helper.kind = JUDGE.kind.value

        with pytest.raises(NotFoundError) as raised:
            await runner.run(
                ctx, key=IMPROVER.key, prompt="Improve it", output_type=Verdict, agent_id=helper.id
            )

        assert raised.value.status_code == 404
        assert raised.value.details == {"agent_id": helper.id}
        system_agent_runner.agent_repo.get.assert_awaited_once_with(
            runner.db, helper.id, organization_id=ctx.organization_id
        )
        system_agent_runner.agent_repo.get_version.assert_not_awaited()
        system_agent_runner.ModelProfileService.resolve.assert_not_awaited()
        execute.assert_not_awaited()

    @pytest.mark.parametrize("access_via", ["owner", "organization", "grant"])
    async def test_a_readable_runnable_helper_can_be_chosen(
        self,
        monkeypatch: pytest.MonkeyPatch,
        chosen_helper: tuple[AuthContext, MagicMock, SystemAgentRunner, AsyncMock],
        access_via: str,
    ) -> None:
        ctx, helper, runner, execute = chosen_helper
        if access_via == "owner":
            helper.owner_user_id = ctx.user_id
        elif access_via == "organization":
            helper.visibility = Visibility.ORG.value
        else:
            monkeypatch.setattr(
                resource_grant_repo, "get_level", AsyncMock(return_value=GrantLevel.USE)
            )

        result = await runner.run(
            ctx, key=IMPROVER.key, prompt="Improve it", output_type=Verdict, agent_id=helper.id
        )

        assert result.output == Verdict(passed=True, reason="cites the policy")
        assert execute.call_args.args[:2] == (ctx, helper.id)
        execute.assert_awaited_once()
        runner.agents.ensure.assert_not_awaited()

    @pytest.mark.security
    async def test_a_read_grant_does_not_allow_running_the_helper(
        self,
        monkeypatch: pytest.MonkeyPatch,
        chosen_helper: tuple[AuthContext, MagicMock, SystemAgentRunner, AsyncMock],
    ) -> None:
        ctx, helper, runner, execute = chosen_helper
        monkeypatch.setattr(
            resource_grant_repo, "get_level", AsyncMock(return_value=GrantLevel.READ)
        )

        with pytest.raises(SystemAgentUnavailableError) as raised:
            await runner.run(
                ctx, key=IMPROVER.key, prompt="Improve it", output_type=Verdict, agent_id=helper.id
            )

        assert raised.value.reason == "no_access"
        system_agent_runner.agent_repo.get_version.assert_not_awaited()
        execute.assert_not_awaited()

    async def test_a_visible_helper_of_the_wrong_kind_still_says_it_cannot_run(
        self, chosen_helper: tuple[AuthContext, MagicMock, SystemAgentRunner, AsyncMock]
    ) -> None:
        ctx, helper, runner, execute = chosen_helper
        helper.visibility = Visibility.ORG.value
        helper.kind = JUDGE.kind.value

        with pytest.raises(SystemAgentUnavailableError) as raised:
            await runner.run(
                ctx, key=IMPROVER.key, prompt="Improve it", output_type=Verdict, agent_id=helper.id
            )

        assert raised.value.reason == "missing"
        execute.assert_not_awaited()


def test_an_unreadable_answer_leaves_why_on_its_run_and_never_the_answer() -> None:
    class Shape(BaseModel):
        grades: list[int]

    with pytest.raises(ValidationError) as refused:
        Shape.model_validate_json('{"grades": ["the private question"]}')

    kept = _unreadable(refused.value)

    assert kept.startswith("The answer did not match the shape asked for - grades.0: ")
    assert "private question" not in kept


async def test_a_pinned_system_agent_runs_the_selected_publication(monkeypatch) -> None:
    from app.services.agent_registry import PublishedCandidate

    agent = _agent()
    runner, execute = _runner(monkeypatch, agent=agent)
    pinned = uuid.uuid4()
    monkeypatch.setattr(
        system_agent_runner.agent_repo,
        "get_version",
        AsyncMock(
            return_value=SimpleNamespace(
                agent_id=agent.id, spec={"model_profile_id": str(uuid.uuid4())}
            )
        ),
    )
    await runner.run(
        _ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict, version_id=pinned
    )
    assert execute.call_args.kwargs["candidate"] == PublishedCandidate(version_id=pinned)


@pytest.mark.parametrize("missing", [True, False])
async def test_a_missing_or_foreign_pinned_version_never_runs_the_current_judge(
    monkeypatch, missing: bool
) -> None:
    runner, execute = _runner(monkeypatch)
    monkeypatch.setattr(
        system_agent_runner.agent_repo,
        "get_version",
        AsyncMock(return_value=(None if missing else SimpleNamespace(agent_id=uuid.uuid4()))),
    )
    with pytest.raises(SystemAgentUnavailableError, match="pinned version"):
        await runner.run(
            _ctx(), key=JUDGE.key, prompt="Grade it", output_type=Verdict, version_id=uuid.uuid4()
        )
    execute.assert_not_awaited()
