"""The rule a skill change is judged by: one agent's result, the change's, what a
person may do next, and which of an agent's own questions a quick check asks."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.skill_check import AgentState, CheckOutcome, CheckVerdict
from app.services.improvement_states import CheckResult
from app.services.skill_check_rules import (
    EXPECTED_RERUN_SHARE,
    SampleCandidate,
    StageComparison,
    StageResult,
    agent_state,
    changed_words,
    expected_cost,
    noisy,
    outcomes,
    pooled,
    sample,
    sample_size,
    stage_state,
    total,
    verdict,
)


def _stage(
    *,
    fixed: int = 0,
    broken: int = 0,
    fixed_unconfirmed: int = 0,
    broken_unconfirmed: int = 0,
    candidate: float | None = 0.5,
    baseline: float | None = 0.5,
    incomplete: int = 0,
) -> StageResult:
    return StageResult(
        check=CheckResult(
            comparable=True,
            incomplete=incomplete,
            ungraded=0,
            regressions_confirmed=broken,
            fixed_confirmed=fixed,
            candidate_pass_rate=candidate,
            baseline_pass_rate=baseline,
        ),
        fixed_unconfirmed=fixed_unconfirmed,
        regressions_unconfirmed=broken_unconfirmed,
        compared=10,
    )


class TestStage:
    def test_a_confirmed_regression_is_worse(self) -> None:
        assert stage_state(_stage(fixed=3, broken=1, candidate=0.8)) is AgentState.WORSE

    def test_confirmed_fixes_with_a_pass_rate_that_held_are_better(self) -> None:
        assert stage_state(_stage(fixed=2, candidate=0.7)) is AgentState.BETTER

    def test_nothing_moved_is_no_change(self) -> None:
        assert stage_state(_stage()) is AgentState.NO_CHANGE

    def test_a_better_stage_stays_better_beside_unconfirmed_flips_and_is_noisy(self) -> None:
        """Noise warns and never turns a measured improvement into nothing."""
        stage = _stage(fixed=2, broken_unconfirmed=1, candidate=0.7)

        assert stage_state(stage) is AgentState.BETTER
        assert noisy(stage)

    def test_an_unconfirmed_regression_without_fixes_is_within_noise(self) -> None:
        assert stage_state(_stage(broken_unconfirmed=1)) is AgentState.WITHIN_NOISE

    def test_a_stage_with_nothing_unconfirmed_is_not_noisy(self) -> None:
        assert not noisy(_stage(fixed=2, candidate=0.7))

    def test_unconfirmed_fixes_alone_are_within_noise(self) -> None:
        assert stage_state(_stage(fixed_unconfirmed=2)) is AgentState.WITHIN_NOISE

    def test_a_stage_not_measured_is_unknown(self) -> None:
        assert stage_state(_stage(incomplete=1)) is AgentState.UNKNOWN


def _compared(
    *,
    held_out: int,
    fixed: int = 0,
    broken: int = 0,
    broken_unconfirmed: int = 0,
    candidate: float | None = 0.5,
    baseline: float | None = 0.5,
    comparable: bool = True,
) -> StageComparison:
    return StageComparison(
        comparable=comparable,
        gradable_holdout=held_out,
        incomplete=0,
        ungraded=0,
        crashed=0,
        regressions_confirmed=broken,
        fixed_confirmed=fixed,
        regressions_unconfirmed=broken_unconfirmed,
        fixed_unconfirmed=0,
        compared=held_out,
        candidate_pass_rate=candidate,
        baseline_pass_rate=baseline,
    )


class TestPooled:
    """The held-out minimum is the agent's: its stages are one measurement."""

    def test_a_sample_and_a_skill_set_too_small_alone_make_a_result_together(self) -> None:
        sample = _compared(held_out=4, fixed=1, candidate=0.75, baseline=0.5)
        skill_set = _compared(held_out=2, candidate=0.5, baseline=0.5)

        result = pooled([sample, skill_set], minimum=5)

        assert result.check.comparable and result.compared == 6
        assert result.check.candidate_pass_rate == pytest.approx((0.75 * 4 + 0.5 * 2) / 6)
        assert stage_state(result) is AgentState.BETTER

    def test_too_few_held_out_questions_in_all_is_unknown(self) -> None:
        result = pooled([_compared(held_out=2, broken=1), _compared(held_out=2)], minimum=5)

        assert stage_state(result) is AgentState.UNKNOWN

    def test_a_regression_confirmed_in_one_stage_makes_the_agent_worse(self) -> None:
        result = pooled(
            [_compared(held_out=4, fixed=1, candidate=0.75), _compared(held_out=6, broken=4)],
            minimum=5,
        )

        assert stage_state(result) is AgentState.WORSE
        assert result.check.regressions_confirmed == 4

    def test_a_stage_invalid_for_another_reason_leaves_the_agent_unknown(self) -> None:
        result = pooled(
            [_compared(held_out=10, fixed=2), _compared(held_out=4, comparable=False)],
            minimum=5,
        )

        assert stage_state(result) is AgentState.UNKNOWN

    @pytest.mark.parametrize(
        "unmeasured",
        [
            {"comparable": False},
            {"incomplete": 1},
            {"ungraded": 1},
        ],
    )
    def test_a_regression_one_stage_confirmed_is_not_hidden_by_an_unmeasured_one(
        self, unmeasured: dict[str, int | bool]
    ) -> None:
        """Unknown can be applied once acknowledged and worse cannot, so a regression a
        stage measured completely blocks whatever the stage beside it could not tell."""
        found = _compared(held_out=6, broken=2)
        beside = replace(_compared(held_out=4), **unmeasured)

        assert agent_state([found, beside], minimum=5) is AgentState.WORSE
        assert stage_state(pooled([found, beside], minimum=5)) is AgentState.UNKNOWN

    def test_a_confirmed_regression_blocks_below_the_held_out_minimum(self) -> None:
        """Nobody may get confirmed worse: blocking on few questions errs on the safe side,
        while getting better still needs the minimum."""
        assert agent_state([_compared(held_out=2, broken=1)], minimum=5) is AgentState.WORSE
        assert agent_state([_compared(held_out=2, fixed=1, candidate=1.0)], minimum=5) is (
            AgentState.UNKNOWN
        )

    def test_a_regression_in_a_stage_not_measured_completely_waits_for_the_pool(self) -> None:
        partial = replace(_compared(held_out=6, broken=2), incomplete=1)

        assert agent_state([partial, _compared(held_out=4)], minimum=5) is AgentState.UNKNOWN

    def test_without_a_regression_the_pool_decides(self) -> None:
        assert (
            agent_state(
                [_compared(held_out=3, fixed=1, candidate=0.75), _compared(held_out=3)], minimum=5
            )
            is AgentState.BETTER
        )

    def test_unconfirmed_flips_anywhere_make_the_agent_noisy(self) -> None:
        result = pooled(
            [_compared(held_out=6), _compared(held_out=4, broken_unconfirmed=1)], minimum=5
        )

        assert stage_state(result) is AgentState.WITHIN_NOISE and noisy(result)

    def test_no_stage_or_no_pass_rate_measures_nothing(self) -> None:
        assert stage_state(pooled([], minimum=5)) is AgentState.UNKNOWN
        result = pooled([_compared(held_out=6, fixed=1, baseline=None)], minimum=5)
        assert result.check.baseline_pass_rate is None
        assert stage_state(result) is AgentState.UNKNOWN


class TestVerdict:
    def test_one_agent_worse_blocks_whatever_the_others(self) -> None:
        result = verdict([AgentState.BETTER, AgentState.BETTER, AgentState.WORSE])
        assert result is CheckVerdict.BLOCKED

    def test_no_agent_better_is_no_better(self) -> None:
        result = verdict([AgentState.NO_CHANGE, AgentState.WITHIN_NOISE])
        assert result is CheckVerdict.NO_BETTER

    def test_an_unknown_agent_beside_a_better_one_needs_an_acknowledgement(self) -> None:
        result = verdict([AgentState.BETTER, AgentState.UNKNOWN])
        assert result is CheckVerdict.NEEDS_ACK

    def test_no_agent_measured_needs_an_acknowledgement(self) -> None:
        assert verdict([AgentState.UNKNOWN, AgentState.UNKNOWN]) is CheckVerdict.NEEDS_ACK
        assert verdict([AgentState.NO_CHANGE, AgentState.UNKNOWN]) is CheckVerdict.NO_BETTER

    def test_no_agent_at_all_is_no_better(self) -> None:
        assert verdict([]) is CheckVerdict.NO_BETTER

    def test_within_noise_is_a_warning_not_a_block(self) -> None:
        result = verdict([AgentState.BETTER, AgentState.WITHIN_NOISE])
        assert result is CheckVerdict.PASSED


def test_a_stage_most_likely_costs_its_answers_and_some_of_its_re_asks() -> None:
    """The re-ask ceiling asks every question again; a check pays for the flipped ones."""
    expected = expected_cost(Decimal("1.00"), Decimal("2.00"))

    assert Decimal("1.00") < expected < Decimal("3.00")
    assert expected == Decimal("1.00") + Decimal("2.00") * EXPECTED_RERUN_SHARE


@pytest.mark.parametrize(("skill_set", "size"), [(10, 4), (2, 4), (1, 4), (0, 5)])
def test_a_quick_sample_reaches_the_minimum_beside_the_skill_set(skill_set: int, size: int):
    assert sample_size(skill_set, minimum=5) == size


class TestOutcomes:
    def test_a_blocked_change_to_main_offers_the_four(self) -> None:
        assert outcomes(CheckVerdict.BLOCKED, fork=False) == [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.APPLY_AND_PIN,
            CheckOutcome.FORK_FOR_HELPED,
            CheckOutcome.DISCARD,
        ]

    @pytest.mark.parametrize("result", list(CheckVerdict))
    def test_a_change_to_main_may_be_forked_whatever_its_result(self, result: CheckVerdict):
        assert CheckOutcome.FORK_FOR_HELPED in outcomes(result, fork=False)

    @pytest.mark.parametrize("result", list(CheckVerdict))
    def test_a_change_to_a_fork_is_never_forked_again(self, result: CheckVerdict) -> None:
        assert CheckOutcome.FORK_FOR_HELPED not in outcomes(result, fork=True)

    def test_a_blocked_change_to_a_fork_has_no_pin_and_no_fork(self) -> None:
        assert outcomes(CheckVerdict.BLOCKED, fork=True) == [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.DISCARD,
        ]

    def test_a_change_that_helped_nobody_cannot_be_applied(self) -> None:
        assert outcomes(CheckVerdict.NO_BETTER, fork=False) == [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.FORK_FOR_HELPED,
            CheckOutcome.DISCARD,
        ]

    @pytest.mark.parametrize("result", [CheckVerdict.PASSED, CheckVerdict.NEEDS_ACK])
    def test_a_passing_change_may_be_applied(self, result: CheckVerdict) -> None:
        assert outcomes(result, fork=True)[0] is CheckOutcome.APPLY


class TestSample:
    NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)

    def _case(self, text: str, *, hours_ago: int, case_id: uuid.UUID | None = None):
        return SampleCandidate(
            case_id=case_id or uuid.uuid4(),
            text=text,
            answered_at=self.NOW - timedelta(hours=hours_ago),
        )

    def test_overlap_with_the_changed_lines_beats_the_newest(self) -> None:
        changed = changed_words(
            "Without a receipt, store credit only.",
            "An order number counts as a receipt.",
        )
        rule = [
            self._case(f"I lost my receipt but have order number {n}", hours_ago=10 + n)
            for n in range(4)
        ]
        newer = [
            self._case(f"What are your opening hours on day {n}?", hours_ago=n) for n in range(4)
        ]

        picked = sample([*newer, *rule], changed)

        assert picked == [case.case_id for case in rule]

    def test_a_tie_on_overlap_goes_to_the_newest_then_the_id(self) -> None:
        changed = changed_words("refunds in 30 days", "refunds in 60 days")
        low, high = uuid.UUID(int=1), uuid.UUID(int=2)
        oldest = self._case("Can I get refunds after some days?", hours_ago=9)
        newest = self._case("Are refunds possible after many days?", hours_ago=1)
        tied_high = self._case("Do refunds take days?", hours_ago=5, case_id=high)
        tied_low = self._case("Are refunds quick, in days?", hours_ago=5, case_id=low)

        picked = sample([oldest, tied_high, newest, tied_low], changed, size=3)

        assert picked == [newest.case_id, tied_low.case_id, tied_high.case_id]

    def test_nothing_shared_falls_back_to_the_newest_then_the_id(self) -> None:
        changed = changed_words("## Returns\nRule one.", "## Returns\n\nRule one.")
        assert changed == set()
        cases = [self._case(f"question {n}", hours_ago=n) for n in range(6)]

        picked = sample(cases, changed)

        assert picked == [case.case_id for case in cases[:4]]

    def test_fewer_candidates_than_the_size_are_all_asked(self) -> None:
        only = self._case("anything", hours_ago=1)
        assert sample([only], {"anything"}) == [only.case_id]

    def test_stop_words_never_count_as_overlap(self) -> None:
        assert changed_words("Rule one.\nThe and of it.", "Rule one.") == set()


def test_money_adds_up_without_floats() -> None:
    assert total([Decimal("0.1"), Decimal("0.2")]) == Decimal("0.3")
    assert total([]) == Decimal(0)
