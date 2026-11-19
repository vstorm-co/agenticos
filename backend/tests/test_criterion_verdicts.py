"""A change judged criterion by criterion when no whole question flips.

A question passes only when every criterion it is graded on passes. A change
that fixes one of three failing criteria flips no question, and used to be
judged no change; these pin what it is judged now, and that a criterion that
got worse reads as plainly as one that got better.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.db.models.improvement import (
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)
from app.services.eval_comparison import (
    CriterionMove,
    PairedGrades,
    compare_criteria,
    criterion_flipped,
    grades,
)
from app.services.improvement_states import (
    MAX_CRITERIA,
    CheckResult,
    RoundResult,
    after_judging,
    best_round,
    criterion_details,
    criterion_owners,
    judge,
)

_PRICE = ("judge", "price break")
_VALIDITY = ("judge", "validity")
_TERMS = ("judge", "payment terms")


def _quote(*, price: bool, reruns: int = 2) -> PairedGrades:
    """A quote case that fails on the skill's two criteria either way; `price` is the
    candidate's grade on the criterion the change is about, the baseline failing it."""
    before = {_PRICE: False, _VALIDITY: False, _TERMS: False}
    after = {_PRICE: price, _VALIDITY: False, _TERMS: False}
    return PairedGrades(
        baseline=before,
        candidate=after,
        baseline_reruns=(before,) * reruns,
        candidate_reruns=(after,) * reruns,
    )


def _held_steady() -> PairedGrades:
    """A quote case the baseline already priced right; nothing moved on it."""
    graded = {_PRICE: True, _VALIDITY: False, _TERMS: False}
    return PairedGrades(baseline=graded, candidate=graded)


def _experiment() -> list[CriterionMove]:
    """The price break went from 9 of 40 to 40 of 40; every quote still fails validity
    and payment terms, so no question flips."""
    return compare_criteria([_quote(price=True) for _ in range(31)] + [_held_steady()] * 9).moves


def _named(moves: list[CriterionMove], name: str) -> CriterionMove:
    return next(move for move in moves if move.name == name)


def _no_question_flipped(*moves: CriterionMove) -> CheckResult:
    return CheckResult(
        comparable=True,
        incomplete=0,
        ungraded=0,
        regressions_confirmed=0,
        fixed_confirmed=0,
        candidate_pass_rate=1 / 3,
        baseline_pass_rate=1 / 3,
        criteria=moves,
    )


def test_a_criterion_fixed_on_every_quote_is_counted_before_and_after() -> None:
    moves = _experiment()
    price = _named(moves, "price break")
    assert (price.graded, price.baseline_passed, price.candidate_passed) == (40, 9, 40)
    assert (price.fixed_confirmed, price.broken_confirmed) == (31, 0)
    assert price.better and not price.worse
    assert _named(moves, "validity").candidate_passed == 0
    assert not _named(moves, "validity").better


def test_a_criterion_fixed_with_no_question_flipped_is_criteria_better() -> None:
    assert judge(_no_question_flipped(*_experiment())) is ImprovementVerdict.CRITERIA_BETTER


def test_the_criterion_that_moved_is_named_and_the_ones_still_failing_follow_it() -> None:
    details = criterion_details(_experiment(), {"validity": "Quote rules"})

    assert details[0] == {
        "scorer": "judge",
        "name": "price break",
        "graded": 40,
        "before": 9,
        "after": 40,
        "fixed": 31,
        "broken": 0,
    }
    assert [(item["name"], item.get("skill")) for item in details[1:]] == [
        ("payment terms", None),
        ("validity", "Quote rules"),
    ]


def test_a_criterion_that_got_worse_is_criteria_worse_whatever_else_improved() -> None:
    worse = CriterionMove("check", "under 200 words", 40, 40, 9, 0, 31)
    assert worse.worse

    assert judge(_no_question_flipped(*_experiment(), worse)) is ImprovementVerdict.CRITERIA_WORSE


def test_a_criterion_move_the_reruns_did_not_repeat_is_no_change() -> None:
    wobbling = replace(_quote(price=True), candidate_reruns=({_PRICE: False},))
    moves = compare_criteria([wobbling]).moves
    price = _named(moves, "price break")

    assert price.fixed_unconfirmed == 1 and price.fixed_confirmed == 0
    assert judge(_no_question_flipped(*moves)) is ImprovementVerdict.NO_CHANGE


def test_a_criterion_flip_the_baseline_was_never_rerun_on_is_unconfirmed() -> None:
    unrerun = replace(_quote(price=True), baseline_reruns=())

    assert _named(compare_criteria([unrerun]).moves, "price break").fixed_confirmed == 0
    drifted = compare_criteria([replace(unrerun, drift=True)]).moves
    assert _named(drifted, "price break").fixed_confirmed == 1


def test_a_criterion_fixed_on_fewer_passes_than_before_is_not_better() -> None:
    assert not CriterionMove("judge", "tone", 10, 6, 5, 1, 0).better


def test_a_whole_question_fixed_stays_better_beside_a_criterion_that_got_worse() -> None:
    worse = CriterionMove("check", "under 200 words", 40, 40, 39, 0, 1)
    result = replace(
        _no_question_flipped(worse),
        fixed_confirmed=2,
        candidate_pass_rate=0.5,
    )

    assert judge(result) is ImprovementVerdict.BETTER


def test_a_question_broken_is_a_regression_whatever_the_criteria_say() -> None:
    result = replace(_no_question_flipped(*_experiment()), regressions_confirmed=1)

    assert judge(result) is ImprovementVerdict.REGRESSION


def test_an_attempt_better_on_criteria_waits_for_a_person_like_a_better_one() -> None:
    transition = after_judging(
        ImprovementVerdict.CRITERIA_BETTER,
        reruns_used=0,
        spent=Decimal(0),
        rerun_estimate=Decimal(0),
        budget=Decimal(1),
    )

    assert transition.status is ImprovementStatus.READY
    assert transition.stage is ImprovementStage.JUDGING


def test_an_attempt_worse_on_criteria_stops_saying_so() -> None:
    transition = after_judging(
        ImprovementVerdict.CRITERIA_WORSE,
        reruns_used=0,
        spent=Decimal(0),
        rerun_estimate=Decimal(0),
        budget=Decimal(1),
    )

    assert transition.status is ImprovementStatus.STOPPED
    assert transition.stop_reason is StopReason.CRITERIA_WORSE


def test_criteria_rank_between_whole_questions_and_no_change() -> None:
    rounds = [
        RoundResult(1, ImprovementVerdict.CRITERIA_WORSE, 0, 0, 10),
        RoundResult(2, ImprovementVerdict.NO_CHANGE, 0, 0, 10),
        RoundResult(3, ImprovementVerdict.CRITERIA_BETTER, 0, 0, 10),
    ]

    assert best_round(rounds) == 3
    assert best_round([*rounds, RoundResult(4, ImprovementVerdict.BETTER, 1, 0, 10)]) == 4
    assert best_round(rounds[:2]) == 2


def test_stored_results_read_as_criterion_outcomes() -> None:
    stored = [
        {"scorer": "judge", "name": "price break", "status": "pass"},
        {"scorer": "check", "name": "contains 'EUR'", "status": "fail"},
        {"scorer": "judge", "name": "validity", "status": "error"},
    ]

    assert grades(stored) == {
        ("judge", "price break"): True,
        ("check", "contains 'EUR'"): False,
        ("judge", "validity"): None,
    }


def test_an_optional_result_is_no_criterion_as_it_is_no_part_of_the_question() -> None:
    stored = [
        {"scorer": "judge", "name": "price break", "required": True, "status": "pass"},
        {"scorer": "judge", "name": "tone", "required": False, "status": "fail"},
    ]

    assert grades(stored) == {("judge", "price break"): True}


def test_two_results_under_one_name_stay_two_criteria() -> None:
    stored = [
        {"scorer": "check", "name": "json_schema at $.total", "status": "pass"},
        {"scorer": "check", "name": "json_schema at $.total", "status": "fail"},
    ]

    assert grades(stored) == {
        ("check", "json_schema at $.total"): True,
        ("check", "json_schema at $.total #2"): False,
    }


@pytest.mark.parametrize("suffix_first", [False, True])
def test_a_literal_duplicate_suffix_does_not_hide_a_confirmed_criterion_flip(
    suffix_first: bool,
) -> None:
    repeated = [
        {"scorer": "check", "name": "json_schema at $.total", "status": "pass"},
        {"scorer": "check", "name": "json_schema at $.total", "status": "fail"},
    ]
    literal = {"scorer": "check", "name": "json_schema at $.total #2", "status": "pass"}
    stored = [literal, *repeated] if suffix_first else [*repeated, literal]

    before = grades(iter(stored))
    after = grades({**row, "status": "pass"} for row in stored)

    assert before == {
        ("check", "json_schema at $.total"): True,
        ("check", "json_schema at $.total #2"): True,
        ("check", "json_schema at $.total #3"): False,
    }
    assert criterion_flipped(before, after)


def test_past_the_limit_the_criteria_that_decide_a_verdict_are_kept() -> None:
    passing = {("check", f"check {n:03}"): True for n in range(300)}
    before = {**passing, _PRICE: False, _VALIDITY: True}
    after = {**passing, _PRICE: True, _VALIDITY: False}
    case = PairedGrades(
        baseline=before, candidate=after, baseline_reruns=(before,), candidate_reruns=(after,)
    )

    moves = compare_criteria([case], limit=3).moves

    assert [move.name for move in moves] == ["check 000", "price break", "validity"]
    assert _named(moves, "validity").worse and _named(moves, "price break").better


def test_only_a_criterion_graded_both_ways_counts_as_flipped() -> None:
    assert criterion_flipped({_PRICE: False}, {_PRICE: True})
    assert not criterion_flipped({_PRICE: False}, {_PRICE: False})
    assert not criterion_flipped({_PRICE: None}, {_PRICE: True})
    assert not criterion_flipped({_PRICE: False}, {})


def test_a_criterion_undecided_on_either_side_is_left_out_of_its_counts() -> None:
    undecided = PairedGrades(baseline={_PRICE: None}, candidate={_PRICE: True})

    assert compare_criteria([undecided]).moves == []


def test_a_criterion_broken_once_and_not_again_is_an_unconfirmed_break() -> None:
    broke = PairedGrades(
        baseline={_PRICE: True},
        candidate={_PRICE: False},
        baseline_reruns=({_PRICE: True},),
        candidate_reruns=({_PRICE: True},),
    )

    move = compare_criteria([broke]).moves[0]
    assert (move.broken_unconfirmed, move.broken_confirmed) == (1, 0)
    assert not move.worse


def test_the_newest_report_decides_which_skill_a_criterion_is_put_down_to() -> None:
    older = {"skill_problems": [{"skill_name": "Old rules", "criteria": ["Validity"]}]}
    newer = {
        "skill_problems": [
            {"skill_name": "Quote rules", "criteria": ["validity", "payment terms"]},
            {"skill_name": "Tone", "problem": "no criteria named"},
        ]
    }

    assert criterion_owners([newer, {}, older, None]) == {
        "validity": "Quote rules",
        "payment terms": "Quote rules",
    }


def test_a_criterion_that_passes_everywhere_is_not_put_down_to_a_skill() -> None:
    passing = CriterionMove("judge", "validity", 10, 10, 10, 0, 0)

    assert "skill" not in criterion_details([passing], {"validity": "Quote rules"})[0]


def test_a_verdict_keeps_the_criteria_that_moved_before_the_rest() -> None:
    quiet = [CriterionMove("check", f"check {n:02}", 1, 1, 1, 0, 0) for n in range(MAX_CRITERIA)]
    moved = CriterionMove("judge", "zz moved", 1, 0, 1, 1, 0)

    details = criterion_details([*quiet, moved], {})

    assert len(details) == MAX_CRITERIA
    assert details[0]["name"] == "zz moved"


@pytest.mark.security
def test_a_large_single_pass_comparison_constructs_only_the_kept_moves(monkeypatch):
    from unittest.mock import Mock

    from app.services import eval_comparison

    factory = Mock(wraps=CriterionMove)
    monkeypatch.setattr(eval_comparison, "CriterionMove", factory)

    def cases():
        for number in range(5000):
            unchanged = {("check", f"check {number:05}"): True}
            yield PairedGrades(baseline=unchanged, candidate=unchanged)
        before = {_PRICE: True}
        after = {_PRICE: False}
        yield PairedGrades(
            baseline=before, candidate=after, baseline_reruns=(before,), candidate_reruns=(after,)
        )

    moves = compare_criteria(cases()).moves

    assert len(moves) == 200
    assert factory.call_count == 200
    assert _named(moves, "price break").worse


@pytest.mark.parametrize("limit", [-1, 201])
def test_a_response_limit_cannot_disable_the_resource_bound(limit):
    with pytest.raises(ValueError, match="limit"):
        compare_criteria([], limit=limit)


def test_a_zero_limit_returns_no_moves():
    assert compare_criteria([_quote(price=True)], limit=0).moves == []


def test_a_name_only_skill_report_does_not_claim_another_scorers_criterion():
    judge = CriterionMove("judge", "Validity", 2, 0, 1, 1, 0)
    check = replace(judge, scorer="check")

    details = criterion_details([judge, check], {"validity": "Quote rules"})

    assert next(row for row in details if row["scorer"] == "judge")["skill"] == "Quote rules"
    assert "skill" not in next(row for row in details if row["scorer"] == "check")


def test_scratch_storage_closes_when_reading_criteria_fails(monkeypatch):
    import sqlite3

    from app.services import eval_comparison

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self) -> None:
            self.closed = True
            super().close()

    connect = sqlite3.connect
    connection = connect("", factory=TrackedConnection)
    monkeypatch.setattr(eval_comparison.sqlite3, "connect", lambda _name: connection)

    def interrupted():
        yield _quote(price=True)
        raise RuntimeError("input interrupted")

    with pytest.raises(RuntimeError, match="input interrupted"):
        compare_criteria(interrupted())
    assert connection.closed


def test_a_confirmed_break_survives_detail_truncation_ahead_of_many_fixes():
    fixes = [CriterionMove("judge", f"fix {n}", 100, 0, 1, 1, 0) for n in range(MAX_CRITERIA)]
    broken = CriterionMove("check", "critical break", 100, 100, 99, 0, 1)
    detail = criterion_details([*fixes, broken], {})
    assert len(detail) == MAX_CRITERIA
    assert detail[0]["name"] == "critical break" and detail[0]["broken"] == 1


@pytest.mark.parametrize("limit", [0, 1, 200])
def test_normalized_criterion_change_includes_rows_outside_the_display_limit(limit):
    before = {("check", f"check {number}"): False for number in range(205)}
    after = {**before, ("check", "check 0"): True}
    pair = PairedGrades(
        baseline=before, candidate=after, baseline_reruns=(before,), candidate_reruns=(after,)
    )
    result = compare_criteria([pair], limit=limit)
    assert len(result.moves) == limit
    assert result.change == pytest.approx(1 / 205)
    assert compare_criteria([PairedGrades(baseline=before, candidate=after)]).change == 0.0
    reversed_pair = PairedGrades(
        baseline=after, candidate=before, baseline_reruns=(after,), candidate_reruns=(before,)
    )
    assert compare_criteria([reversed_pair], limit=limit).change == pytest.approx(-1 / 205)
    assert compare_criteria([]).change == 0.0


def test_criterion_only_rounds_rank_normalized_confirmed_movement_and_keep_exact_ties():
    verdict = ImprovementVerdict.CRITERIA_BETTER
    assert (
        best_round(
            [
                RoundResult(1, verdict, 0, 0, 20, criterion_change=0.1),
                RoundResult(2, verdict, 0, 0, 20, criterion_change=0.3),
            ]
        )
        == 2
    )
    assert (
        best_round(
            [
                RoundResult(1, verdict, 0, 0, 10, criterion_change=0.2),
                RoundResult(2, verdict, 0, 0, 20, criterion_change=0.15),
            ]
        )
        == 1
    )
    assert (
        best_round(
            [
                RoundResult(1, verdict, 0, 0, 10, criterion_change=0.2),
                RoundResult(2, verdict, 0, 0, 20, criterion_change=0.2),
            ]
        )
        == 1
    )


def test_criterion_change_survives_stored_round_details():
    from app.db.models.improvement import ImprovementIteration
    from app.services.improvement_pipeline import ImprovementPipelineService

    result = replace(_no_question_flipped(*_experiment()), criterion_change=0.25)
    detail = ImprovementPipelineService._result_detail(result)
    iteration = ImprovementIteration(number=2, verdict="criteria_better", verdict_detail=detail)
    assert ImprovementPipelineService._round_result(iteration).criterion_change == 0.25
    assert (
        ImprovementPipelineService._round_result(
            ImprovementIteration(number=1, verdict="no_change", verdict_detail=None)
        ).criterion_change
        == 0.0
    )


@pytest.mark.parametrize("source", [None, "invalid", "00000000-0000-0000-0000-000000000123"])
def test_criterion_identity_comes_from_the_same_newest_report(source):
    from app.services.improvement_states import criterion_skill_ids

    older = {
        "skill_problems": [
            {
                "skill_name": "old",
                "skill_id": "00000000-0000-0000-0000-000000000001",
                "criteria": ["Validity"],
            }
        ]
    }
    newer = {
        "skill_problems": [
            {"skill_name": "new", "skill_id": source, "criteria": ["validity", "VALIDITY"]}
        ]
    }
    expected = {} if source in {None, "invalid"} else {"validity": source}
    assert criterion_skill_ids([newer, None, {}, older]) == expected
    details = criterion_details(_experiment(), criterion_owners([newer, older]), expected)
    attributed = [detail for detail in details if detail.get("skill") == "new"]
    assert attributed
    assert [detail.get("skill_id") for detail in attributed] == [expected.get("validity")] * len(
        attributed
    )


@pytest.mark.parametrize(
    "report",
    [
        {"skill_problems": None},
        {"skill_problems": [None]},
        {"skill_problems": [{"criteria": None}]},
        {"skill_problems": [{"criteria": [None]}]},
    ],
)
def test_malformed_historical_attributions_authorize_no_identity(report):
    from app.services.improvement_states import criterion_skill_ids

    assert criterion_skill_ids([report]) == {}


@pytest.mark.parametrize(
    "moves", [(), _experiment(), (CriterionMove("check", "length", 40, 40, 9, 0, 31),)]
)
def test_confirmed_whole_question_movement_never_becomes_a_criterion_only_verdict(moves):
    result = replace(
        _no_question_flipped(*moves),
        fixed_confirmed=1,
        candidate_pass_rate=0.1,
        baseline_pass_rate=0.5,
    )
    verdict = judge(result)
    assert verdict is ImprovementVerdict.NO_CHANGE
    transition = after_judging(
        verdict, reruns_used=0, spent=Decimal(0), rerun_estimate=Decimal(0), budget=Decimal(1)
    )
    assert transition.status is ImprovementStatus.STOPPED
    assert transition.stop_reason is StopReason.NO_CHANGE
