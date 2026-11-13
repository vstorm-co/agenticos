"""The parts of an eval run decided without running anything: refusals, outcomes, fingerprints."""

import uuid
from types import SimpleNamespace

import pytest

from app.db.models.eval_run import (
    AttemptFault,
    CaseAttemptStatus,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
)
from app.schemas.scoring import DatasetScoring
from app.services.eval_comparison import CaseState
from app.services.eval_run import (
    _failed_alike,
    _served_skill_versions,
    attempt_outcome,
    attempt_state,
    decidable,
    scoring_hash,
    scoring_refusal,
)


def _case(*, checks=(), expected=(), reference=None, counter_example=None):
    return SimpleNamespace(
        checks=list(checks),
        expected_tool_calls=list(expected),
        reference_answer=reference,
        counter_example=counter_example,
    )


def _scoring(**overrides) -> DatasetScoring:
    return DatasetScoring.model_validate(overrides)


class TestScoringRefusal:
    def test_a_check_on_a_case_decides_it(self):
        scoring = _scoring()
        cases = [_case(checks=[{"type": "contains", "value": "30 days"}])]
        assert scoring_refusal(scoring, cases) is None

    def test_a_default_check_decides_every_case(self):
        scoring = _scoring(checks={"defaults": [{"type": "contains", "value": "x"}]})
        assert scoring_refusal(scoring, [_case()]) is None

    def test_an_expected_call_decides_it(self):
        cases = [_case(expected=[{"tool": "lookup", "args": {}}])]
        assert scoring_refusal(_scoring(), cases) is None

    def test_nothing_to_check_is_refused_with_what_to_add(self):
        refusal = scoring_refusal(_scoring(), [_case(reference="yes")])
        assert refusal is not None
        assert refusal.details == {"reason": "no_scorer"}
        assert "Add a check" in refusal.message

    def test_enabled_criteria_can_decide_a_case(self):
        scoring = _scoring(
            judge={"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]}
        )
        assert scoring_refusal(scoring, [_case()]) is None

    def test_a_reference_answer_needs_the_judge(self):
        scoring = _scoring(reference={"enabled": True})
        cases = [_case(reference="30 days")]
        assert scoring_refusal(scoring, cases) is None

    def test_a_judge_check_on_a_case_needs_the_judge(self):
        cases = [_case(checks=[{"type": "judge", "criterion": "Cites a source"}])]
        assert scoring_refusal(_scoring(), cases) is None

    def test_an_optional_scorer_decides_nothing(self):
        scoring = _scoring(checks={"required": False}, trajectory={"required": False})
        cases = [_case(checks=[{"type": "contains", "value": "x"}], expected=[{"tool": "t"}])]
        assert scoring_refusal(scoring, cases) is not None


class TestDecidable:
    """What the start dialog counts: cases a run would leave ungraded."""

    def test_a_case_with_a_check_is_decided_and_one_with_only_a_reference_is_not(self):
        scoring = _scoring()
        assert decidable(_case(checks=[{"type": "contains", "value": "4"}]), scoring)
        assert not decidable(_case(reference="Red, blue or yellow."), scoring)

    def test_a_default_judge_check_can_decide_a_case(self):
        scoring = _scoring(checks={"defaults": [{"type": "judge", "criterion": "Polite"}]})
        assert decidable(_case(), scoring)

    def test_a_counter_example_is_decided_by_whichever_judges_it(self):
        case = _case(counter_example="Yes, any time.")
        assert decidable(case, _scoring(reference={"enabled": True}))
        assert not decidable(case, _scoring())


def _score(passed=None, human=None, results=()):
    return SimpleNamespace(passed=passed, human_passed=human, results=list(results))


class TestAttemptState:
    def _attempt(self, status=CaseAttemptStatus.DONE, fault=None):
        return SimpleNamespace(status=status.value, fault=fault)

    def test_a_persons_verdict_wins_over_the_scorers(self):
        attempt = self._attempt()
        assert attempt_state(attempt, _score(True, human=False)) is CaseState.FAILED
        assert attempt_outcome(attempt, _score(True, human=False)) is False

    def test_the_scorers_decide_without_a_verdict(self):
        assert attempt_state(self._attempt(), _score(True)) is CaseState.PASSED
        assert attempt_outcome(self._attempt(), _score(True)) is True

    def test_a_crash_of_the_agent_fails_the_case(self):
        crashed = self._attempt(CaseAttemptStatus.FAILED, AttemptFault.AGENT.value)
        assert attempt_state(crashed, None) is CaseState.FAILED
        assert attempt_outcome(crashed, None) is False

    @pytest.mark.parametrize("fault", [AttemptFault.INFRASTRUCTURE.value, None])
    def test_a_failure_of_the_infrastructure_leaves_it_incomplete(self, fault):
        """A failure recorded before its fault was is read the way that can never pass."""
        failed = self._attempt(CaseAttemptStatus.FAILED, fault)
        assert attempt_state(failed, None) is CaseState.INCOMPLETE
        assert attempt_outcome(failed, None) is None

    @pytest.mark.parametrize(
        "status", [CaseAttemptStatus.SKIPPED, CaseAttemptStatus.PENDING, CaseAttemptStatus.RUNNING]
    )
    def test_an_attempt_that_never_finished_is_incomplete(self, status):
        assert attempt_state(self._attempt(status), _score(True)) is CaseState.INCOMPLETE

    def test_an_answer_nothing_scored_is_ungraded(self):
        assert attempt_state(self._attempt(), None) is CaseState.UNGRADED
        assert attempt_outcome(self._attempt(), None) is None

    def test_a_score_with_nothing_required_is_ungraded(self):
        optional = {"scorer": "checks", "required": False, "status": "pass"}
        assert attempt_state(self._attempt(), _score(results=[optional])) is CaseState.UNGRADED

    def test_a_judge_ai_assistance_kept_from_running_left_it_ungraded(self):
        off = {
            "scorer": "judge",
            "required": True,
            "status": "skipped",
            "reason_code": "ai_assistance_off",
        }
        assert attempt_state(self._attempt(), _score(results=[off])) is CaseState.UNGRADED

    @pytest.mark.parametrize(
        ("status", "code"), [("error", "judge_run_failed"), ("skipped", "judge_budget")]
    )
    def test_a_judge_that_erred_or_was_refused_left_it_incomplete(self, status, code):
        result = {"scorer": "judge", "required": True, "status": status, "reason_code": code}
        assert attempt_state(self._attempt(), _score(results=[result])) is CaseState.INCOMPLETE


class TestFailedAlike:
    def _attempt(
        self,
        status=CaseAttemptStatus.FAILED,
        error="The provider rejected the key",
        *,
        fault=AttemptFault.AGENT,
    ):
        return SimpleNamespace(status=status.value, error=error, fault=fault.value)

    def test_every_answer_failing_with_one_error_names_it(self):
        firsts = [self._attempt(), self._attempt()]
        assert _failed_alike(firsts) == "The provider rejected the key"

    def test_a_parked_or_infrastructure_failure_is_not_a_common_agent_failure(self):
        assert (
            _failed_alike(
                [
                    self._attempt(fault=AttemptFault.INFRASTRUCTURE),
                    self._attempt(fault=AttemptFault.INFRASTRUCTURE),
                ]
            )
            is None
        )

    def test_two_errors_one_answer_that_finished_or_a_single_case_name_nothing(self):
        assert _failed_alike([self._attempt(), self._attempt(error="Step limit")]) is None
        assert _failed_alike([self._attempt(), self._attempt(CaseAttemptStatus.DONE)]) is None
        assert _failed_alike([self._attempt()]) is None
        assert _failed_alike([]) is None


def test_the_scoring_fingerprint_changes_with_any_setting():
    base = _scoring()
    assert scoring_hash(base) == scoring_hash(_scoring())
    assert scoring_hash(base) != scoring_hash(_scoring(review={"select": "all"}))


def test_every_eval_row_names_itself():
    run = EvalRun(id=uuid.uuid4(), agent_id=uuid.uuid4(), status="queued")
    arm = EvalRunArm(eval_run_id=run.id, role="candidate", source="draft")
    case = EvalRunCase(eval_run_id=run.id, case_id=uuid.uuid4(), attempt=1, status="pending")

    assert "status=queued" in repr(run)
    assert "role=candidate" in repr(arm)
    assert "attempt=1" in repr(case)


@pytest.mark.anyio
async def test_invalid_draft_eval_explains_evaluation_without_talking_about_publishing() -> None:
    from unittest.mock import AsyncMock

    from app.agents.spec import AgentSpec
    from app.core.exceptions import BadRequestError
    from app.core.permissions import AuthContext, OrgRoleName
    from app.db.models.agent import Agent
    from app.db.models.eval_run import ArmRole, ArmSource
    from app.services.eval_run import EvalRunService

    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)
    service = EvalRunService(AsyncMock())
    service.registry.get_candidate_spec = AsyncMock(
        side_effect=BadRequestError(
            message="This agent cannot be published yet",
            details={"problems": ["The selected model profile no longer exists"]},
        )
    )
    with pytest.raises(BadRequestError, match="draft cannot be evaluated") as refused:
        await service._arm(
            ctx,
            Agent(id=uuid.uuid4()),
            role=ArmRole.CANDIDATE,
            source=ArmSource.DRAFT,
            version=None,
            spec=AgentSpec(name="Draft"),
            model_profile_id=None,
            environment_id=None,
        )
    assert refused.value.details == {"problems": ["The selected model profile no longer exists"]}


@pytest.mark.anyio
async def test_a_reevaluation_by_nobody_still_named_reads_without_a_name() -> None:
    """Whoever re-evaluated was removed since; nothing is looked up for them."""
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from app.services.eval_run import EvalRunService

    db = AsyncMock()
    review = await EvalRunService(db).named_review(
        uuid.uuid4(),
        {"by_user_id": None, "at": datetime.now(UTC).isoformat(), "verdict": "passed"},
    )

    assert review is not None
    assert (review.by_user_id, review.by_name, review.verdict) == (None, None, "passed")
    db.execute.assert_not_awaited()


def test_a_side_names_each_skill_it_was_served_once_by_its_stored_version() -> None:
    """The agent and an inline specialist may read one skill; a deleted version is
    left out rather than named by an id nobody can open."""
    skill, other = uuid.uuid4(), uuid.uuid4()
    main_v3 = SimpleNamespace(id=uuid.uuid4(), skill_id=skill, number=3, fork_id=None)
    fork = SimpleNamespace(id=uuid.uuid4(), name="Returns")
    fork_v2 = SimpleNamespace(id=uuid.uuid4(), skill_id=other, number=2, fork_id=fork.id)
    served = {
        f":{skill}": str(main_v3.id),
        f"helper:{skill}": str(main_v3.id),
        f":{other}": str(fork_v2.id),
        f":{uuid.uuid4()}": str(uuid.uuid4()),
    }

    named = _served_skill_versions(
        served, {main_v3.id: main_v3, fork_v2.id: fork_v2}, {fork.id: fork}
    )

    assert [(v.skill_id, v.number, v.fork_name) for v in named] == [
        (skill, 3, None),
        (other, 2, "Returns"),
    ]
    assert _served_skill_versions(None, {}, {}) == []


def test_inherited_and_frozen_judge_instructions_share_a_scoring_fingerprint() -> None:
    from app.agents.system_agents import JUDGE

    inherited = _scoring()
    frozen = inherited.model_copy(deep=True)
    frozen.judge.instructions = JUDGE.instructions
    assert scoring_hash(inherited) == scoring_hash(frozen)
    frozen.judge.instructions = "Different grading instructions."
    assert scoring_hash(inherited) != scoring_hash(frozen)
