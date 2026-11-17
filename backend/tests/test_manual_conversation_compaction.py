"""Server-side invariants for idle conversation compaction."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel

from app.agents.capabilities.budget import BudgetExceeded, BudgetScope, SpendLedger
from app.agents.capabilities.compaction import (
    CompactionConfig,
    ContextGauge,
    MeteredCompaction,
    build_strategy,
)
from app.agents.compaction_events import CompactionEvent
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunStatus
from app.repositories import conversation as conversation_repo
from app.schemas.conversation import ConversationCompactionAvailability
from app.services import agent_runner as agent_runner_module
from app.services import agent_session as agent_session_module
from app.services.agent_runner import AgentRunnerService, PreparedRun
from app.services.agent_session import AgentSession, _CompactNowRequest
from app.services.message_history import ModelHistory

pytestmark = pytest.mark.anyio

PERSON, ORG, CONVERSATION, AGENT = uuid4(), uuid4(), uuid4(), uuid4()


def _session() -> AgentSession:
    user = MagicMock(id=PERSON)
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    session = AgentSession(websocket, user, SimpleNamespace(id=ORG))
    session._room = str(CONVERSATION)
    return session


def _events(session: AgentSession) -> list[tuple[str, dict]]:
    return [
        (call.args[0]["type"], call.args[0]["data"])
        for call in session.websocket.send_json.call_args_list
    ]


def _install_session_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    session: AgentSession,
    *,
    conversation: object | None = None,
    unfinished: list[bool] | None = None,
    room_submissions: list[bool] | None = None,
    claim_available: bool = True,
) -> dict[str, object]:
    db = MagicMock()
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=OrgRoleName.OWNER)
    stored = conversation or SimpleNamespace(
        user_id=PERSON,
        project_id=None,
        workflow_id=None,
        origin=None,
        is_archived=False,
    )
    conversation_service = MagicMock()
    conversation_service.get_conversation = AsyncMock(return_value=stored)

    @asynccontextmanager
    async def db_context() -> AsyncIterator[MagicMock]:
        yield db

    @asynccontextmanager
    async def admission(conversation_id, *, background: bool):
        assert conversation_id == CONVERSATION
        assert background is True
        if not claim_available:
            yield False
            return
        claim_state["held"] = True
        try:
            yield True
        finally:
            claim_state["held"] = False
            claim_state["released"] = True

    claim_state: dict[str, bool] = {"held": False, "released": False}
    runner = MagicMock()

    async def compact(*_args, on_compaction, **_kwargs):
        assert claim_state["held"] is True
        await on_compaction(CompactionEvent(kind="compaction_started", messages_before=6))
        return True

    runner.compact_conversation = AsyncMock(side_effect=compact)
    monkeypatch.setattr(agent_session_module, "get_db_context", db_context)
    monkeypatch.setattr(session, "_chat_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(
        agent_session_module, "ConversationService", lambda _db: conversation_service
    )
    monkeypatch.setattr(
        agent_session_module,
        "AgentRunnerService",
        lambda _db: runner,
    )
    monkeypatch.setattr(
        conversation_repo,
        "has_unfinished_runs",
        AsyncMock(side_effect=unfinished or [False, False]),
    )
    monkeypatch.setattr(
        conversation_repo,
        "has_room_submissions",
        AsyncMock(side_effect=room_submissions or [False, False]),
    )
    from app.services import conversation_turns

    monkeypatch.setattr(conversation_turns, "claim", admission)
    return {
        "conversation_service": conversation_service,
        "runner": runner,
        "claim_state": claim_state,
    }


async def test_compaction_availability_uses_owner_write_access_and_published_summary_policy():
    from app.api.routes.v1.conversations import compaction_availability

    conversation_service = MagicMock()
    conversation_service.get_conversation = AsyncMock(
        return_value=SimpleNamespace(
            user_id=PERSON,
            project_id=None,
            workflow_id=None,
            origin=None,
            is_archived=False,
        )
    )
    registry = MagicMock()
    registry.get_runnable_spec = AsyncMock(
        return_value=(
            object(),
            SimpleNamespace(
                capabilities=[
                    SimpleNamespace(id="compaction", enabled=True, config={"strategy": "tiered"})
                ]
            ),
            None,
        )
    )
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=OrgRoleName.OWNER)

    result = await compaction_availability(
        CONVERSATION,
        conversation_service,
        registry,
        ctx,
        SimpleNamespace(id=PERSON),
        SimpleNamespace(id=ORG),
        AGENT,
    )

    assert result == ConversationCompactionAvailability(available=True)
    assert conversation_service.get_conversation.await_args.kwargs == {
        "organization_id": ORG,
        "user_id": PERSON,
        "for_write": True,
        "turn": True,
        "include_favourite": False,
        "ctx": ctx,
    }
    registry.get_runnable_spec.assert_awaited_once_with(ctx, AGENT)


@pytest.mark.parametrize(
    "conversation",
    [
        SimpleNamespace(
            user_id=uuid4(), project_id=None, workflow_id=None, origin=None, is_archived=False
        ),
        SimpleNamespace(
            user_id=PERSON, project_id=uuid4(), workflow_id=None, origin=None, is_archived=False
        ),
        SimpleNamespace(
            user_id=PERSON, project_id=None, workflow_id=uuid4(), origin=None, is_archived=False
        ),
        SimpleNamespace(
            user_id=PERSON, project_id=None, workflow_id=None, origin="manual", is_archived=False
        ),
        SimpleNamespace(
            user_id=PERSON, project_id=None, workflow_id=None, origin=None, is_archived=True
        ),
    ],
)
async def test_compaction_availability_refuses_unowned_or_nonpersonal_chats(conversation):
    from app.api.routes.v1.conversations import compaction_availability

    conversation_service = MagicMock()
    conversation_service.get_conversation = AsyncMock(return_value=conversation)
    registry = MagicMock()
    registry.get_runnable_spec = AsyncMock()
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=OrgRoleName.OWNER)

    result = await compaction_availability(
        CONVERSATION,
        conversation_service,
        registry,
        ctx,
        SimpleNamespace(id=PERSON),
        SimpleNamespace(id=ORG),
        AGENT,
    )

    assert result.available is False
    registry.get_runnable_spec.assert_not_awaited()


async def test_compaction_availability_hides_unsupported_policy_and_agent_permissions():
    from app.api.routes.v1.conversations import compaction_availability

    conversation_service = MagicMock()
    conversation_service.get_conversation = AsyncMock(
        return_value=SimpleNamespace(
            user_id=PERSON,
            project_id=None,
            workflow_id=None,
            origin=None,
            is_archived=False,
        )
    )
    registry = MagicMock()
    registry.get_runnable_spec = AsyncMock(
        side_effect=[
            (
                object(),
                SimpleNamespace(
                    capabilities=[
                        SimpleNamespace(
                            id="compaction", enabled=True, config={"strategy": "sliding_window"}
                        )
                    ]
                ),
                None,
            ),
            AuthorizationError(message="Agent run permission required"),
        ]
    )
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=OrgRoleName.OWNER)
    args = (
        CONVERSATION,
        conversation_service,
        registry,
        ctx,
        SimpleNamespace(id=PERSON),
        SimpleNamespace(id=ORG),
        AGENT,
    )

    assert (await compaction_availability(*args)).available is False
    assert (await compaction_availability(*args)).available is False


async def test_owned_compaction_correlates_progress_and_result_and_releases_the_lease(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session()
    dependencies = _install_session_dependencies(monkeypatch, session)
    request = _CompactNowRequest(
        request_id="request-1",
        conversation_id=CONVERSATION,
        agent_id=AGENT,
    )

    await session._run_compaction(request)

    events = _events(session)
    progress = next(data for kind, data in events if kind == "compaction_started")
    result = next(data for kind, data in events if kind == "compact_now_result")
    assert progress["request_id"] == "request-1"
    assert result == {
        "request_id": "request-1",
        "conversation_id": str(CONVERSATION),
        "status": "compacted",
    }
    assert events[-1] == ("session_ready", {"conversation_id": str(CONVERSATION)})
    assert dependencies["claim_state"] == {"held": False, "released": True}
    assert dependencies["conversation_service"].get_conversation.await_count == 2
    assert dependencies["runner"].compact_conversation.await_args.kwargs["model_profile_id"] is None


async def test_parked_resumable_run_is_rechecked_inside_the_exclusive_claim(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session()
    dependencies = _install_session_dependencies(monkeypatch, session, unfinished=[False, True])

    await session._run_compaction(
        _CompactNowRequest(request_id="parked", conversation_id=CONVERSATION, agent_id=AGENT)
    )

    assert (
        next(data for kind, data in _events(session) if kind == "compact_now_result")["status"]
        == "busy"
    )
    assert dependencies["claim_state"] == {"held": False, "released": True}
    dependencies["runner"].compact_conversation.assert_not_awaited()


async def test_parked_resumable_run_blocks_compaction_before_claim(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session()
    dependencies = _install_session_dependencies(monkeypatch, session, unfinished=[True])

    await session._run_compaction(
        _CompactNowRequest(request_id="parked", conversation_id=CONVERSATION, agent_id=AGENT)
    )

    assert (
        next(data for kind, data in _events(session) if kind == "compact_now_result")["status"]
        == "busy"
    )
    assert dependencies["claim_state"] == {"held": False, "released": False}
    dependencies["runner"].compact_conversation.assert_not_awaited()


async def test_live_turn_lease_refuses_manual_compaction(monkeypatch: pytest.MonkeyPatch):
    session = _session()
    dependencies = _install_session_dependencies(monkeypatch, session, claim_available=False)

    await session._run_compaction(
        _CompactNowRequest(request_id="live-turn", conversation_id=CONVERSATION, agent_id=AGENT)
    )

    assert (
        next(data for kind, data in _events(session) if kind == "compact_now_result")["status"]
        == "busy"
    )
    assert dependencies["claim_state"] == {"held": False, "released": False}
    dependencies["runner"].compact_conversation.assert_not_awaited()


async def test_nonowner_cannot_start_manual_compaction(monkeypatch: pytest.MonkeyPatch):
    session = _session()
    dependencies = _install_session_dependencies(
        monkeypatch,
        session,
        conversation=SimpleNamespace(
            user_id=uuid4(),
            project_id=None,
            workflow_id=None,
            origin=None,
            is_archived=False,
        ),
    )

    await session._run_compaction(
        _CompactNowRequest(request_id="other-owner", conversation_id=CONVERSATION, agent_id=AGENT)
    )

    assert (
        next(data for kind, data in _events(session) if kind == "compact_now_result")["status"]
        == "unavailable"
    )
    assert dependencies["claim_state"] == {"held": False, "released": False}
    dependencies["runner"].compact_conversation.assert_not_awaited()


async def test_stopping_compaction_releases_its_lease_and_emits_a_correlated_terminal_result(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session()
    dependencies = _install_session_dependencies(monkeypatch, session)
    started = asyncio.Event()
    wait_forever = asyncio.Event()

    async def waits_until_stopped(*_args, **_kwargs):
        started.set()
        await wait_forever.wait()

    runner = dependencies["runner"]
    runner.compact_conversation.side_effect = waits_until_stopped
    request = _CompactNowRequest(
        request_id="cancelled-maintenance",
        conversation_id=CONVERSATION,
        agent_id=AGENT,
    )
    task = asyncio.create_task(session._run_compaction(request))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert dependencies["claim_state"] == {"held": False, "released": True}
    result = next(data for kind, data in _events(session) if kind == "compact_now_result")
    assert result == {
        "request_id": "cancelled-maintenance",
        "conversation_id": str(CONVERSATION),
        "status": "failed",
    }
    assert _events(session)[-1] == ("session_ready", {"conversation_id": str(CONVERSATION)})


def _prepared_compaction(
    *,
    conversation_id,
    history: ModelHistory,
    guardrails: bool = False,
) -> tuple[PreparedRun, MeteredCompaction]:
    compaction_binding = SimpleNamespace(
        id="compaction", enabled=True, config={"strategy": "summarize"}
    )
    bindings = [compaction_binding]
    if guardrails:
        bindings.append(
            SimpleNamespace(
                id="guardrails", enabled=True, config={"blocked_keywords_in": "blocked"}
            )
        )
    capability = MeteredCompaction(
        wrapped=build_strategy(CompactionConfig(strategy="summarize", context_window=1_000))
    )
    capability.compact_now = AsyncMock(return_value=list(history)[:1])
    built = SimpleNamespace(
        ledger=SpendLedger(),
        context=ContextGauge(summarized=True),
        capabilities=[capability],
        deps=AgentDeps(),
        agent=SimpleNamespace(model=TestModel(), model_settings=None),
        usage_limits=None,
        budget=MagicMock(),
        recorder=SimpleNamespace(requests=[], instructions=None),
        primary_model=None,
        fallback_models=[],
        repairs=SimpleNamespace(count=0),
    )
    run = SimpleNamespace(
        id=uuid4(),
        fallback_used=False,
        serving_model=None,
        tool_args_repaired=0,
    )
    prepared = PreparedRun(
        run=run,
        agent=SimpleNamespace(model=TestModel(), model_settings=None),
        spec=SimpleNamespace(capabilities=bindings),
        built=built,
        approvals=SimpleNamespace(parked={}, requested=[]),
        workspace=None,
    )
    return prepared, capability


def _runner_harness(monkeypatch: pytest.MonkeyPatch, history: ModelHistory, prepared: PreparedRun):
    db = MagicMock()
    db.commit = AsyncMock()
    conversation_service = MagicMock()
    conversation_service.model_history = AsyncMock(return_value=history)
    conversation_service.keep_summary_snapshot = AsyncMock(return_value=True)
    ctx = AuthContext(user_id=PERSON, organization_id=ORG, role=OrgRoleName.OWNER)
    published_spec = SimpleNamespace(
        capabilities=[
            SimpleNamespace(id="compaction", enabled=True, config={"strategy": "summarize"})
        ]
    )
    service = AgentRunnerService(db)
    service.registry.get_runnable_spec = AsyncMock(return_value=(object(), published_spec, None))
    service.prepare = AsyncMock(return_value=prepared)
    service.finish_compaction = AsyncMock(return_value=prepared.run)

    @asynccontextmanager
    async def heartbeat(_run_id):
        yield

    monkeypatch.setattr(
        agent_runner_module, "ConversationService", lambda _db: conversation_service
    )
    monkeypatch.setattr(agent_runner_module, "check_history_snapshot", AsyncMock())
    monkeypatch.setattr(agent_runner_module, "run_heartbeat", heartbeat)
    monkeypatch.setattr(agent_runner_module.change_feed, "publish_run", AsyncMock())
    monkeypatch.setattr(
        agent_runner_module, "offloaded_history", AsyncMock(return_value=[{"summary": True}])
    )
    return service, conversation_service, db, ctx


async def test_runner_records_summary_only_if_the_bounded_snapshot_cas_holds(
    monkeypatch: pytest.MonkeyPatch,
):
    history = ModelHistory(
        [ModelRequest(parts=[UserPromptPart(content="remember this")])], revision=4, ordinal=9
    )
    prepared, capability = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    service, conversation_service, db, ctx = _runner_harness(monkeypatch, history, prepared)

    result = await service.compact_conversation(ctx, CONVERSATION, AGENT)

    assert result is True
    capability.compact_now.assert_awaited_once()
    conversation_service.keep_summary_snapshot.assert_awaited_once_with(
        CONVERSATION,
        [{"summary": True}],
        expected_revision=4,
        expected_ordinal=9,
    )
    assert prepared.model_context_check is not None
    assert service.finish_compaction.await_args.kwargs["status"] is RunStatus.COMPLETED
    assert db.commit.await_count == 2


async def test_runner_keeps_the_existing_cache_when_snapshot_cas_loses(
    monkeypatch: pytest.MonkeyPatch,
):
    history = ModelHistory(
        [ModelRequest(parts=[UserPromptPart(content="remember this")])], revision=4, ordinal=9
    )
    prepared, _capability = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    service, conversation_service, _db, ctx = _runner_harness(monkeypatch, history, prepared)
    conversation_service.keep_summary_snapshot.return_value = False

    with pytest.raises(BadRequestError, match="changed while its summary was being written"):
        await service.compact_conversation(ctx, CONVERSATION, AGENT)

    assert service.finish_compaction.await_args.kwargs["status"] is RunStatus.FAILED
    conversation_service.keep_summary_snapshot.assert_awaited_once_with(
        CONVERSATION,
        [{"summary": True}],
        expected_revision=4,
        expected_ordinal=9,
    )


async def test_runner_refuses_a_stale_guardrail_revision_before_calling_the_summarizer(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.agents.capabilities.guardrails import GuardrailBlocked

    history = ModelHistory(
        [ModelRequest(parts=[UserPromptPart(content="safe history")])], revision=4, ordinal=9
    )
    prepared, capability = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    service, conversation_service, _db, ctx = _runner_harness(monkeypatch, history, prepared)
    monkeypatch.setattr(
        agent_runner_module,
        "check_history_snapshot",
        AsyncMock(side_effect=GuardrailBlocked(edge="input", message="history changed")),
    )

    with pytest.raises(GuardrailBlocked):
        await service.compact_conversation(ctx, CONVERSATION, AGENT)

    capability.compact_now.assert_not_awaited()
    conversation_service.keep_summary_snapshot.assert_not_awaited()
    assert service.finish_compaction.await_args.kwargs["status"] is RunStatus.GUARDRAIL_BLOCKED


async def test_runner_books_budget_refusal_and_does_not_replace_the_summary(
    monkeypatch: pytest.MonkeyPatch,
):
    history = ModelHistory(
        [ModelRequest(parts=[UserPromptPart(content="remember this")])], revision=4, ordinal=9
    )
    prepared, capability = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    capability.compact_now.side_effect = BudgetExceeded(
        limit_usd=Decimal("1"), spent_usd=Decimal("1"), scope=BudgetScope.RUN
    )
    service, conversation_service, _db, ctx = _runner_harness(monkeypatch, history, prepared)

    with pytest.raises(BudgetExceeded):
        await service.compact_conversation(ctx, CONVERSATION, AGENT)

    conversation_service.keep_summary_snapshot.assert_not_awaited()
    assert service.finish_compaction.await_args.kwargs["status"] is RunStatus.BUDGET_EXCEEDED


async def test_runner_settles_cancellation_before_releasing_the_run_ledger(
    monkeypatch: pytest.MonkeyPatch,
):
    history = ModelHistory(
        [ModelRequest(parts=[UserPromptPart(content="remember this")])], revision=4, ordinal=9
    )
    prepared, capability = _prepared_compaction(conversation_id=CONVERSATION, history=history)
    capability.compact_now.side_effect = asyncio.CancelledError()
    service, conversation_service, db, ctx = _runner_harness(monkeypatch, history, prepared)

    with pytest.raises(asyncio.CancelledError):
        await service.compact_conversation(ctx, CONVERSATION, AGENT)

    conversation_service.keep_summary_snapshot.assert_not_awaited()
    assert service.finish_compaction.await_args.kwargs["status"] is RunStatus.CANCELLED
    assert db.commit.await_count == 2
