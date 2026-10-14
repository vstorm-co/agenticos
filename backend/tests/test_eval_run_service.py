"""The parts of an eval run decided without running anything: refusals, outcomes, fingerprints."""

import uuid
from types import SimpleNamespace

import pytest

from app.db.models.eval_run import CaseAttemptStatus, EvalRun, EvalRunArm, EvalRunCase
from app.schemas.scoring import DatasetScoring
from app.services.eval_run import attempt_outcome, scoring_hash, scoring_refusal


def _case(*, checks=(), expected=(), reference=None):
    return SimpleNamespace(
        checks=list(checks), expected_tool_calls=list(expected), reference_answer=reference
    )


def _scoring(**overrides) -> DatasetScoring:
    return DatasetScoring.model_validate(overrides)


class TestScoringRefusal:
    def test_a_check_on_a_case_decides_it(self):
        scoring = _scoring()
        cases = [_case(checks=[{"type": "contains", "value": "30 days"}])]
        assert scoring_refusal(scoring, cases, ai_enabled=False) is None

    def test_a_default_check_decides_every_case(self):
        scoring = _scoring(checks={"defaults": [{"type": "contains", "value": "x"}]})
        assert scoring_refusal(scoring, [_case()], ai_enabled=False) is None

    def test_an_expected_call_decides_it(self):
        cases = [_case(expected=[{"tool": "lookup", "args": {}}])]
        assert scoring_refusal(_scoring(), cases, ai_enabled=False) is None

    def test_nothing_to_check_is_refused_with_what_to_add(self):
        refusal = scoring_refusal(_scoring(), [_case(reference="yes")], ai_enabled=True)
        assert refusal is not None
        assert refusal.details == {"reason": "no_scorer"}
        assert "Add a check" in refusal.message

    def test_only_a_judge_with_ai_assistance_off_says_the_judge_cannot_run(self):
        scoring = _scoring(
            checks={"enabled": False},
            trajectory={"enabled": False},
            judge={"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]},
        )
        refusal = scoring_refusal(scoring, [_case()], ai_enabled=False)
        assert refusal is not None
        assert refusal.details == {"reason": "ai_assistance_off"}
        assert "AI assistance is off" in refusal.message

    def test_a_judge_runs_when_ai_assistance_is_on(self):
        scoring = _scoring(
            judge={"enabled": True, "criteria": [{"name": "Tone", "description": "Polite"}]}
        )
        assert scoring_refusal(scoring, [_case()], ai_enabled=True) is None

    def test_a_reference_answer_needs_the_judge(self):
        scoring = _scoring(reference={"enabled": True})
        cases = [_case(reference="30 days")]
        assert scoring_refusal(scoring, cases, ai_enabled=True) is None
        assert scoring_refusal(scoring, cases, ai_enabled=False) is not None

    def test_a_judge_check_on_a_case_needs_the_judge(self):
        cases = [_case(checks=[{"type": "judge", "criterion": "Cites a source"}])]
        assert scoring_refusal(_scoring(), cases, ai_enabled=True) is None
        refusal = scoring_refusal(_scoring(), cases, ai_enabled=False)
        assert refusal is not None and refusal.details == {"reason": "ai_assistance_off"}

    def test_an_optional_scorer_decides_nothing(self):
        scoring = _scoring(checks={"required": False}, trajectory={"required": False})
        cases = [_case(checks=[{"type": "contains", "value": "x"}], expected=[{"tool": "t"}])]
        assert scoring_refusal(scoring, cases, ai_enabled=True) is not None


class TestAttemptOutcome:
    def _attempt(self, status=CaseAttemptStatus.DONE):
        return SimpleNamespace(status=status.value)

    def test_a_persons_verdict_wins_over_the_scorers(self):
        score = SimpleNamespace(passed=True, human_passed=False)
        assert attempt_outcome(self._attempt(), score) is False

    def test_the_scorers_decide_without_a_verdict(self):
        score = SimpleNamespace(passed=True, human_passed=None)
        assert attempt_outcome(self._attempt(), score) is True

    @pytest.mark.parametrize("status", [CaseAttemptStatus.FAILED, CaseAttemptStatus.SKIPPED])
    def test_an_attempt_that_did_not_finish_is_undecided(self, status):
        score = SimpleNamespace(passed=True, human_passed=None)
        assert attempt_outcome(self._attempt(status), score) is None

    def test_an_unscored_attempt_is_undecided(self):
        assert attempt_outcome(self._attempt(), None) is None


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
