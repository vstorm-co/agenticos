"""What stops a routine's next activation, asked of the checks a fire makes."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.schemas.routine_sources import RoutineSourcePolicy
from app.services import routine_readiness
from app.services.agent_trigger import AgentTriggerService
from app.services.routine_sources import PlatformRoutineIdentityRequired, RoutineSourcesRequired

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_CREATOR = uuid.uuid4()
_CREATOR_CTX = AuthContext(user_id=_CREATOR, organization_id=_ORG, role=OrgRoleName.MEMBER)


def _policy(mode: str = "restricted") -> RoutineSourcePolicy:
    ceiling = (
        {
            "approved_ceiling": RoutineSourcePolicy(
                mode="follow_agent",
                id=uuid.uuid4(),
                consented_by=_CREATOR,
                reviewed_at=datetime.now(UTC),
                version_id=uuid.uuid4(),
                scope_hash="a" * 64,
                spec_hash="b" * 64,
                behavior={},
            )
        }
        if mode == "follow_agent"
        else {}
    )
    return RoutineSourcePolicy(
        mode=mode,  # type: ignore[arg-type]  - a literal the test chooses
        id=uuid.uuid4(),
        consented_by=_CREATOR,
        reviewed_at=datetime.now(UTC),
        version_id=uuid.uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
        behavior={} if mode == "follow_agent" else None,
        **ceiling,
    )


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
        "trigger_type": "schedule",
        "overlap": "skip",
        "one_shot": False,
        "scope": "a" * 64,
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
    checks.actions.review = AsyncMock(return_value=MagicMock(can_waive=True, items=[]))
    checks.runs.get_run = AsyncMock(return_value=None)
    monkeypatch.setattr(routine_readiness, "AgentRegistryService", lambda db: checks.agents)
    monkeypatch.setattr(routine_readiness, "RoutineSourceService", lambda db: checks.sources)
    monkeypatch.setattr(routine_readiness, "RoutineActionService", lambda db: checks.actions)
    monkeypatch.setattr(routine_readiness, "agent_run_repo", checks.runs)
    monkeypatch.setattr(routine_readiness, "source_scope", lambda trigger: trigger.scope)
    return checks


async def _codes(trigger: MagicMock, **kwargs: object) -> list[str]:
    options: dict[str, object] = {"creator": _CREATOR_CTX, "paused_for_budget": False}
    options.update(kwargs)
    found = await routine_readiness.blockers(MagicMock(), trigger, **options)  # type: ignore[arg-type]
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


@pytest.mark.parametrize(
    ("refusal", "code"),
    [
        (PlatformRoutineIdentityRequired(), "platform_identity"),
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


def _action(*, waivable: bool, consented: bool) -> MagicMock:
    return MagicMock(waivable=waivable, consented=consented)


async def test_actions_without_standing_consent_are_counted(engine: MagicMock) -> None:
    engine.actions.review.return_value = MagicMock(
        can_waive=True,
        items=[
            _action(waivable=True, consented=False),
            _action(waivable=True, consented=True),
            _action(waivable=False, consented=False),
            _action(waivable=True, consented=False),
        ],
    )
    trigger = _trigger()
    [blocker] = await routine_readiness.blockers(
        MagicMock(), trigger, creator=_CREATOR_CTX, paused_for_budget=False
    )
    assert (blocker.code, blocker.severity, blocker.count) == (
        "actions_need_approval",
        "attention",
        2,
    )
    engine.actions.review.assert_awaited_once_with(_CREATOR_CTX, trigger)


async def test_consent_the_creator_may_not_waive_covers_nothing(engine: MagicMock) -> None:
    engine.actions.review.return_value = MagicMock(
        can_waive=False,
        items=[_action(waivable=True, consented=True), _action(waivable=False, consented=False)],
    )
    found = await routine_readiness.blockers(
        MagicMock(), _trigger(), creator=_CREATOR_CTX, paused_for_budget=False
    )
    assert [(blocker.code, blocker.count) for blocker in found] == [("actions_need_approval", 1)]


@pytest.mark.parametrize(
    "refusal",
    [NotFoundError(message="x"), BadRequestError(message="x"), AuthorizationError(message="x")],
)
async def test_an_action_review_that_cannot_be_made_adds_no_blocker(
    engine: MagicMock, refusal: Exception
) -> None:
    engine.actions.review.side_effect = refusal
    assert await _codes(_trigger()) == []


async def test_a_following_review_leaves_consent_to_the_agents_own_gate(
    engine: MagicMock,
) -> None:
    trigger = _trigger(approved_sources=_policy("follow_agent").model_dump(mode="json"))
    assert await _codes(trigger) == []
    engine.actions.review.assert_not_awaited()


async def test_a_stale_following_review_asks_for_the_review_and_counts_no_consent(
    engine: MagicMock,
) -> None:
    """Publishing a new prompt makes a following review stale; its actions stay the agent's."""
    engine.sources.current.side_effect = AuthorizationError(message="stale")
    trigger = _trigger(approved_sources=_policy("follow_agent").model_dump(mode="json"))
    assert await _codes(trigger) == ["sources_review"]
    engine.actions.review.assert_not_awaited()


def _service() -> AgentTriggerService:
    service = AgentTriggerService(MagicMock())
    service.agents = MagicMock(get=AsyncMock(return_value=MagicMock(id=uuid.uuid4())))
    return service


async def test_the_service_evaluates_as_the_creator_with_this_months_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import agent_trigger

    service = _service()
    agent_id = service.agents.get.return_value.id
    trigger = MagicMock(
        id=uuid.uuid4(), agent_id=agent_id, one_shot=False, created_by_user_id=_CREATOR
    )
    repo = MagicMock(get=AsyncMock(return_value=trigger))
    monkeypatch.setattr(agent_trigger, "agent_trigger_repo", repo)
    monkeypatch.setattr(agent_trigger.TriggerRead, "model_validate", lambda row: MagicMock())

    async def spent(reads: list[tuple[MagicMock, MagicMock]]) -> None:
        reads[0][0].paused_for_budget = True

    monkeypatch.setattr(service, "_mark_spend", spent)
    monkeypatch.setattr(service, "_creator_context", AsyncMock(return_value=_CREATOR_CTX))
    evaluate = AsyncMock(return_value=[])
    monkeypatch.setattr(agent_trigger.routine_readiness, "blockers", evaluate)
    caller = AuthContext(user_id=uuid.uuid4(), organization_id=_ORG, role=OrgRoleName.VIEWER)

    result = await service.readiness(caller, agent_id, trigger.id)

    assert result.trigger_id == trigger.id
    assert result.blockers == []
    service.agents.get.assert_awaited_once_with(caller, agent_id)
    assert evaluate.await_args.kwargs == {"creator": _CREATOR_CTX, "paused_for_budget": True}


@pytest.mark.parametrize(
    "found",
    [
        None,
        {"agent_id": uuid.uuid4(), "one_shot": False},
        {"one_shot": True, "created_by_user_id": uuid.uuid4()},
    ],
)
async def test_a_routine_the_caller_cannot_see_is_not_found(
    monkeypatch: pytest.MonkeyPatch, found: dict[str, object] | None
) -> None:
    from app.services import agent_trigger

    service = _service()
    agent_id = service.agents.get.return_value.id
    row = None if found is None else MagicMock(**{"agent_id": agent_id, **found})
    monkeypatch.setattr(
        agent_trigger, "agent_trigger_repo", MagicMock(get=AsyncMock(return_value=row))
    )
    caller = AuthContext(user_id=uuid.uuid4(), organization_id=_ORG, role=OrgRoleName.VIEWER)
    with pytest.raises(NotFoundError):
        await service.readiness(caller, agent_id, uuid.uuid4())
