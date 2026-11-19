"""What the helper writing an attempt reads about the session's earlier ones."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.authoring import SpecProposalHunk
from app.db.models.improvement import ImprovementVerdict
from app.repositories import authoring_repo, improvement_repo
from app.schemas.eval_run import CriterionMoveRead
from app.services.authoring_worker import _earlier_section
from app.services.eval_run import EvalRunService
from app.services.improvement_pipeline import (
    EarlierAttempt,
    ImprovementPipelineService,
    _change_text,
)

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


def _hunk(**fields: object) -> SpecProposalHunk:
    return SpecProposalHunk(id=uuid.uuid4(), **fields)


class TestChangeText:
    def test_an_instructions_edit_reads_as_the_passage_it_replaced_and_the_text_kept(self):
        hunk = _hunk(
            kind="instructions", old_text="Be brief.", new_text="Be long.", edited_text="Be kind."
        )

        text = _change_text(hunk)

        assert "In the instructions, replaced:" in text
        assert "<old>\nBe brief.\n</old>" in text and "<new>\nBe kind.\n</new>" in text

    def test_a_skill_passage_says_it_was_in_a_skill(self):
        hunk = _hunk(kind="skill_body", old_text="a", new_text="b", edited_text=None)

        assert _change_text(hunk).startswith("In a skill's body, replaced:")

    def test_a_field_reads_as_its_operation_path_and_value(self):
        hunk = _hunk(kind="spec_field", op="add", path="capabilities", new_value={"id": "clock"})

        assert _change_text(hunk) == 'add capabilities: {"id": "clock"}'

    def test_a_tool_reads_as_its_new_name_and_description(self):
        hunk = _hunk(
            kind="tool_override",
            capability_id="knowledge",
            tool_id="search",
            new_name="find",
            new_description="Search first",
        )

        assert (
            _change_text(hunk) == "Tool knowledge/search: name 'find', description 'Search first'"
        )

    def test_anything_else_reads_as_its_kind_and_new_text(self):
        hunk = _hunk(kind="create_skill", new_text="", new_description="Quote layout")

        assert _change_text(hunk) == "create_skill: Quote layout"


class TestEarlierSection:
    def test_a_first_attempt_reads_nothing_about_earlier_ones(self):
        assert _earlier_section([]) == ""

    def test_each_attempt_says_what_it_changed_what_moved_and_only_how_many_held_out_broke(self):
        attempts = [
            EarlierAttempt(
                number=1,
                verdict=ImprovementVerdict.REGRESSION,
                changes=("add capabilities: {}",),
                held_out=35,
                fixed=0,
                broken=2,
                criteria=(_move("Names the next price band", 1, 4),),
            ),
            EarlierAttempt(
                number=2,
                verdict=ImprovementVerdict.NO_CHANGE,
                changes=(),
                held_out=35,
                fixed=0,
                broken=0,
                criteria=(),
            ),
        ]

        text = _earlier_section(attempts)

        assert "None of these changes is in the draft above" in text
        assert "## Attempt 1: regression\n- add capabilities: {}" in text
        assert "On 35 held-out questions it fixed 0 and broke 2. Which ones stays hidden." in text
        assert "- [judge] Names the next price band: 1/4 -> 4/4" in text
        assert "## Attempt 2: no_change" in text
        assert "No criterion moved on the questions it learned from." in text


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
        kept, other = (
            _hunk(kind="spec_field", op="set", path="x", new_value=1),
            _hunk(kind="spec_field", op="set", path="y", new_value=2),
        )
        iterations = [
            self._iteration(1, included_hunk_ids=[kept.id]),
            self._iteration(2, verdict=None),
            self._iteration(3, batch_id=None),
            self._iteration(4),
        ]
        monkeypatch.setattr(improvement_repo, "list_iterations", AsyncMock(return_value=iterations))
        monkeypatch.setattr(authoring_repo, "list_hunks", AsyncMock(return_value=[kept, other]))
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

        (attempt,) = await ImprovementPipelineService(mock_db_session).earlier_attempts(
            ctx, uuid.uuid4(), before=4
        )

        assert (attempt.number, attempt.verdict) == (1, ImprovementVerdict.REGRESSION)
        assert attempt.changes == ("set x: 1",)
        assert (attempt.held_out, attempt.fixed, attempt.broken) == (5, 1, 2)
        assert [move.name for move in attempt.criteria] == ["moved", "net unchanged"]
        assert compare.await_args.kwargs == {"training_only": True}

    @pytest.mark.parametrize(
        "compared",
        [
            AsyncMock(side_effect=NotFoundError(message="gone")),
            AsyncMock(return_value=SimpleNamespace(verdict="invalid", criteria=[_move("m", 0, 1)])),
        ],
    )
    async def test_a_check_that_cannot_be_read_or_did_not_measure_moves_no_criterion(
        self, monkeypatch, mock_db_session, ctx, compared
    ):
        monkeypatch.setattr(
            improvement_repo,
            "list_iterations",
            AsyncMock(return_value=[self._iteration(1, verdict_detail=None)]),
        )
        monkeypatch.setattr(authoring_repo, "list_hunks", AsyncMock(return_value=[]))
        monkeypatch.setattr(EvalRunService, "compare", compared)

        (attempt,) = await ImprovementPipelineService(mock_db_session).earlier_attempts(
            ctx, uuid.uuid4(), before=2
        )

        assert attempt.criteria == ()
        assert (attempt.held_out, attempt.fixed, attempt.broken) == (0, 0, 0)

    async def test_an_attempt_without_a_check_run_moves_no_criterion(
        self, monkeypatch, mock_db_session, ctx
    ):
        monkeypatch.setattr(
            improvement_repo,
            "list_iterations",
            AsyncMock(return_value=[self._iteration(1, eval_run_ids=[])]),
        )
        monkeypatch.setattr(authoring_repo, "list_hunks", AsyncMock(return_value=[]))

        (attempt,) = await ImprovementPipelineService(mock_db_session).earlier_attempts(
            ctx, uuid.uuid4(), before=2
        )

        assert attempt.criteria == ()


def test_a_large_instruction_replacement_is_an_explicit_bounded_excerpt():
    text = _change_text(_hunk(kind="instructions", old_text="a" * 100_000, new_text="b" * 100_000))
    assert len(text) < 4100
    assert "change excerpt clipped" in text
    assert text.startswith("In the instructions") and text.endswith("</new>")
    assert all(text.count(tag) == 1 for tag in ("<old>", "</old>", "<new>", "</new>"))


def test_earlier_attempts_have_a_total_prompt_bound_and_keep_recent_evidence():
    attempts = [
        EarlierAttempt(
            number=n,
            verdict=ImprovementVerdict.NO_CHANGE,
            changes=("x" * 5000,) * 20,
            held_out=10,
            fixed=0,
            broken=0,
            criteria=(),
        )
        for n in range(10)
    ]
    text = _earlier_section(attempts)
    assert len(text) < 25_000
    assert "## Attempt 9:" in text
    assert "## Attempt 0:" not in text
    assert "clipped" in text


def test_an_unchanged_tool_name_remains_absent_in_the_change_description():
    text = _change_text(
        _hunk(
            kind="tool_override",
            capability_id="knowledge",
            tool_id="search",
            new_name=None,
            new_description="Search first",
        )
    )
    assert "name None," in text


def test_retry_evidence_distinguishes_equal_names_from_different_scorers():
    judge = _move("Validity", 1, 2).model_copy(update={"fixed_confirmed": 1})
    check = _move("Validity", 2, 1).model_copy(update={"scorer": "check", "broken_confirmed": 1})
    text = _earlier_section(
        [
            EarlierAttempt(
                number=1,
                verdict=ImprovementVerdict.CRITERIA_WORSE,
                changes=(),
                held_out=5,
                fixed=0,
                broken=0,
                criteria=(judge, check),
            )
        ]
    )
    assert "[judge] Validity: 1/4 -> 2/4; confirmed fixes: 1" in text
    assert "[check] Validity: 2/4 -> 1/4; confirmed fixes: 0, confirmed breaks: 1" in text
