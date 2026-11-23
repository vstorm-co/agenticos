"""Maintenance preparation, snapshot checks, and terminal accounting."""

from collections.abc import Callable
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import RunContext

from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.exceptions import BadRequestError
from app.db.models.agent_run import RunStatus
from app.services import agent_runner as runner_module
from app.services.agent_runner import AgentRunnerService, _compaction_only
from app.services.message_history import ModelHistory
from tests.test_manual_conversation_compaction import (
    AGENT,
    CONVERSATION,
    _prepared_compaction,
    _runner_harness,
)

pytestmark = pytest.mark.anyio


def _history() -> ModelHistory:
    return ModelHistory(
        [ModelRequest(parts=[UserPromptPart(content="remember this")])], revision=4, ordinal=9
    )


def test_maintenance_spec_removes_tools_and_disabled_bindings_without_mutating_the_published_spec() -> (
    None
):
    spec = AgentSpec(
        name="support",
        model_profile_id=uuid4(),
        capabilities=[
            CapabilityBindingSpec(id="compaction"),
            CapabilityBindingSpec(id="guardrails"),
            CapabilityBindingSpec(id="thinking"),
            CapabilityBindingSpec(id="media"),
            CapabilityBindingSpec(id="sandbox"),
            CapabilityBindingSpec(id="skills", enabled=False),
        ],
        skill_ids=[uuid4()],
        collection_ids=[uuid4()],
    )
    maintenance = _compaction_only(spec)
    assert [binding.id for binding in maintenance.capabilities] == [
        "compaction",
        "guardrails",
        "thinking",
        "media",
    ]
    assert (
        maintenance.skill_ids
        == maintenance.collection_ids
        == maintenance.mcp_servers
        == maintenance.subagents
        == maintenance.external_agents
        == []
    )
    assert len(spec.capabilities) == 6
    assert spec.skill_ids and spec.collection_ids


@pytest.mark.parametrize("strategy", [None, "sliding_window", "clear_tool_results"])
async def test_unsupported_published_policy_is_refused_before_history_or_model_access(
    monkeypatch: pytest.MonkeyPatch, strategy: str | None
) -> None:
    history = _history()
    prepared, _ = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    service, conversations, db, ctx = _runner_harness(monkeypatch, history, prepared)
    bindings = (
        []
        if strategy is None
        else [SimpleNamespace(id="compaction", enabled=True, config={"strategy": strategy})]
    )
    service.registry.get_runnable_spec.return_value = (
        object(),
        SimpleNamespace(capabilities=bindings),
        None,
    )
    with pytest.raises(BadRequestError, match="not configured for summarising"):
        await service.compact_conversation(ctx, CONVERSATION, AGENT)
    conversations.model_history.assert_not_awaited()
    service.prepare.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_empty_history_needs_no_maintenance_row_or_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = ModelHistory([], revision=4, ordinal=9)
    prepared, _ = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    service, conversations, db, ctx = _runner_harness(monkeypatch, history, prepared)
    assert await service.compact_conversation(ctx, CONVERSATION, AGENT) is False
    service.prepare.assert_not_awaited()
    conversations.keep_summary_snapshot.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("fault", ["ordinal", "unbounded", "compactor", "workspace", "capability"])
async def test_invalid_prepared_maintenance_is_settled_without_replacing_the_saved_summary(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    history = _history()
    prepared, compactor = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    service, conversations, db, ctx = _runner_harness(monkeypatch, history, prepared)
    error: type[Exception] = RuntimeError
    match = "bounded history snapshot"
    if fault == "ordinal":
        conversations.history_for_provenance.return_value = ModelHistory(
            list(history), revision=4, ordinal=None
        )
        conversations.history_for_provenance.side_effect = None
    elif fault == "unbounded":
        conversations.history_for_provenance.return_value = list(history)
        conversations.history_for_provenance.side_effect = None
    elif fault == "compactor":
        prepared.built.capabilities = []
        error, match = BadRequestError, "no summarising compaction"
    elif fault == "workspace":
        prepared.workspace = MagicMock()
        match = "unexpectedly opened a workspace"
    else:
        prepared.built.capabilities.append(object())
        error, match = TypeError, "unprepared capability"
    with pytest.raises(error, match=match):
        await service.compact_conversation(ctx, CONVERSATION, AGENT)
    compactor.compact_now.assert_not_awaited()
    conversations.keep_summary_snapshot.assert_not_awaited()
    assert service.finish_compaction.await_args.kwargs["status"] is RunStatus.FAILED
    assert db.commit.await_count == (2 if fault == "capability" else 1)


class _ContextSettings(AbstractCapability[AgentDeps]):
    def get_model_settings(self) -> Callable[[RunContext[AgentDeps]], ModelSettings | None]:
        def settings(ctx: RunContext[AgentDeps]) -> ModelSettings:
            assert ctx.messages
            return ModelSettings(temperature=0.4)

        return settings


async def test_callable_capability_settings_reach_the_manual_summarizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = _history()
    prepared, compactor = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    prepared.built.capabilities.append(_ContextSettings())
    service, _, _, ctx = _runner_harness(monkeypatch, history, prepared)
    assert await service.compact_conversation(ctx, CONVERSATION, AGENT) is True
    assert compactor.compact_now.await_args.args[1].model_settings["temperature"] == 0.4


@pytest.mark.parametrize("summarized,output", [(False, True), (True, False)])
async def test_a_summary_is_not_saved_without_both_a_summary_signal_and_output(
    monkeypatch: pytest.MonkeyPatch, summarized: bool, output: bool
) -> None:
    history = _history()
    prepared, compactor = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    prepared.built.context.summarized = summarized
    if not output:
        compactor.compact_now.return_value = None
    service, conversations, _, ctx = _runner_harness(monkeypatch, history, prepared)
    assert await service.compact_conversation(ctx, CONVERSATION, AGENT) is False
    conversations.keep_summary_snapshot.assert_not_awaited()
    assert service.finish_compaction.await_args.kwargs["status"] is RunStatus.COMPLETED


@pytest.mark.parametrize(
    "previous_fallback,serving", [(False, None), (True, "earlier-fallback"), (False, "test")]
)
async def test_terminal_maintenance_keeps_prior_fallback_and_repair_accounting(
    monkeypatch: pytest.MonkeyPatch, previous_fallback: bool, serving: str | None
) -> None:
    history = _history()
    prepared, _ = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    prepared.run.fallback_used = previous_fallback
    prepared.run.serving_model = serving
    prepared.run.tool_args_repaired = 2
    prepared.built.primary_model = "test"
    if serving == "test":
        prepared.built.recorder.requests = [SimpleNamespace(model="test", failed=None, cache=None)]
    prepared.built.repairs.count = 3
    finish = AsyncMock(return_value=prepared.run)
    monkeypatch.setattr(runner_module.agent_run_repo, "finish_run", finish)
    service = AgentRunnerService(MagicMock())
    result = await service.finish_compaction(
        prepared, status=RunStatus.FAILED, error="summary failed"
    )
    assert result is prepared.run
    saved = finish.await_args.kwargs
    assert saved["status"] == "failed"
    assert saved["error"] == "summary failed"
    assert saved["fallback_used"] is previous_fallback
    assert saved["serving_model"] == serving
    assert saved["tool_args_repaired"] == 5
    assert saved["cost_usd"] == Decimal(0)
    assert saved["paused_state"] is None


@pytest.mark.parametrize(
    "strategy,aside",
    [
        (None, False),
        ("sliding_window", False),
        ("summarize", True),
        ("summarize", False),
        ("tiered", False),
    ],
)
async def test_preparation_accepts_only_summary_maintenance_without_a_side_question(
    monkeypatch: pytest.MonkeyPatch, strategy: str | None, aside: bool
) -> None:
    history = _history()
    prepared, _ = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    service, _, _, ctx = _runner_harness(monkeypatch, history, prepared)
    # Exercise the real prepare method; the shared harness replaces it for execution tests.
    monkeypatch.delattr(service, "prepare")
    spec = AgentSpec(
        name="support",
        model_profile_id=uuid4(),
        capabilities=[]
        if strategy is None
        else [
            CapabilityBindingSpec(id="compaction", config={"strategy": strategy}),
            CapabilityBindingSpec(id="sandbox"),
        ],
    )
    service.registry.get_runnable_spec.return_value = (SimpleNamespace(id=AGENT), spec, uuid4())
    monkeypatch.setattr(service, "_with_environment_observability", AsyncMock(return_value=spec))
    assemble = AsyncMock(return_value=prepared)
    monkeypatch.setattr(service, "_assemble", assemble)
    if strategy in {"summarize", "tiered"} and not aside:
        assert await service.prepare(ctx, AGENT, compaction_only=True) is prepared
        assert [item.id for item in assemble.await_args.kwargs["spec"].capabilities] == [
            "compaction"
        ]
    else:
        with pytest.raises(
            BadRequestError, match="side question" if aside else "not configured for summarising"
        ):
            await service.prepare(ctx, AGENT, compaction_only=True, aside=aside)
        assemble.assert_not_awaited()
