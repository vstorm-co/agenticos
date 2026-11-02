"""The rule a skill change is judged by: one agent's result, the change's, what a
person may do next, and which of an agent's own questions a quick check asks."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.skill_check import AgentState, CheckOutcome, CheckVerdict
from app.services.improvement_states import CheckResult
from app.services.skill_check_rules import (
    SampleCandidate,
    StageResult,
    changed_words,
    combined,
    outcomes,
    sample,
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

    def test_an_unconfirmed_regression_is_within_noise_even_beside_fixes(self) -> None:
        assert stage_state(_stage(fixed=2, broken_unconfirmed=1, candidate=0.7)) is (
            AgentState.WITHIN_NOISE
        )

    def test_unconfirmed_fixes_alone_are_within_noise(self) -> None:
        assert stage_state(_stage(fixed_unconfirmed=2)) is AgentState.WITHIN_NOISE

    def test_a_stage_not_measured_is_unknown(self) -> None:
        assert stage_state(_stage(incomplete=1)) is AgentState.UNKNOWN


class TestCombined:
    @pytest.mark.parametrize(
        ("states", "expected"),
        [
            ([AgentState.BETTER, AgentState.WORSE], AgentState.WORSE),
            ([AgentState.UNKNOWN, AgentState.WORSE], AgentState.WORSE),
            ([AgentState.BETTER, AgentState.UNKNOWN], AgentState.UNKNOWN),
            ([AgentState.BETTER, AgentState.NO_CHANGE], AgentState.BETTER),
            ([AgentState.WITHIN_NOISE, AgentState.BETTER], AgentState.BETTER),
            ([AgentState.WITHIN_NOISE, AgentState.NO_CHANGE], AgentState.WITHIN_NOISE),
            ([AgentState.NO_CHANGE], AgentState.NO_CHANGE),
            ([], AgentState.UNKNOWN),
        ],
    )
    def test_an_agents_result_from_its_stages(
        self, states: list[AgentState], expected: AgentState
    ) -> None:
        assert combined(states) is expected


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

    def test_within_noise_is_a_warning_not_a_block(self) -> None:
        result = verdict([AgentState.BETTER, AgentState.WITHIN_NOISE])
        assert result is CheckVerdict.PASSED


class TestOutcomes:
    def test_a_blocked_change_to_main_offers_the_four(self) -> None:
        assert outcomes(CheckVerdict.BLOCKED, fork=False) == [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.APPLY_AND_PIN,
            CheckOutcome.FORK_FOR_HELPED,
            CheckOutcome.DISCARD,
        ]

    def test_a_blocked_change_to_a_fork_has_no_pin_and_no_fork(self) -> None:
        assert outcomes(CheckVerdict.BLOCKED, fork=True) == [
            CheckOutcome.IMPROVE_FURTHER,
            CheckOutcome.DISCARD,
        ]

    def test_a_change_that_helped_nobody_cannot_be_applied(self) -> None:
        assert CheckOutcome.APPLY not in outcomes(CheckVerdict.NO_BETTER, fork=False)

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
