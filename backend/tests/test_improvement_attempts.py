"""What the helper writing an attempt reads about the session's earlier ones."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.improvement import ImprovementVerdict
from app.repositories import improvement_repo
from app.schemas.eval_run import CriterionMoveRead
from app.services.authoring_worker import _earlier_section
from app.services.eval_run import EvalRunService
from app.services.improvement_pipeline import EarlierAttempt, ImprovementPipelineService

pytestmark = pytest.mark.anyio


def _move(name: str, before: int, after: int, graded: int = 4) -> CriterionMoveRead:
    return CriterionMoveRead(
        scorer="judge",
        name=name,
        graded=graded,
        baseline_passed=before,
        candidate_passed=after,
        fixed_confirmed=0,
        broken_confirmed=0,
        fixed_unconfirmed=0,
        broken_unconfirmed=0,
    )


class TestEarlierSection:
    def test_a_first_attempt_reads_nothing_about_earlier_ones(self):
        assert _earlier_section([]) == ""

    def test_each_attempt_says_how_it_was_judged_and_never_what_it_changed(self):
        """An earlier change was written from questions this attempt may be measured on."""
        attempts = [
            EarlierAttempt(
                number=1,
                verdict=ImprovementVerdict.REGRESSION,
                held_out=35,
                fixed=0,
                broken=2,
                criteria=(_move("Names the next price band", 1, 4),),
            ),
            EarlierAttempt(
                number=2,
                verdict=ImprovementVerdict.NO_CHANGE,
                held_out=35,
                fixed=0,
                broken=0,
                criteria=(),
            ),
            EarlierAttempt(
                number=3,
                verdict=ImprovementVerdict.NO_CHANGE,
                held_out=35,
                fixed=0,
                broken=0,
                criteria=None,
            ),
        ]

        text = _earlier_section(attempts)

        assert "What each changed is left out on purpose" in text
        assert "None of their changes is in the draft above" in text
        assert "## Attempt 1: regression\nOn 35 held-out questions it fixed 0 and broke 2." in text
        assert "Which ones stays hidden." in text
        assert "- [judge] Names the next price band: 1/4 -> 4/4" in text
        assert "## Attempt 2: no_change" in text
        assert "No criterion moved on this attempt's training questions." in text
        assert "## Attempt 3: no_change" in text
        assert "No criteria on this attempt's training questions." in text
        assert "0/0" not in text


class TestEarlierAttempts:
    @pytest.fixture
    def ctx(self) -> SimpleNamespace:
        return SimpleNamespace(organization_id=uuid.uuid4())

    def _iteration(self, number: int, **fields: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "number": number,
            "verdict": "regression",
            "batch_id": uuid.uuid4(),
            "included_hunk_ids": None,
            "eval_run_ids": [uuid.uuid4()],
            "verdict_detail": {"held_out": 5, "fixed": 1, "broken": 2},
        }
        values.update(fields)
        return SimpleNamespace(**values)

    async def test_only_measured_attempts_before_the_one_being_written_are_read(
        self, monkeypatch, mock_db_session, ctx
    ):
        iterations = [
            self._iteration(1),
            self._iteration(2, verdict=None),
            self._iteration(3, batch_id=None),
            self._iteration(4),
        ]
        monkeypatch.setattr(improvement_repo, "list_iterations", AsyncMock(return_value=iterations))
        compare = AsyncMock(
            return_value=SimpleNamespace(
                verdict="worse",
                criteria=[
                    _move("moved", 1, 3).model_copy(update={"fixed_confirmed": 2}),
                    _move("noise", 1, 3),
                    _move("net unchanged", 2, 2).model_copy(update={"broken_confirmed": 1}),
                ],
            )
        )
        monkeypatch.setattr(EvalRunService, "compare", compare)
        learning = [uuid.uuid4(), uuid.uuid4()]

        (attempt,) = await ImprovementPipelineService(mock_db_session).earlier_attempts(
            ctx, uuid.uuid4(), before=4, learns_from=learning
        )

        assert (attempt.number, attempt.verdict) == (1, ImprovementVerdict.REGRESSION)
        assert (attempt.held_out, attempt.fixed, attempt.broken) == (5, 1, 2)
        assert attempt.criteria is not None
        assert [move.name for move in attempt.criteria] == ["moved", "net unchanged"]
        assert compare.await_args.kwargs == {"training_only": True, "within": learning}

    @pytest.mark.parametrize(
        "compared",
        [
            AsyncMock(side_effect=NotFoundError(message="gone")),
            AsyncMock(return_value=SimpleNamespace(verdict="invalid", criteria=[_move("m", 0, 1)])),
            AsyncMock(
                return_value=SimpleNamespace(
                    verdict="no_difference", criteria=[_move("m", 0, 0, 0)]
                )
            ),
            AsyncMock(return_value=SimpleNamespace(verdict="no_difference", criteria=[])),
        ],
    )
    async def test_a_check_that_graded_none_of_the_questions_learned_from_says_so(
        self, monkeypatch, mock_db_session, ctx, compared
    ):
        """Zeros would read as a result; the check simply did not measure these questions."""
        monkeypatch.setattr(
            improvement_repo,
            "list_iterations",
            AsyncMock(return_value=[self._iteration(1, verdict_detail=None)]),
        )
        monkeypatch.setattr(EvalRunService, "compare", compared)

        (attempt,) = await ImprovementPipelineService(mock_db_session).earlier_attempts(
            ctx, uuid.uuid4(), before=2, learns_from=[uuid.uuid4()]
        )

        assert attempt.criteria is None
        assert (attempt.held_out, attempt.fixed, attempt.broken) == (0, 0, 0)

    @pytest.mark.parametrize(
        ("eval_run_ids", "learns_from"), [([], [uuid.uuid4()]), ([uuid.uuid4()], None)]
    )
    async def test_with_no_check_or_nothing_to_learn_from_no_criterion_is_read(
        self, monkeypatch, mock_db_session, ctx, eval_run_ids, learns_from
    ):
        monkeypatch.setattr(
            improvement_repo,
            "list_iterations",
            AsyncMock(return_value=[self._iteration(1, eval_run_ids=eval_run_ids)]),
        )
        compare = AsyncMock()
        monkeypatch.setattr(EvalRunService, "compare", compare)

        (attempt,) = await ImprovementPipelineService(mock_db_session).earlier_attempts(
            ctx, uuid.uuid4(), before=2, learns_from=learns_from
        )

        assert attempt.criteria is None
        compare.assert_not_awaited()


def test_earlier_attempts_have_a_total_prompt_bound_and_keep_recent_evidence():
    attempts = [
        EarlierAttempt(
            number=n,
            verdict=ImprovementVerdict.NO_CHANGE,
            held_out=10,
            fixed=0,
            broken=0,
            criteria=tuple(_move("x" * 200, 0, 1) for _ in range(20)),
        )
        for n in range(10)
    ]
    text = _earlier_section(attempts)
    assert len(text) < 25_000
    assert "## Attempt 9:" in text
    assert "## Attempt 0:" not in text
    assert "clipped" in text


def test_retry_evidence_distinguishes_equal_names_from_different_scorers():
    judge = _move("Validity", 1, 2).model_copy(update={"fixed_confirmed": 1})
    check = _move("Validity", 2, 1).model_copy(update={"scorer": "check", "broken_confirmed": 1})
    text = _earlier_section(
        [
            EarlierAttempt(
                number=1,
                verdict=ImprovementVerdict.CRITERIA_WORSE,
                held_out=5,
                fixed=0,
                broken=0,
                criteria=(judge, check),
            )
        ]
    )
    assert "[judge] Validity: 1/4 -> 2/4; confirmed fixes: 1" in text
    assert "[check] Validity: 2/4 -> 1/4; confirmed fixes: 0, confirmed breaks: 1" in text
