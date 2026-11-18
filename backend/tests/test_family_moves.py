"""Criteria counted by family: settled by their own spread, or by asking again.

A dataset's per-case checks each carry their own name - every case's VAT total is
a regex on a different amount - so a comparison that counts names separately sees
one case per criterion, and one case repeated three times decides a verdict. A
family counts those checks together, case by case.
"""

import pytest

from app.services.eval_comparison import (
    MIN_FAMILY_CASES,
    FamilyMove,
    PairedGrades,
    families,
    family_flipped,
    family_moves,
    family_of,
    family_outcomes,
)

ALPHA = 0.05
_PRICE = ("judge", "Points out the next price band")
_TERMS = ("judge", "Payment terms stated")


def _vat(amount: str) -> tuple[str, str]:
    return ("check", f"regex '£{amount}'")


_NAMED = {_vat(a): "total including VAT" for a in ("913.68", "252.00", "129.60", "198.00")}


def _case(before: dict, after: dict, *, reruns: int = 0, drift: bool = False) -> PairedGrades:
    return PairedGrades(
        baseline=before,
        candidate=after,
        baseline_reruns=(before,) * reruns,
        candidate_reruns=(after,) * reruns,
        drift=drift,
    )


def _move(**overrides) -> FamilyMove:
    values = {
        "family": "f",
        "criteria": ("f",),
        "cases": 10,
        "baseline_passed": 0,
        "candidate_passed": 0,
        "fixed": 0,
        "broken": 0,
        "fixed_confirmed": 0,
        "broken_confirmed": 0,
        "p_value": 1.0,
        "settled": False,
    }
    return FamilyMove(**(values | overrides))


class TestFamiliesFromScores:
    def test_a_named_family_is_read_keyed_as_grades_are_and_an_unnamed_one_left_out(self) -> None:
        results = [
            {"scorer": "check", "name": "json_schema", "status": "pass", "family": "shape"},
            {"scorer": "check", "name": "json_schema", "status": "fail", "family": "shape"},
            {"scorer": "judge", "name": "tone", "status": "pass"},
            {
                "scorer": "judge",
                "name": "aside",
                "status": "pass",
                "required": False,
                "family": "x",
            },
        ]

        assert families(results) == {
            ("check", "json_schema"): "shape",
            ("check", "json_schema #2"): "shape",
        }

    def test_a_criterion_without_a_family_is_its_own(self) -> None:
        assert family_of(_TERMS, _NAMED) == "Payment terms stated"
        assert family_of(_vat("913.68"), _NAMED) == "total including VAT"


class TestFamilyOutcome:
    @pytest.mark.parametrize(
        ("outcomes", "expected"),
        [
            ((True, True), True),
            ((True, False), False),
            ((None, False), False),
            ((True, None), None),
        ],
    )
    def test_a_family_passes_in_a_case_only_when_every_criterion_of_it_does(
        self, outcomes, expected
    ) -> None:
        named = {("check", "a"): "f", ("check", "b"): "f"}
        graded = {("check", "a"): outcomes[0], ("check", "b"): outcomes[1]}

        assert family_outcomes(graded, named) == {"f": expected}


class TestFamilyMoves:
    def test_a_family_that_moved_on_many_cases_is_settled_without_asking_again(self) -> None:
        cases = [_case({_PRICE: False, _TERMS: False}, {_PRICE: True, _TERMS: False})] * 25
        cases += [_case({_PRICE: True, _TERMS: False}, {_PRICE: True, _TERMS: False})] * 3

        terms, price = family_moves(cases, {}, alpha=ALPHA)

        assert (price.family, price.cases, price.baseline_passed, price.candidate_passed) == (
            _PRICE[1],
            28,
            3,
            28,
        )
        assert (price.fixed, price.fixed_confirmed, price.settled) == (25, 0, True)
        assert price.better and not price.needs_reruns
        assert not terms.moved and not terms.better and not terms.worse

    def test_per_case_checks_of_one_family_count_together_case_by_case(self) -> None:
        cases = [
            _case({_vat(amount): True}, {_vat(amount): False})
            for amount in ("913.68", "252.00", "129.60", "198.00")
        ]

        [vat] = family_moves(cases, _NAMED, alpha=ALPHA)

        assert vat.family == "total including VAT"
        assert vat.criteria == tuple(sorted(name for _, name in _NAMED))
        assert (vat.cases, vat.broken, vat.settled, vat.needs_reruns) == (4, 4, False, True)
        assert not vat.worse

    def test_an_unsettled_family_counts_what_the_reruns_repeated(self) -> None:
        cases = [
            _case({_vat("913.68"): True}, {_vat("913.68"): False}, reruns=2),
            _case({_vat("252.00"): True}, {_vat("252.00"): False}, reruns=2),
            _case({_vat("129.60"): True}, {_vat("129.60"): False}),
        ]

        [vat] = family_moves(cases, _NAMED, alpha=ALPHA)

        assert (vat.broken, vat.broken_confirmed, vat.broken_held) == (3, 2, 2)
        assert vat.worse

    def test_one_case_never_decides_a_family_either_way(self) -> None:
        [vat] = family_moves(
            [_case({_vat("913.68"): True}, {_vat("913.68"): False}, reruns=2)],
            _NAMED,
            alpha=ALPHA,
        )

        assert (vat.broken_confirmed, vat.moved, vat.worse, vat.needs_reruns) == (
            1,
            False,
            False,
            False,
        )

    def test_a_criterion_graded_on_one_side_only_is_not_compared(self) -> None:
        moves = family_moves([_case({_PRICE: False}, {_TERMS: True})], {}, alpha=ALPHA)

        assert moves == []


class TestFamilyVerdicts:
    def test_more_broken_than_fixed_is_worse_and_the_reverse_better(self) -> None:
        assert _move(broken_confirmed=3, fixed_confirmed=1).worse
        assert not _move(broken_confirmed=3, fixed_confirmed=3).worse
        assert _move(fixed_confirmed=2, baseline_passed=1, candidate_passed=3).better

    def test_better_needs_no_fewer_passes_than_before(self) -> None:
        assert not _move(fixed_confirmed=2, baseline_passed=5, candidate_passed=4).better

    def test_a_settled_family_counts_every_flip_it_had(self) -> None:
        move = _move(fixed=1, broken=7, settled=True, p_value=0.03)

        assert (move.broken_held, move.fixed_held, move.worse) == (7, 1, True)

    def test_the_minimum_is_two_cases(self) -> None:
        assert MIN_FAMILY_CASES == 2


class TestFamilyFlipped:
    def test_only_a_flip_in_a_family_still_to_be_decided_counts(self) -> None:
        before = {_PRICE: False, _vat("913.68"): True}
        after = {_PRICE: True, _vat("913.68"): False}

        assert family_flipped(before, after, _NAMED, {"total including VAT"})
        assert not family_flipped(before, after, _NAMED, {"Payment terms stated"})
        assert not family_flipped(before, before, _NAMED, {"total including VAT", _PRICE[1]})
