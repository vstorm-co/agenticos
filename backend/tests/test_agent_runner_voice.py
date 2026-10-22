"""A voice call is one run, prepared and finished like any other (#54)."""

import uuid
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.toolsets import FunctionToolset

from app.agents.hand_off import HAND_OFF_TOOL
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.agents.voice import VoiceOptions
from app.core.permissions import AuthContext, OrgRoleName
from app.services.agent_runner import AgentRunnerService, PreparedRun, VoiceRun


def _prepared() -> PreparedRun:
    built = MagicMock()
    run = MagicMock(id=uuid.uuid4(), conversation_id=uuid.uuid4())
    return PreparedRun(
        run=run, agent=MagicMock(), spec=MagicMock(), built=built, approvals=MagicMock()
    )


def _voice(**overrides: Any) -> VoiceRun:
    values: dict[str, Any] = {
        "options": VoiceOptions(on_deferred=AsyncMock()),
        "model_label": "GPT Realtime (marin)",
        "provider": "openai",
        "secret_id": uuid.uuid4(),
    }
    values.update(overrides)
    return VoiceRun(**values)


@pytest.mark.security
def test_a_call_runs_with_no_request_limit_and_the_budget_as_cost_limit():
    """A session counts every response: a text run's request cap would end a call in minutes."""
    prepared = _prepared()

    prepared.realtime(MagicMock(), settings={}, message_history=[], cost_limit=Decimal("1.50"))

    kwargs = prepared.built.agent.realtime.call_args.kwargs
    assert kwargs["usage_limits"].request_limit is None
    assert kwargs["usage_limits"].cost_limit == Decimal("1.50")
    assert kwargs["run_id"] == str(prepared.run.id)
    assert kwargs["conversation_id"] == str(prepared.run.conversation_id)


def test_a_call_outside_a_conversation_names_none():
    prepared = _prepared()
    prepared.run.conversation_id = None

    prepared.realtime(MagicMock(), settings={}, message_history=[], cost_limit=None)

    assert prepared.built.agent.realtime.call_args.kwargs["conversation_id"] is None


@pytest.mark.anyio
async def test_answering_the_offer_is_metered_on_the_run(monkeypatch):
    prepared = _prepared()
    realtime = MagicMock(answer_webrtc_offer=AsyncMock(return_value="answer"))
    metered: list[object] = []

    @contextmanager
    def fake_meter(ledger):
        metered.append(ledger)
        yield

    monkeypatch.setattr("app.services.agent_runner.metered_by", fake_meter)
    assert await prepared.answer_offer(realtime, "v=0") == "answer"
    assert metered == [prepared.built.ledger]


@pytest.mark.anyio
async def test_the_session_keeps_no_audio_and_is_metered(monkeypatch):
    prepared = _prepared()
    opened: dict[str, object] = {}

    @asynccontextmanager
    async def session(**kwargs):
        opened.update(kwargs)
        yield "session"

    metered: list[object] = []

    @contextmanager
    def fake_meter(ledger):
        metered.append(ledger)
        yield

    monkeypatch.setattr("app.services.agent_runner.metered_by", fake_meter)
    provider_session = object()
    async with prepared.realtime_session(
        MagicMock(session=session), provider_session=provider_session
    ) as got:
        assert got == "session"

    assert opened == {"provider_session": provider_session, "audio_retention": "transcript_only"}
    assert metered == [prepared.built.ledger]


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _db() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.get = AsyncMock(return_value=MagicMock(monthly_budget_usd=None))
    return db


@pytest.fixture(autouse=True)
def _in_no_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nobody here is in a group; `test_prompt_variables` covers `{{groups}}`."""
    monkeypatch.setattr(
        "app.services.agent_runner.group_repo.names_for_member", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "app.services.agent_runner.group_repo.capped_groups_for_member",
        AsyncMock(return_value=[]),
    )


@pytest.fixture
def runner_with_mocks():
    service = AgentRunnerService(_db())
    agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
    spec = AgentSpec(name="Support", model_profile_id=uuid.uuid4())
    with (
        patch.object(
            service.registry,
            "get_runnable_spec",
            new=AsyncMock(return_value=(agent, spec, agent.current_version_id)),
        ) as runnable,
        patch.object(
            service.models,
            "resolve",
            new=AsyncMock(
                return_value=MagicMock(label="gpt-4.1", provider="openai", secret_id=uuid.uuid4())
            ),
        ),
        patch.object(service.skills, "resolve_for_agent", new=AsyncMock(return_value=[])),
        patch.object(service.workspaces, "open", new=AsyncMock(return_value=None)) as opened,
        patch(
            "app.services.agent_runner.agent_run_repo.create_run",
            new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        ) as create_run,
        patch("app.services.agent_runner.build_agent", return_value=MagicMock()) as build_agent,
    ):
        yield SimpleNamespace(
            service=service,
            runnable=runnable,
            opened=opened,
            create_run=create_run,
            build_agent=build_agent,
        )


@pytest.mark.anyio
async def test_a_voice_run_row_names_the_realtime_model_and_its_key(runner_with_mocks):
    voice = _voice()

    await runner_with_mocks.service.prepare(_ctx(), uuid.uuid4(), voice=voice)

    kwargs = runner_with_mocks.create_run.call_args.kwargs
    assert (kwargs["model_label"], kwargs["provider"], kwargs["secret_id"], kwargs["modality"]) == (
        "GPT Realtime (marin)",
        "openai",
        voice.secret_id,
        "voice",
    )
    assert runner_with_mocks.build_agent.call_args.kwargs["voice"] is voice.options


@pytest.mark.anyio
async def test_a_text_run_stays_text(runner_with_mocks):
    await runner_with_mocks.service.prepare(_ctx(), uuid.uuid4())

    kwargs = runner_with_mocks.create_run.call_args.kwargs
    assert (kwargs["model_label"], kwargs["modality"]) == ("gpt-4.1", "text")
    assert runner_with_mocks.build_agent.call_args.kwargs["voice"] is None


def _runnable(runner_with_mocks: SimpleNamespace, *capability_ids: str) -> MagicMock:
    agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
    runner_with_mocks.runnable.return_value = (
        agent,
        AgentSpec(
            name="a",
            model_profile_id=uuid.uuid4(),
            capabilities=[CapabilityBindingSpec(id=cap) for cap in capability_ids],
        ),
        agent.current_version_id,
    )
    return agent


def _tool_names(toolsets: list[Any]) -> set[str]:
    return {
        name
        for toolset in toolsets
        if isinstance(toolset, FunctionToolset)
        for name in toolset.tools
    }


@pytest.mark.anyio
async def test_a_call_opens_the_sandbox_for_its_text_twin_and_hands_work_to_it(runner_with_mocks):
    """The realtime model cannot carry a workspace; the twin it hands off to can."""
    agent = _runnable(runner_with_mocks, "sandbox", "clock")
    voice = _voice()

    prepared = await runner_with_mocks.service.prepare(_ctx(), agent.id, voice=voice)

    opened_spec = runner_with_mocks.opened.call_args.args[0]
    assert [binding.id for binding in opened_spec.capabilities] == ["sandbox", "clock"]
    call_build = runner_with_mocks.build_agent.call_args.kwargs
    assert call_build["voice"] is voice.options
    assert HAND_OFF_TOOL in _tool_names(call_build["extra_toolsets"])
    assert prepared.hand_off is not None


@pytest.mark.security
@pytest.mark.anyio
async def test_the_twin_is_the_agents_text_run_settling_approvals_with_the_caller(
    runner_with_mocks,
):
    agent = _runnable(runner_with_mocks, "sandbox")
    voice = _voice()
    prepared = await runner_with_mocks.service.prepare(_ctx(), agent.id, voice=voice)
    assert prepared.hand_off is not None

    prepared.hand_off._build()

    twin = runner_with_mocks.build_agent.call_args
    assert twin.kwargs["answering_call"] is voice.options
    assert "voice" not in twin.kwargs
    assert [binding.id for binding in twin.args[0].capabilities] == ["sandbox"]
    assert HAND_OFF_TOOL not in _tool_names(twin.kwargs["extra_toolsets"])


@pytest.mark.anyio
async def test_a_hand_off_is_a_row_of_its_own_on_the_text_model_and_key(runner_with_mocks):
    """Codex on #2204: the twin's spend was attributed to the realtime provider and key."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.agents.capabilities.budget import SpendShare
    from app.agents.hand_off import HandOffSpend
    from app.db.models.agent_run import RunStatus

    agent = _runnable(runner_with_mocks, "sandbox")
    prepared = await runner_with_mocks.service.prepare(_ctx(), agent.id, voice=_voice())
    assert prepared.hand_off is not None and prepared.hand_off._report is not None
    now = datetime.now(UTC)

    prepared.hand_off._report(
        HandOffSpend(
            task_id="hand-off-1",
            share=SpendShare(cost_usd=Decimal("0.03"), input_tokens=10, output_tokens=5),
            started_at=now,
            ended_at=now,
            error=None,
        )
    )
    prepared.hand_off._report(
        HandOffSpend(
            task_id="hand-off-2",
            share=SpendShare(),
            started_at=now,
            ended_at=now,
            error="the model failed",
        )
    )

    done, failed = prepared.delegations
    model = runner_with_mocks.build_agent.call_args.args[1]
    assert (done.task_id, done.cost_usd, done.status) == (
        "hand-off-1",
        Decimal("0.03"),
        RunStatus.COMPLETED,
    )
    assert (done.provider, done.secret_id, done.agent_id) == (
        model.provider,
        model.secret_id,
        agent.id,
    )
    assert failed.status is RunStatus.FAILED and failed.error == "the model failed"


@pytest.mark.anyio
async def test_a_hand_off_on_a_run_with_no_version_stays_on_the_calls_row(runner_with_mocks):
    from datetime import UTC, datetime

    from app.agents.capabilities.budget import SpendShare
    from app.agents.hand_off import HandOffSpend

    agent = _runnable(runner_with_mocks, "sandbox")
    prepared = await runner_with_mocks.service.prepare(_ctx(), agent.id, voice=_voice())
    assert prepared.hand_off is not None and prepared.hand_off._report is not None
    prepared.run.agent_version_id = None
    now = datetime.now(UTC)

    prepared.hand_off._report(
        HandOffSpend(task_id="h", share=SpendShare(), started_at=now, ended_at=now, error=None)
    )

    assert prepared.delegations == []


@pytest.mark.anyio
async def test_a_call_with_nothing_to_hand_off_has_no_twin(runner_with_mocks):
    agent = _runnable(runner_with_mocks, "clock")

    prepared = await runner_with_mocks.service.prepare(_ctx(), agent.id, voice=_voice())

    assert prepared.hand_off is None
    assert not _tool_names(runner_with_mocks.build_agent.call_args.kwargs["extra_toolsets"])


@pytest.mark.anyio
async def test_a_text_run_has_no_twin_whatever_it_binds(runner_with_mocks):
    agent = _runnable(runner_with_mocks, "sandbox")

    prepared = await runner_with_mocks.service.prepare(_ctx(), agent.id)

    assert prepared.hand_off is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("voice", "contexts"),
    [
        (True, ["worker", "worker", "pooled", "pooled"]),
        (False, ["worker", "worker", "worker", "worker"]),
    ],
)
async def test_a_calls_start_reads_its_baselines_off_the_pool_and_its_heartbeats_on_it(
    runner_with_mocks, voice, contexts
):
    """A call re-reads them every heartbeat: a new engine and connection each time does not
    scale. Its first read is the start's, made while the starter's own transaction holds a
    pooled connection: a second checkout from that pool there waits on a pool the starts
    themselves exhaust (RR-q14)."""
    opened: list[str] = []

    def _context(name: str):
        @asynccontextmanager
        async def context():
            opened.append(name)
            yield MagicMock()

        return context

    with (
        patch("app.services.agent_runner.get_db_context", _context("pooled")),
        patch("app.services.agent_runner.get_worker_db_context", _context("worker")),
        patch(
            "app.services.agent_runner.agent_run_repo.sum_cost_since",
            new=AsyncMock(return_value=Decimal("1")),
        ),
        patch(
            "app.services.agent_runner.organization_monthly_spend",
            new=AsyncMock(return_value=Decimal("2")),
        ),
    ):
        await runner_with_mocks.service.prepare(
            _ctx(), uuid.uuid4(), voice=_voice() if voice else None
        )
        kwargs = runner_with_mocks.build_agent.call_args.kwargs
        for _ in range(2):  # the start's read, then a heartbeat's
            assert await kwargs["agent_period_spend"]() == Decimal("1")
            assert await kwargs["org_period_spend"]() == Decimal("2")

    assert opened == contexts
