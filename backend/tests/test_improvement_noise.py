"""Whether an improvement session's test could tell a better version from a worse
one, read from the checks it stored and shown only to whoever may read runs."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.services import improvement_pipeline
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.improvement_states import (
    NOISE_EXAMPLES,
    CheckedAttempt,
    CheckedCase,
    measurement_noise,
)

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
OWNER = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role=OrgRoleName.OWNER.value)


def _case(n: int, baseline=(True,), candidate=(True,)) -> CheckedCase:
    return CheckedCase(
        case_id=uuid.UUID(int=n),
        input=f"Question {n}",
        baseline=tuple(baseline),
        candidate=tuple(candidate),
    )


def _attempt(number: int, passed: int, cases: list[CheckedCase]) -> CheckedAttempt:
    return CheckedAttempt(
        number=number,
        baseline_passed=passed,
        baseline_rate=passed / len(cases),
        cases=tuple(cases),
    )


def _steady(n: int = 10) -> list[CheckedCase]:
    return [_case(i) for i in range(n)]


def test_a_session_with_no_measured_attempt_has_no_signal():
    assert measurement_noise([]) is None


def test_the_same_version_scoring_two_questions_apart_is_noise():
    noise = measurement_noise([_attempt(1, 5, _steady()), _attempt(2, 7, _steady())])
    assert noise is not None
    assert noise.noisy
    assert (noise.baseline_low, noise.baseline_high, noise.baseline_spread) == (0.5, 0.7, 2)
    assert noise.held_out == 10


def test_one_question_of_twenty_is_within_what_the_test_can_tell():
    noise = measurement_noise([_attempt(1, 10, _steady(20)), _attempt(2, 11, _steady(20))])
    assert noise is not None
    assert not noise.noisy
    assert noise.baseline_spread == 1
    assert noise.unstable == 0
    assert noise.examples == []


def test_one_question_of_a_small_set_already_moves_the_score_too_far():
    noise = measurement_noise([_attempt(1, 3, _steady(5)), _attempt(2, 4, _steady(5))])
    assert noise is not None
    assert noise.baseline_spread == 1
    assert noise.noisy


def test_a_fifth_of_the_questions_graded_both_ways_is_noise_and_a_tenth_is_not():
    mixed = [_case(0, baseline=(True, False, True)), _case(1, candidate=(False, True))]
    calm = _attempt(1, 10, [*mixed[:1], *_steady(10)[1:]])
    assert not measurement_noise([calm]).noisy  # type: ignore[union-attr]
    noise = measurement_noise([_attempt(1, 10, [*mixed, *_steady(10)[2:]])])
    assert noise is not None
    assert noise.noisy
    assert noise.unstable == 2
    assert noise.by_attempt[0].model_dump() == {
        "number": 1,
        "baseline_unstable": 1,
        "candidate_unstable": 1,
    }


def test_today_s_version_graded_differently_between_attempts_counts_as_unstable():
    first = _attempt(1, 10, [_case(0, baseline=(True, True, True)), *_steady(10)[1:]])
    second = _attempt(2, 9, [_case(0, baseline=(False, False, False)), *_steady(10)[1:]])
    noise = measurement_noise([first, second])
    assert noise is not None
    assert noise.unstable == 1
    assert [a.baseline_unstable for a in noise.by_attempt] == [0, 0]
    [example] = noise.examples
    assert example.input == "Question 0"
    assert [(a.number, a.baseline) for a in example.attempts] == [
        (1, [True, True, True]),
        (2, [False, False, False]),
    ]


def test_ungraded_answers_neither_count_as_a_change_nor_hide_one():
    noise = measurement_noise(
        [_attempt(1, 9, [_case(0, baseline=(None, True), candidate=(None,)), *_steady(10)[1:]])]
    )
    assert noise is not None
    assert noise.unstable == 0


def test_examples_stop_at_the_limit_while_the_count_covers_every_question():
    cases = [_case(i, baseline=(True, False)) for i in range(NOISE_EXAMPLES + 2)]
    noise = measurement_noise([_attempt(1, len(cases), cases)])
    assert noise is not None
    assert noise.unstable == NOISE_EXAMPLES + 2
    assert [e.input for e in noise.examples] == [f"Question {i}" for i in range(NOISE_EXAMPLES)]


def test_an_attempt_without_a_baseline_score_leaves_the_spread_to_the_others():
    unscored = CheckedAttempt(number=1, baseline_passed=0, baseline_rate=None, cases=())
    noise = measurement_noise([unscored])
    assert noise is not None
    assert (noise.baseline_low, noise.baseline_high, noise.baseline_spread) == (None, None, 0)
    assert noise.held_out == 0
    assert not noise.noisy


def _flip(n: int, baseline, reruns=(), candidate=True) -> SimpleNamespace:
    return SimpleNamespace(
        case_id=uuid.UUID(int=n),
        input=f"Question {n}",
        baseline=baseline,
        baseline_reruns=list(reruns),
        candidate=candidate,
        candidate_reruns=[],
    )


def _iteration(number: int, *, verdict="no_change", runs=("run",)) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        number=number,
        verdict=verdict,
        eval_run_ids=[uuid.uuid4() for _ in runs],
        authoring_request_id=None,
        batch_id=None,
        candidate_spec_hash=None,
        attribution_eval_run_ids={},
        dropped_hunk_ids=[],
        dropped=[],
        verdict_detail=None,
        cost_usd=Decimal(0),
        started_at=datetime.now(UTC),
        ended_at=None,
        included_hunk_ids=None,
        previous_eval_run_ids=[],
    )


def _session(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        organization_id=ORG,
        created_by_user_id=OWNER.user_id,
        created_by_api_key_id=None,
        improver_agent_id=None,
        status=status,
        stage="judging",
        iteration=2,
        max_iterations=2,
        base_version_id=None,
        dataset_id=uuid.uuid4(),
        dataset_version=1,
        suite_id=None,
        estimate_usd=Decimal(1),
        budget_usd=Decimal(1),
        spent_usd=Decimal(0),
        best_iteration_id=None,
        stop_reason="no_change",
        error=None,
        created_at=datetime.now(UTC),
        finished_at=None,
        deferred_topic_ids=[],
        published_version_id=None,
    )


@pytest.fixture
def service(monkeypatch):
    rounds = [
        _iteration(1),
        _iteration(2),
        _iteration(3, verdict=None),
        _iteration(4, runs=()),
        _iteration(5),
    ]
    repo = improvement_pipeline.improvement_repo
    monkeypatch.setattr(repo, "list_iterations", AsyncMock(return_value=rounds))
    monkeypatch.setattr(repo, "timeline", AsyncMock(return_value=[]))
    monkeypatch.setattr(repo, "spent", AsyncMock(return_value=Decimal(0)))
    monkeypatch.setattr(repo, "knowledge_checks", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        improvement_pipeline.eval_run_repo, "arm_answers", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(improvement_pipeline.user_repo, "get_many", AsyncMock(return_value={}))
    pipeline = ImprovementPipelineService(AsyncMock())
    monkeypatch.setattr(pipeline, "_may_continue", AsyncMock(return_value=True))
    first = SimpleNamespace(
        baseline_summary=SimpleNamespace(passed=5, pass_rate=0.5),
        cases=[_flip(0, True, reruns=[False, True]), *[_flip(i, True) for i in range(1, 10)]],
    )
    second = SimpleNamespace(
        baseline_summary=SimpleNamespace(passed=7, pass_rate=0.7),
        cases=[_flip(i, True) for i in range(10)],
    )
    compare = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(pipeline.evals, "compare", compare)
    return pipeline, compare, second


async def test_a_settled_session_reads_its_noise_from_each_measured_attempt(service):
    pipeline, compare, _ = service
    read = await pipeline._read(OWNER, _session("stopped"))  # type: ignore[arg-type]
    noise = read.measurement_noise
    assert noise is not None
    assert noise.noisy
    assert (noise.baseline_low, noise.baseline_high, noise.baseline_spread) == (0.5, 0.7, 2)
    assert [a.number for a in noise.by_attempt] == [1, 2]
    assert noise.examples[0].attempts[0].baseline == [True, False, True]
    assert compare.await_count == 2


async def test_a_check_the_reader_can_no_longer_open_is_left_out(service):
    pipeline, compare, second = service
    compare.side_effect = [NotFoundError(message="Eval run not found"), second]
    read = await pipeline._read(OWNER, _session("stopped"))  # type: ignore[arg-type]
    assert read.measurement_noise is not None
    assert [a.number for a in read.measurement_noise.by_attempt] == [2]


async def test_a_working_session_and_a_reader_without_runs_view_get_no_signal(service):
    pipeline, compare, _ = service
    working = await pipeline._read(OWNER, _session("running"))  # type: ignore[arg-type]
    assert working.measurement_noise is None
    narrowed = AuthContext(
        user_id=OWNER.user_id,
        organization_id=ORG,
        role=OrgRoleName.OWNER.value,
        key_scopes=frozenset({Perm.AGENTS_VIEW}),
    )
    hidden = await pipeline._read(narrowed, _session("stopped"))  # type: ignore[arg-type]
    assert hidden.measurement_noise is None
    compare.assert_not_awaited()
