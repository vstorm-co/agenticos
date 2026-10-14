"""A voice call is one run, prepared and finished like any other (#54)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


@pytest.mark.anyio
async def test_a_voice_run_never_opens_a_sandbox(runner_with_mocks):
    agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
    runner_with_mocks.runnable.return_value = (
        agent,
        AgentSpec(
            name="a",
            model_profile_id=uuid.uuid4(),
            capabilities=[CapabilityBindingSpec(id="sandbox")],
        ),
        agent.current_version_id,
    )

    await runner_with_mocks.service.prepare(_ctx(), agent.id, voice=_voice())

    opened_spec = runner_with_mocks.opened.call_args.args[0]
    assert opened_spec.capabilities == []
