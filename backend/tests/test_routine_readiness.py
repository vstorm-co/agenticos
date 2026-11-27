"""What stops a routine's next activation, asked of the checks a fire makes."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock

import anyio
import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.schemas.routine_readiness import RoutineBlocker, TriggerReadiness
from app.schemas.routine_sources import RoutineSourcePolicy
from app.services import routine_readiness
from app.services.agent_trigger import AgentTriggerService
from app.services.routine_sources import (
    PlatformRoutineIdentityRequired,
    RoutineSourcesRequired,
    RoutineTrustRefused,
)

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CREATOR = uuid.uuid4()
_CREATOR_CTX = AuthContext(user_id=_CREATOR, organization_id=_ORG, role=OrgRoleName.MEMBER)


def _policy(**update: object) -> RoutineSourcePolicy:
    return RoutineSourcePolicy(
        id=uuid.uuid4(),
        consented_by=_CREATOR,
        reviewed_at=datetime.now(UTC),
        version_id=uuid.uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
    ).model_copy(update=update)


def _trigger(**overrides: object) -> MagicMock:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": _ORG,
        "agent_id": uuid.uuid4(),
        "created_by_user_id": _CREATOR,
        "ends_at": None,
        "pinned_version_id": None,
        "environment_id": None,
        "setup_required": False,
        "approved_sources": _policy().model_dump(mode="json"),
        "last_run_id": None,
        "conversation_id": None,
        "trigger_type": "schedule",
        "overlap": "skip",
        "one_shot": False,
        "scope": "a" * 64,
        "intent": "d" * 64,
    }
    fields.update(overrides)
    return MagicMock(**fields)


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """The fire path's own checks, each answering "admitted" until a test says otherwise."""
    checks = MagicMock()
    checks.agents.get = AsyncMock()
    checks.agents.get_pinned_spec = AsyncMock()
    checks.agents.get_runnable_spec = AsyncMock()
    checks.sources.current = AsyncMock()
    checks.access.waiting = AsyncMock(return_value=0)
    checks.runs.get_run = AsyncMock(return_value=None)
    checks.runs.latest_parked_run_for_conversation = AsyncMock(return_value=None)
    monkeypatch.setattr(routine_readiness, "AgentRegistryService", lambda db: checks.agents)
    monkeypatch.setattr(routine_readiness, "RoutineSourceService", lambda db: checks.sources)
    monkeypatch.setattr(routine_readiness, "RoutineAccessService", lambda db: checks.access)
    monkeypatch.setattr(routine_readiness, "agent_run_repo", checks.runs)
    monkeypatch.setattr(routine_readiness, "source_scope", lambda trigger: trigger.scope)
    monkeypatch.setattr(routine_readiness, "routine_intent", lambda trigger: trigger.intent)
    return checks


async def _codes(
    trigger: MagicMock,
    *,
    creator: AuthContext | None = _CREATOR_CTX,
    paused_for_budget: bool = False,
) -> list[str]:
    found = await routine_readiness.blockers(
        MagicMock(), trigger, creator=creator, paused_for_budget=paused_for_budget
    )
    return [blocker.code for blocker in found]


async def test_a_routine_every_check_admits_has_no_blockers(engine: MagicMock) -> None:
    trigger = _trigger()
    assert await _codes(trigger) == []
    engine.agents.get.assert_awaited_once_with(_CREATOR_CTX, trigger.agent_id, perm=Perm.AGENTS_RUN)
    engine.agents.get_runnable_spec.assert_awaited_once_with(
        _CREATOR_CTX, trigger.agent_id, environment_id=None
    )
    expected = RoutineSourcePolicy.model_validate(trigger.approved_sources).id
    assert engine.sources.current.await_args.kwargs == {"expected_id": expected}


async def test_a_creator_who_left_stops_every_other_check(engine: MagicMock) -> None:
    trigger = _trigger(ends_at=datetime.now(UTC) - timedelta(minutes=1))
    assert await _codes(trigger, creator=None, paused_for_budget=True) == [
        "ended",
        "budget_exhausted",
        "creator_inactive",
    ]
    engine.agents.get.assert_not_awaited()


@pytest.mark.parametrize("refusal", [NotFoundError(message="x"), AuthorizationError(message="x")])
async def test_a_creator_without_a_run_grant_is_named(
    engine: MagicMock, refusal: Exception
) -> None:
    engine.agents.get.side_effect = refusal
    assert await _codes(_trigger(ends_at=datetime.now(UTC) + timedelta(days=1))) == [
        "creator_cannot_run"
    ]
    engine.sources.current.assert_not_awaited()


async def test_a_pinned_version_that_is_gone_makes_the_agent_unavailable(
    engine: MagicMock,
) -> None:
    version = uuid.uuid4()
    engine.agents.get_pinned_spec.side_effect = NotFoundError(message="gone")
    trigger = _trigger(pinned_version_id=version)
    assert await _codes(trigger) == ["agent_unavailable"]
    engine.agents.get_pinned_spec.assert_awaited_once_with(_CREATOR_CTX, trigger.agent_id, version)


async def test_an_unpublished_agent_is_unavailable(engine: MagicMock) -> None:
    engine.agents.get_runnable_spec.side_effect = BadRequestError(message="draft")
    assert await _codes(_trigger()) == ["agent_unavailable"]


async def test_a_routine_awaiting_its_first_review_is_not_reviewed_again(
    engine: MagicMock,
) -> None:
    assert await _codes(_trigger(setup_required=True)) == ["sources_setup"]
    engine.sources.current.assert_not_awaited()
    engine.access.waiting.assert_not_awaited()


@pytest.mark.parametrize(
    ("refusal", "code"),
    [
        (PlatformRoutineIdentityRequired(), "platform_identity"),
        (RoutineTrustRefused(details={"reason": "organization"}), "trust_not_allowed"),
        (RoutineSourcesRequired(), "sources_review"),
        (NotFoundError(message="project gone"), "sources_review"),
        (BadRequestError(message="delegate gone"), "sources_review"),
    ],
)
async def test_a_source_review_the_fire_would_refuse_is_named(
    engine: MagicMock, refusal: Exception, code: str
) -> None:
    engine.sources.current.side_effect = refusal
    assert await _codes(_trigger()) == [code]


async def test_editing_the_routine_itself_is_named_apart_from_a_changed_agent(
    engine: MagicMock,
) -> None:
    """Switching who it runs as is what the person did, not something the agent did."""
    engine.sources.current.side_effect = RoutineSourcesRequired()
    assert await _codes(_trigger(scope="c" * 64)) == ["routine_changed"]


async def test_a_changed_prompt_is_the_routine_changing_where_the_review_recorded_one(
    engine: MagicMock,
) -> None:
    engine.sources.current.side_effect = RoutineSourcesRequired()
    reviewed = _policy(intent_hash="d" * 64).model_dump(mode="json")
    assert await _codes(_trigger(approved_sources=reviewed)) == ["sources_review"]
    assert await _codes(_trigger(approved_sources=reviewed, intent="e" * 64)) == ["routine_changed"]
    # Migrated without an intent: a prompt edit is not detected until the review is saved.
    assert await _codes(_trigger(intent="e" * 64)) == ["sources_review"]


async def test_a_stored_review_that_does_not_parse_needs_reviewing(engine: MagicMock) -> None:
    assert await _codes(_trigger(approved_sources={"pending_review": False})) == ["sources_review"]
    engine.sources.current.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "trigger_type", "overlap", "code", "severity"),
    [
        ("awaiting_approval", "schedule", "skip", "awaiting_approval", "blocked"),
        ("awaiting_approval", "schedule", "queue", "awaiting_approval", "blocked"),
        ("awaiting_answer", "schedule", "skip", "awaiting_answer", "blocked"),
        ("awaiting_approval", "schedule", "allow", "awaiting_approval", "attention"),
        ("awaiting_approval", "event", "skip", "awaiting_approval", "attention"),
    ],
)
async def test_a_parked_previous_run_holds_a_schedule_that_does_not_overlap(
    engine: MagicMock, status: str, trigger_type: str, overlap: str, code: str, severity: str
) -> None:
    run_id = uuid.uuid4()
    engine.runs.get_run.return_value = MagicMock(id=run_id, status=status)
    trigger = _trigger(last_run_id=run_id, trigger_type=trigger_type, overlap=overlap)
    [blocker] = await routine_readiness.blockers(
        MagicMock(), trigger, creator=_CREATOR_CTX, paused_for_budget=False
    )
    assert (blocker.code, blocker.severity, blocker.run_id) == (code, severity, run_id)
    engine.runs.get_run.assert_awaited_once_with(ANY, run_id, organization_id=_ORG)


@pytest.mark.parametrize("run", [None, MagicMock(status="completed")])
async def test_a_finished_or_missing_previous_run_holds_nothing(
    engine: MagicMock, run: MagicMock | None
) -> None:
    engine.runs.get_run.return_value = run
    assert await _codes(_trigger(last_run_id=uuid.uuid4())) == []


async def test_tools_the_review_makes_wait_are_counted(engine: MagicMock) -> None:
    engine.access.waiting.return_value = 2
    trigger = _trigger()
    [blocker] = await routine_readiness.blockers(
        MagicMock(), trigger, creator=_CREATOR_CTX, paused_for_budget=False
    )
    assert (blocker.code, blocker.severity, blocker.count) == (
        "actions_need_approval",
        "attention",
        2,
    )
    engine.access.waiting.assert_awaited_once_with(_CREATOR_CTX, trigger)


@pytest.mark.parametrize(
    "refusal",
    [NotFoundError(message="x"), BadRequestError(message="x"), AuthorizationError(message="x")],
)
async def test_a_tool_count_that_cannot_be_made_adds_no_blocker(
    engine: MagicMock, refusal: Exception
) -> None:
    engine.access.waiting.side_effect = refusal
    assert await _codes(_trigger()) == []


async def test_a_stale_review_still_counts_the_tools_it_makes_wait(engine: MagicMock) -> None:
    """Re-reviewing fixes the sources; the tools it asks for are a separate, standing fact."""
    engine.sources.current.side_effect = AuthorizationError(message="stale")
    engine.access.waiting.return_value = 1
    trigger = _trigger(approved_sources=_policy(mode="trust_agent").model_dump(mode="json"))
    assert await _codes(trigger) == ["sources_review", "actions_need_approval"]


def _row(**overrides: object) -> MagicMock:
    return MagicMock(
        **{
            "id": uuid.uuid4(),
            "created_by_user_id": _CREATOR,
            "runs_as_creator": False,
            "trigger_type": "schedule",
            **overrides,
        }
    )


async def test_the_service_evaluates_each_visible_routine_as_its_creator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import agent_trigger

    service = AgentTriggerService(MagicMock())
    first, second = _row(), _row(runs_as_creator=True, trigger_type="event")
    other = _row(created_by_user_id=uuid.uuid4())
    shared = uuid.uuid4()
    repo = MagicMock(list_visible_by_ids=AsyncMock(return_value=[first, second, other]))
    monkeypatch.setattr(agent_trigger, "agent_trigger_repo", repo)
    monkeypatch.setattr(agent_trigger, "visible_resource_ids", AsyncMock(return_value=[shared]))
    monkeypatch.setattr(agent_trigger.TriggerRead, "model_validate", lambda row: MagicMock())

    async def spent(reads: list[tuple[MagicMock, MagicMock]]) -> None:
        for read, row in reads:
            read.paused_for_budget = row is second

    monkeypatch.setattr(service, "_mark_spend", spent)
    creator = AsyncMock(side_effect=[_CREATOR_CTX, None])
    monkeypatch.setattr(service, "_creator_context", creator)
    evaluate = AsyncMock(side_effect=[[], [RoutineBlocker(code="ended", severity="blocked")], []])
    monkeypatch.setattr(agent_trigger.routine_readiness, "blockers", evaluate)
    caller = AuthContext(user_id=uuid.uuid4(), organization_id=_ORG, role=OrgRoleName.VIEWER)
    asked = [first.id, second.id, other.id, uuid.uuid4()]

    result = await service.readiness(caller, asked)

    assert [item.trigger_id for item in result] == [first.id, second.id, other.id]
    assert [len(item.blockers) for item in result] == [0, 1, 0]
    assert repo.list_visible_by_ids.await_args.kwargs == {
        "organization_id": _ORG,
        "user_id": caller.user_id,
        "see_all": False,
        "shared_ids": [shared],
        "trigger_ids": asked,
    }
    # One membership read per creator, not per routine.
    assert creator.await_count == 2
    assert [call.kwargs for call in evaluate.await_args_list] == [
        {
            "creator": replace(
                _CREATOR_CTX, routine_id=first.id, subject_is_publisher_fallback=True
            ),
            "paused_for_budget": False,
        },
        {
            "creator": replace(_CREATOR_CTX, routine_id=second.id, fired_as_creator="event"),
            "paused_for_budget": True,
        },
        {"creator": None, "paused_for_budget": False},
    ]


async def test_a_role_that_sees_every_agent_reads_without_a_grant_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import agent_trigger

    service = AgentTriggerService(MagicMock())
    repo = MagicMock(list_visible_by_ids=AsyncMock(return_value=[]))
    monkeypatch.setattr(agent_trigger, "agent_trigger_repo", repo)
    monkeypatch.setattr(agent_trigger, "visible_resource_ids", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_mark_spend", AsyncMock())
    caller = AuthContext(user_id=uuid.uuid4(), organization_id=_ORG, role=OrgRoleName.OWNER)

    assert await service.readiness(caller, [uuid.uuid4()]) == []
    assert repo.list_visible_by_ids.await_args.kwargs["see_all"] is True
    assert repo.list_visible_by_ids.await_args.kwargs["shared_ids"] == []


@pytest.mark.parametrize("last", [None, "completed", "missing"])
async def test_a_crash_before_last_run_linking_still_exposes_the_parked_run(
    engine: MagicMock, last: str | None
) -> None:
    conversation_id, parked_id = uuid.uuid4(), uuid.uuid4()
    engine.runs.get_run.return_value = None if last == "missing" else MagicMock(status=last)
    engine.runs.latest_parked_run_for_conversation.return_value = MagicMock(
        id=parked_id, status="awaiting_answer"
    )
    trigger = _trigger(
        last_run_id=None if last is None else uuid.uuid4(), conversation_id=conversation_id
    )
    [blocker] = await routine_readiness.blockers(
        MagicMock(), trigger, creator=_CREATOR_CTX, paused_for_budget=False
    )
    assert (blocker.code, blocker.severity, blocker.run_id) == (
        "awaiting_answer",
        "blocked",
        parked_id,
    )
    engine.runs.latest_parked_run_for_conversation.assert_awaited_once_with(
        ANY, conversation_id=conversation_id, organization_id=_ORG
    )


async def test_an_empty_run_log_does_not_add_a_parked_blocker(engine: MagicMock) -> None:
    assert await _codes(_trigger(conversation_id=uuid.uuid4())) == []


async def test_parallel_readiness_requests_are_refused_before_database_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import rate_limit

    monkeypatch.setattr(rate_limit, "_redis", None)
    monkeypatch.setattr(rate_limit, "_held_here", set())
    service = AgentTriggerService(MagicMock())
    entered, finish = anyio.Event(), anyio.Event()
    evaluated: list[AuthContext] = []

    async def evaluate(ctx: AuthContext, trigger_ids: list[uuid.UUID]) -> list[TriggerReadiness]:
        evaluated.append(ctx)
        if ctx == _CREATOR_CTX:
            entered.set()
            await finish.wait()
        return []

    monkeypatch.setattr(service, "_readiness", evaluate)
    async with anyio.create_task_group() as group:
        group.start_soon(service.readiness, _CREATOR_CTX, [])
        await entered.wait()
        for _ in range(14):
            with pytest.raises(RateLimitError):
                await service.readiness(_CREATOR_CTX, [])
        other = replace(_CREATOR_CTX, user_id=uuid.uuid4())
        assert await service.readiness(other, []) == []
        finish.set()
    assert evaluated == [_CREATOR_CTX, other]
    assert await service.readiness(other, []) == []
