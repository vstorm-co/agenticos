"""What each scorer concludes about one answer, without a database or a model.

The trajectory tests are the contract the issue states: every order mode, each
with an extra call, a missing one and a reordered pair.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.scoring import (
    CaseScoreRead,
    DatasetScoring,
    JudgeCheck,
    JudgeScorer,
    ReferenceScorer,
    RubricCriterion,
    ScorerResult,
)
from app.services.scorers import (
    MAX_MATCH_TEXT,
    MAX_QUOTE,
    MAX_QUOTES,
    MAX_REASON,
    MAX_RULE,
    CaseView,
    JudgeGrade,
    JudgeVerdict,
    ScoredAnswer,
    ScoredCall,
    case_passed,
    copies,
    graded,
    judge_criteria,
    judge_prompt,
    not_graded,
    restates,
    run_checks,
    score_trajectory,
)


def _answer(text: str = "", **overrides) -> ScoredAnswer:
    return ScoredAnswer(text=text, **overrides)


def _check(check: dict, answer: ScoredAnswer) -> ScorerResult:
    results, judged = run_checks([check], answer, required=True)
    assert judged == []
    [result] = results
    return result


def _case(**overrides) -> CaseView:
    values = {
        "input": "What is the refund window?",
        "history": [],
        "reference_answer": None,
        "counter_example": None,
        "expected_tool_calls": [],
        "order_mode": "any",
        "checks": [],
    }
    return CaseView(**{**values, **overrides})


class TestTextChecks:
    @pytest.mark.parametrize(
        ("check", "status"),
        [
            ({"type": "contains", "value": "thirty DAYS"}, "pass"),
            ({"type": "contains", "value": "thirty DAYS", "case_sensitive": True}, "fail"),
            ({"type": "not_contains", "value": "ninety"}, "pass"),
            ({"type": "not_contains", "value": "thirty"}, "fail"),
            ({"type": "equals", "value": "  Refunds within thirty days. "}, "pass"),
            ({"type": "equals", "value": "Refunds"}, "fail"),
            ({"type": "regex", "value": r"\bthirty\s+days\b"}, "pass"),
            ({"type": "regex", "value": r"^\d+$"}, "fail"),
        ],
    )
    def test_a_rule_on_the_whole_answer(self, check, status) -> None:
        result = _check(check, _answer("Refunds within thirty days."))

        assert result.status == status
        assert result.score == (1.0 if status == "pass" else 0.0)

    @pytest.mark.security
    def test_a_pattern_that_backtracks_without_end_stops_as_an_error(self) -> None:
        started = time.monotonic()

        result = _check({"type": "regex", "value": r"^(a|a)*$"}, _answer("a" * 40 + "b"))

        assert (result.status, result.reason_code) == ("error", "pattern_timeout")
        assert time.monotonic() - started < 2

    def test_a_path_reads_into_a_json_answer(self) -> None:
        answer = _answer('```json\n{"items": [{"name": "Refund"}]}\n```')

        assert (
            _check({"type": "equals", "value": "refund", "path": "items.0.name"}, answer).status
            == "pass"
        )

    def test_a_non_string_value_is_matched_as_json(self) -> None:
        answer = _answer('{"days": 30}')

        assert _check({"type": "equals", "value": "30", "path": "days"}, answer).status == "pass"

    @pytest.mark.parametrize(
        ("text", "path", "reason"),
        [
            ("thirty days", "days", "The answer is not JSON"),
            ('{"days": 30}', "weeks", "The answer has nothing at `weeks`"),
            ('{"items": []}', "items.0", "The answer has nothing at `items.0`"),
        ],
    )
    def test_nothing_where_the_path_looks_fails_the_rule(self, text, path, reason) -> None:
        result = _check({"type": "contains", "value": "x", "path": path}, _answer(text))

        assert result.status == "fail"
        assert result.reason == reason

    def test_only_the_bounded_head_of_an_answer_is_read(self) -> None:
        answer = _answer("a" * MAX_MATCH_TEXT + "needle")

        assert _check({"type": "contains", "value": "needle"}, answer).status == "fail"


class TestSchemaChecks:
    SCHEMA = {
        "type": "object",
        "properties": {"days": {"type": "integer"}},
        "required": ["days"],
    }

    def test_a_matching_answer_passes(self) -> None:
        result = _check({"type": "json_schema", "schema": self.SCHEMA}, _answer('{"days": 30}'))

        assert result.status == "pass"

    def test_a_mismatch_says_where(self) -> None:
        result = _check({"type": "json_schema", "schema": self.SCHEMA}, _answer('{"days": "30"}'))

        assert result.status == "fail"
        assert result.reason.startswith("days:")

    def test_prose_is_not_json(self) -> None:
        result = _check({"type": "json_schema", "schema": self.SCHEMA}, _answer("30 days"))

        assert result.status == "fail"
        assert result.reason == "The answer is not JSON"

    def test_a_schema_applies_at_a_path(self) -> None:
        check = {"type": "json_schema", "schema": {"type": "integer"}, "path": "days"}

        assert _check(check, _answer('{"days": 30}')).status == "pass"

    def test_a_reference_to_a_part_the_schema_lacks_is_an_error(self) -> None:
        check = {"type": "json_schema", "schema": {"$ref": "#/$defs/missing"}}

        result = _check(check, _answer("{}"))

        assert (result.status, result.reason_code) == ("error", "schema_unresolvable")


class TestCeilings:
    def test_a_cost_under_the_ceiling_passes(self) -> None:
        result = _check({"type": "max_cost_usd", "value": 0.05}, _answer(cost_usd=Decimal("0.012")))

        assert result.status == "pass"
        assert result.reason == "Took $0.0120"

    def test_a_latency_over_the_ceiling_fails(self) -> None:
        result = _check({"type": "max_latency_ms", "value": 1000}, _answer(latency_ms=2500))

        assert result.status == "fail"
        assert result.reason == "Took 2500 ms"

    def test_an_unmeasured_run_is_an_error_not_a_pass(self) -> None:
        result = _check({"type": "max_latency_ms", "value": 1000}, _answer())

        assert result.status == "error"
        assert result.reason_code == "not_measured"


class TestStoredChecks:
    def test_a_check_this_build_cannot_read_is_an_error_and_the_rest_still_score(self) -> None:
        results, _ = run_checks(
            [{"type": "sentiment", "value": "warm"}, {"type": "contains", "value": "days"}],
            _answer("thirty days"),
            required=True,
        )

        assert [(r.status, r.reason_code) for r in results] == [
            ("error", "unknown_check"),
            ("pass", None),
        ]

    def test_judge_criteria_are_handed_back_for_the_judge(self) -> None:
        results, judged = run_checks(
            [{"type": "judge", "criterion": "Refuses politely"}], _answer(), required=True
        )

        assert results == []
        assert judged == [JudgeCheck(type="judge", criterion="Refuses politely")]


SEARCH = {"tool": "search_kb", "args": {"query": "refunds"}}
LOOKUP = {"tool": "lookup_order", "args": {}}
EMAIL = {"tool": "send_email", "args": {}}


def _calls(*specs: tuple[str, dict]) -> list[ScoredCall]:
    return [ScoredCall(tool=tool, args=args) for tool, args in specs]


class TestTrajectory:
    def test_nothing_expected_is_nothing_to_score(self) -> None:
        assert (
            score_trajectory([], _calls(("search_kb", {})), order_mode="exact", required=True)
            is None
        )

    @pytest.mark.parametrize("mode", ["any", "in_order", "exact"])
    def test_the_expected_calls_in_order_pass_every_mode(self, mode) -> None:
        calls = _calls(("search_kb", {"query": "refunds", "limit": 5}), ("lookup_order", {"id": 7}))

        result = score_trajectory([SEARCH, LOOKUP], calls, order_mode=mode, required=True)

        assert result is not None
        assert result.status == "pass"
        assert result.score == 1.0

    @pytest.mark.parametrize("mode", ["any", "in_order", "exact"])
    def test_a_missing_call_fails_every_mode(self, mode) -> None:
        result = score_trajectory(
            [SEARCH, LOOKUP],
            _calls(("search_kb", {"query": "refunds"})),
            order_mode=mode,
            required=True,
        )

        assert result is not None
        assert result.status == "fail"
        assert result.score == 0.5
        assert "Missing: lookup_order" in result.reason

    def test_an_argument_that_differs_is_a_missing_call(self) -> None:
        result = score_trajectory(
            [SEARCH], _calls(("search_kb", {"query": "shipping"})), order_mode="any", required=True
        )

        assert result is not None
        assert result.status == "fail"

    @pytest.mark.parametrize(
        ("mode", "status"), [("any", "pass"), ("in_order", "pass"), ("exact", "fail")]
    )
    def test_an_extra_call_fails_only_exact(self, mode, status) -> None:
        calls = _calls(
            ("search_kb", {"query": "refunds"}), ("send_email", {}), ("lookup_order", {})
        )

        result = score_trajectory([SEARCH, LOOKUP], calls, order_mode=mode, required=True)

        assert result is not None
        assert result.status == status
        if status == "fail":
            assert "Not expected: send_email" in result.reason

    @pytest.mark.parametrize(
        ("mode", "status"), [("any", "pass"), ("in_order", "fail"), ("exact", "fail")]
    )
    def test_a_reordered_pair_fails_the_ordered_modes(self, mode, status) -> None:
        calls = _calls(("lookup_order", {}), ("search_kb", {"query": "refunds"}))

        result = score_trajectory([SEARCH, LOOKUP], calls, order_mode=mode, required=True)

        assert result is not None
        assert result.status == status
        if status == "fail":
            assert result.reason == "Called in a different order"

    def test_a_general_expectation_does_not_take_the_call_a_specific_one_needs(self) -> None:
        """Matched as a whole, not first-come: `search_kb` with no arguments must
        leave the `refunds` search to the expectation that names it."""
        calls = _calls(("search_kb", {"query": "refunds"}), ("search_kb", {"query": "shipping"}))

        result = score_trajectory(
            [{"tool": "search_kb", "args": {}}, SEARCH], calls, order_mode="any", required=True
        )

        assert result is not None
        assert result.status == "pass"

    def test_two_identical_expectations_need_two_calls(self) -> None:
        result = score_trajectory(
            [SEARCH, SEARCH],
            _calls(("search_kb", {"query": "refunds"})),
            order_mode="any",
            required=True,
        )

        assert result is not None
        assert result.status == "fail"
        assert result.score == 0.5

    def test_a_blocked_write_counts_as_a_call_the_agent_made(self) -> None:
        calls = [
            ScoredCall(tool="search_kb", args={"query": "refunds"}),
            ScoredCall(tool="send_email", args={"to": "a@example.com"}, blocked=True),
        ]

        result = score_trajectory([SEARCH, EMAIL], calls, order_mode="exact", required=True)

        assert result is not None
        assert result.status == "pass"
        assert "send_email blocked, not executed" in result.reason


def _result(status: str, *, required: bool = True) -> ScorerResult:
    return ScorerResult(scorer="check", name="x", required=required, status=status, reason="")


class TestCasePassed:
    def test_every_required_scorer_passing_passes(self) -> None:
        assert case_passed([_result("pass"), _result("fail", required=False)]) is True

    def test_one_required_failure_fails_whatever_else_reached_no_verdict(self) -> None:
        assert (
            case_passed([_result("pass"), _result("error"), _result("fail"), _result("skipped")])
            is False
        )

    @pytest.mark.parametrize("status", ["skipped", "error"])
    def test_a_required_scorer_without_a_verdict_leaves_the_case_unscored(self, status) -> None:
        """A judge that errored checked nothing, so the case is neither passed nor failed."""
        assert case_passed([_result("pass"), _result(status)]) is None

    def test_an_optional_error_does_not_hold_the_case(self) -> None:
        assert case_passed([_result("pass"), _result("error", required=False)]) is True

    def test_nothing_required_leaves_the_case_unscored(self) -> None:
        assert case_passed([_result("pass", required=False)]) is None

    def test_an_unscored_score_names_the_first_required_scorer_without_a_verdict(self) -> None:
        def read(results: list[ScorerResult], passed: bool | None) -> CaseScoreRead:
            return CaseScoreRead(
                id=uuid.uuid4(),
                dataset_id=uuid.uuid4(),
                case_id=uuid.uuid4(),
                case_revision_id=uuid.uuid4(),
                question="q",
                results=results,
                passed=passed,
                review_state="none",
                created_at=datetime.now(UTC),
            )

        budget = _result("skipped").model_copy(update={"reason_code": "judge_budget"})
        optional = _result("error", required=False).model_copy(update={"reason_code": "x"})

        assert read([optional, budget, _result("error")], None).unscored_reason == "judge_budget"
        assert read([_result("error")], None).unscored_reason == "error"
        assert read([_result("pass", required=False)], None).unscored_reason is None
        assert read([_result("fail"), budget], False).unscored_reason is None


class TestJudgeCriteria:
    def _scoring(self, **overrides) -> DatasetScoring:
        return DatasetScoring(
            judge=JudgeScorer(
                enabled=True,
                criteria=[
                    RubricCriterion(name="correctness", description="Facts are right"),
                    RubricCriterion(name="tone", description="Polite", required=False),
                ],
            ),
            **overrides,
        )

    def test_the_rubric_the_reference_and_the_case_s_own(self) -> None:
        scoring = self._scoring(reference=ReferenceScorer(enabled=True))
        case = _case(reference_answer="Thirty days.")

        criteria = judge_criteria(
            case, scoring, [JudgeCheck(type="judge", criterion="Cites policy")]
        )

        assert [(c.id, c.scorer, c.name, c.required) for c in criteria] == [
            ("r1", "judge", "correctness", True),
            ("r2", "judge", "tone", False),
            ("ref", "reference", "reference answer", True),
            ("c1", "judge", "Cites policy", True),
        ]

    def test_a_disabled_judge_and_a_case_without_a_reference_ask_nothing(self) -> None:
        scoring = DatasetScoring(reference=ReferenceScorer(enabled=True))

        assert judge_criteria(_case(), scoring, []) == []

    def test_the_prompt_carries_the_case_and_every_criterion_id(self) -> None:
        scoring = self._scoring(reference=ReferenceScorer(enabled=True))
        case = _case(
            history=[{"role": "user", "content": "Hi"}],
            reference_answer="Thirty days.",
            counter_example="Ninety days.",
        )
        criteria = judge_criteria(case, scoring, [])

        prompt = judge_prompt(case, _answer("30 days"), criteria, scale_max=5)

        for part in (
            "<conversation_so_far>\nuser: Hi",
            "<question>\nWhat is the refund window?",
            "<reference_answer>\nThirty days.",
            "<counter_example>\nNinety days.",
            "<answer>\n30 days",
            "from 1 (does not meet it at all) to 5",
            "- r1 (correctness): Facts are right",
            "- ref (reference answer):",
            "For counter, quote what sets the answer apart from the counter-example",
        ):
            assert part in prompt

    def test_a_case_without_a_counter_example_is_not_told_how_to_quote_one(self) -> None:
        criteria = judge_criteria(_case(), self._scoring(), [])

        prompt = judge_prompt(_case(), _answer("30 days"), criteria, scale_max=5)

        assert "For counter" not in prompt

    def test_the_prompt_says_why_the_case_exists_and_what_the_agent_called(self) -> None:
        case = _case(note="Customers keep getting the old 90-day window")
        criteria = judge_criteria(case, self._scoring(), [])
        answer = _answer(
            "30 days",
            calls=(
                ScoredCall(tool="search_kb", args={"query": "refund"}),
                ScoredCall(tool="send_email", args={"to": "a@b.c"}, blocked=True),
            ),
        )

        prompt = judge_prompt(case, answer, criteria, scale_max=5)

        assert "<why_this_case_exists>\nCustomers keep getting the old 90-day window\n" in prompt
        assert '1. search_kb {"query": "refund"} (ran)' in prompt
        assert '2. send_email {"to": "a@b.c"} (blocked before it ran)' in prompt
        assert prompt.index("<why_this_case_exists>") < prompt.index("<question>")

    def test_a_prompt_with_no_calls_says_so_and_a_long_trajectory_is_cut(self) -> None:
        criteria = judge_criteria(_case(), self._scoring(), [])

        quiet = judge_prompt(_case(), _answer(), criteria, scale_max=5)
        busy = judge_prompt(
            _case(),
            _answer(calls=tuple(ScoredCall(tool="t", args={"q": "x" * 2000}) for _ in range(52))),
            criteria,
            scale_max=5,
        )

        assert "The agent called no tools." in quiet
        assert "<why_this_case_exists>" not in quiet
        assert "50. t " in busy
        assert "51. t" not in busy
        assert "… and 2 more" in busy
        assert f'{{"q": "{"x" * 993}…' in busy

    def test_a_counter_example_is_a_required_criterion_once_the_judge_grades(self) -> None:
        case = _case(counter_example="Ninety days.")
        rubric_off = DatasetScoring(
            judge=JudgeScorer(enabled=False), reference=ReferenceScorer(enabled=True)
        )

        for scoring in (self._scoring(), rubric_off):
            counter = judge_criteria(case, scoring, [])[-1]
            assert (counter.id, counter.scorer, counter.name, counter.required) == (
                "counter",
                "reference",
                "counter-example",
                True,
            )
        assert judge_criteria(case, DatasetScoring(), []) == []
        assert "<reference_answer>" not in judge_prompt(
            case, _answer(), judge_criteria(case, rubric_off, []), scale_max=5
        )

    def test_the_reference_is_withheld_when_it_is_not_a_criterion(self) -> None:
        case = _case(reference_answer="Thirty days.")
        criteria = judge_criteria(case, self._scoring(), [])

        assert "<reference_answer>" not in judge_prompt(case, _answer(), criteria, scale_max=5)


class TestGrades:
    def test_grades_at_and_above_the_mark_pass(self) -> None:
        run_id = uuid.uuid4()
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])
        verdict = JudgeVerdict(
            grades=[
                JudgeGrade(id="r1", score=4, reason="Right date"),
                JudgeGrade(id="r2", score=2, reason="Curt"),
            ]
        )

        results = graded(criteria, verdict, answer="", scale_max=5, pass_at=4, run_id=run_id)

        assert [(r.name, r.status, r.score, r.reason) for r in results] == [
            ("correctness", "pass", 0.8, "4/5: Right date"),
            ("tone", "fail", 0.4, "2/5: Curt"),
        ]
        assert {r.judge_run_id for r in results} == {run_id}

    @pytest.mark.parametrize("grades", [[], [JudgeGrade(id="r1", score=9, reason="")]])
    def test_a_criterion_left_ungraded_or_off_the_scale_is_an_error(self, grades) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])[:1]

        [result] = graded(
            criteria,
            JudgeVerdict(grades=grades),
            answer="",
            scale_max=5,
            pass_at=4,
            run_id=uuid.uuid4(),
        )

        assert result.status == "error"
        assert result.reason_code == "judge_ungraded"

    @pytest.mark.parametrize(
        "reason",
        [
            "Facts are right",
            "facts are RIGHT.",
            "The answer agrees with the reference answer on every fact",
            "Yes: The answer agrees with the reference answer on every fact the question "
            "turns on. Wording may differ; a missing or contradicted fact does not.",
        ],
    )
    def test_a_reason_that_restates_the_criterion_is_an_error(self, reason) -> None:
        scoring = TestJudgeCriteria()._scoring(reference=ReferenceScorer(enabled=True))
        criteria = judge_criteria(_case(reference_answer="30"), scoring, [])
        verdict = JudgeVerdict(
            grades=[
                JudgeGrade(id="r1", score=5, reason=reason),
                JudgeGrade(id="r2", score=5, reason="Thanks the customer by name"),
                JudgeGrade(id="ref", score=5, reason=reason),
            ]
        )

        results = graded(criteria, verdict, answer="", scale_max=5, pass_at=4, run_id=uuid.uuid4())

        echoed = [r for r in results if r.status == "error"]
        assert echoed
        assert {r.reason_code for r in echoed} == {"judge_reason_echo"}
        assert results[1].status == "pass"

    def test_a_criterion_copied_with_one_word_swapped_is_still_restated(self) -> None:
        criterion = (
            "The decision (approve, deny or need more info) follows the store's refund policy, "
            "and the answer never promises a refund the policy does not allow."
        )
        copied = (
            "The decision (deny) follows the store's refund policy, and the answer never "
            "promises a refund the policy does not allow."
        )

        assert restates(copied, criterion)
        assert restates("The decision follows the store's refund policy.", criterion)

    @pytest.mark.parametrize(
        ("reason", "criterion"),
        [
            ("The answer is polite", "Polite"),
            ("Says 30 days, which the reference also gives", "Facts are right"),
            ("It is ok", "Facts are right"),
        ],
    )
    def test_a_reason_of_its_own_is_not_restated(self, reason, criterion) -> None:
        assert not restates(reason, criterion)

    def test_a_quote_the_answer_holds_saves_a_reason_close_to_the_criterion(self) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])[:1]
        verdict = JudgeVerdict(
            grades=[
                JudgeGrade(
                    id="r1",
                    score=5,
                    reason="Facts are right",
                    rule="Refunds within 30 days",
                    quotes=["within 30 days"],
                )
            ]
        )

        [result] = graded(
            criteria,
            verdict,
            answer="You can return it within 30 days.",
            scale_max=5,
            pass_at=4,
            run_id=uuid.uuid4(),
        )

        assert (result.status, result.rule, result.unverified) == (
            "pass",
            "Refunds within 30 days",
            False,
        )

    def test_passing_on_the_counter_example_needs_a_quote_it_does_not_also_say(self) -> None:
        case = _case(counter_example="You have 90 days to return it.")
        scoring = DatasetScoring(reference=ReferenceScorer(enabled=True))
        criteria = judge_criteria(case, scoring, [])
        answer = "You have 30 days to return it, receipt or not."

        def grade(**given) -> ScorerResult:
            [result] = graded(
                criteria,
                JudgeVerdict(grades=[JudgeGrade(id="counter", reason="Differs", **given)]),
                answer=answer,
                scale_max=5,
                pass_at=4,
                run_id=uuid.uuid4(),
                counter_example=case.counter_example,
            )
            return result

        echoed = grade(score=5, quotes=["days to return it"])
        backed = grade(score=4, quotes=["30 days"])
        failed = grade(score=1, quotes=["days to return it"])

        assert (echoed.status, echoed.reason_code, echoed.judge_said) == (
            "error",
            "judge_counter_unsupported",
            "Differs",
        )
        assert (backed.status, backed.unverified) == ("pass", False)
        assert failed.status == "fail"

    def test_a_pass_on_the_counter_example_with_nothing_quoted_stands_unverified(self) -> None:
        """Judges grade an answer that plainly refuses what the bad answer did as
        unlike it and quote nothing; the answer is still graded."""
        case = _case(counter_example="Sure, I have refunded your gift code.")
        criteria = judge_criteria(case, DatasetScoring(reference=ReferenceScorer(enabled=True)), [])
        verdict = JudgeVerdict(
            grades=[
                JudgeGrade(
                    id="counter",
                    score=4,
                    reason="It refuses the refund the counter-example grants",
                    quotes=[],
                )
            ]
        )

        [result] = graded(
            criteria,
            verdict,
            answer="Gift codes are never refundable once redeemed. I cannot process a refund.",
            scale_max=5,
            pass_at=4,
            run_id=uuid.uuid4(),
            counter_example=case.counter_example,
        )

        assert (result.status, result.reason_code, result.unverified) == ("pass", None, True)

    @pytest.mark.parametrize(
        ("answer", "quotes"),
        [
            ("sure - I've refunded your gift code!", []),
            ("Sure - I've refunded your gift code.", ["Sure - I've"]),
            ("Sure, I\u2019ve refunded your gift code.", ["I\u2019ve refunded your gift code"]),
            ("Sure, I\u2019ve refunded your gift code. Bye!", ["Bye!"]),
        ],
    )
    def test_a_copy_of_the_counter_example_cannot_pass_whatever_is_quoted(
        self, answer, quotes
    ) -> None:
        case = _case(counter_example="Sure, I've refunded your gift code.")
        criteria = judge_criteria(case, DatasetScoring(reference=ReferenceScorer(enabled=True)), [])
        verdict = JudgeVerdict(
            grades=[JudgeGrade(id="counter", score=5, reason="Fine", quotes=quotes)]
        )

        [result] = graded(
            criteria,
            verdict,
            answer=answer,
            scale_max=5,
            pass_at=4,
            run_id=uuid.uuid4(),
            counter_example=case.counter_example,
        )

        assert (result.status, result.reason_code) == ("error", "judge_counter_unsupported")

    def test_a_shared_passage_quoted_in_other_punctuation_is_still_shared(self) -> None:
        case = _case(counter_example="You have 30 days to return it.")
        criteria = judge_criteria(case, DatasetScoring(reference=ReferenceScorer(enabled=True)), [])
        verdict = JudgeVerdict(
            grades=[JudgeGrade(id="counter", score=5, reason="Differs", quotes=["30 days - to"])]
        )

        [result] = graded(
            criteria,
            verdict,
            answer="Within 30 days - to be exact - you may return it, receipt or not.",
            scale_max=5,
            pass_at=4,
            run_id=uuid.uuid4(),
            counter_example=case.counter_example,
        )

        assert (result.status, result.reason_code) == ("error", "judge_counter_unsupported")

    @pytest.mark.parametrize(
        ("answer", "copied"),
        [
            ("Sure, I have refunded your gift code.", True),
            ("Hello! Sure, I have refunded your gift code. Anything else?", True),
            ("I have refunded", True),
            ("Your gift code.", True),
            ("Gift code.", False),
            ("I have not refunded your gift code.", False),
            ("Your gift code I have refunded, sure.", False),
            ("...", False),
        ],
    )
    def test_only_the_counter_examples_own_words_in_order_are_a_copy(self, answer, copied) -> None:
        assert copies(answer, "Sure, I have refunded your gift code.") is copied

    def test_a_restated_reason_keeps_what_the_judge_wrote(self) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])[:1]

        [result] = graded(
            criteria,
            JudgeVerdict(grades=[JudgeGrade(id="r1", score=2, reason="Facts are not right")]),
            answer="",
            scale_max=5,
            pass_at=4,
            run_id=uuid.uuid4(),
        )

        assert (result.status, result.reason_code, result.judge_said) == (
            "error",
            "judge_reason_echo",
            "Facts are not right",
        )

    def test_a_top_grade_with_nothing_quoted_from_the_answer_is_unverified(self) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])
        verdict = JudgeVerdict(
            grades=[
                JudgeGrade(id="r1", score=5, reason="Gives the date", quotes=["not there"]),
                JudgeGrade(id="r2", score=4, reason="Courteous"),
            ]
        )

        top, lower = graded(
            criteria, verdict, answer="30 days.", scale_max=5, pass_at=4, run_id=uuid.uuid4()
        )

        assert (top.status, top.unverified, top.rule) == ("pass", True, None)
        assert (lower.status, lower.unverified) == ("pass", False)

    def test_a_quote_not_in_the_answer_is_flagged_and_the_grade_stands(self) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])
        verdict = JudgeVerdict(
            grades=[
                JudgeGrade(id="r1", score=4, reason="Right", quotes=["within 30 days"]),
                JudgeGrade(id="r2", score=5, reason="Warm", quotes=["Happy to help", "x" * 200]),
            ]
        )

        results = graded(
            criteria,
            verdict,
            answer="You can return it within 30 days.",
            scale_max=5,
            pass_at=4,
            run_id=uuid.uuid4(),
        )

        assert [(r.status, r.reason, r.unverified_quotes) for r in results] == [
            ("pass", "4/5: Right", []),
            ("pass", "5/5: Warm", ["Happy to help", f"{'x' * 80}…"]),
        ]

    def test_an_unverified_quote_stays_out_of_a_reason_at_the_length_limit(self) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])[:1]
        verdict = JudgeVerdict(
            grades=[JudgeGrade(id="r1", score=4, reason="r" * 3000, quotes=["absent"])]
        )

        [result] = graded(criteria, verdict, answer="", scale_max=5, pass_at=4, run_id=uuid.uuid4())

        assert len(result.reason) == MAX_REASON
        assert set(result.reason[5:]) == {"r"}
        assert (result.unverified_quotes, result.status) == (["absent"], "pass")

    def test_a_grade_overrunning_what_backs_it_stands_with_the_overrun_cut(self) -> None:
        quotes = ["", "   ", "q" * (MAX_QUOTE + 1), 7, *[f"passage {n}" for n in range(15)]]

        [grade] = JudgeVerdict.model_validate(
            {
                "grades": [
                    {"id": "r1", "score": 4, "reason": "r", "rule": "x" * 500, "quotes": quotes}
                ]
            }
        ).grades

        assert grade.score == 4
        assert grade.rule == "x" * MAX_RULE
        assert grade.quotes == [f"passage {n}" for n in range(MAX_QUOTES)]

    @pytest.mark.parametrize(("quotes", "kept"), [("one passage", ["one passage"]), (None, [])])
    def test_quotes_not_given_as_a_list_are_read_as_well_as_they_can_be(self, quotes, kept) -> None:
        [grade] = JudgeVerdict.model_validate(
            {"grades": [{"id": "r1", "score": 4, "reason": "r", "rule": 3, "quotes": quotes}]}
        ).grades

        assert (grade.quotes, grade.rule) == (kept, "")

    @pytest.mark.parametrize("grade", [{"score": 4, "reason": "r"}, {"id": "r1", "reason": "r"}])
    def test_a_grade_without_its_criterion_or_its_score_is_not_a_verdict(self, grade) -> None:
        with pytest.raises(ValidationError):
            JudgeVerdict.model_validate({"grades": [grade]})

    def test_not_graded_keeps_what_an_unreadable_judge_said(self) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])[:1]

        [result] = not_graded(
            criteria, skipped=False, code="judge_output_invalid", reason="x", said="It is fine."
        )

        assert (result.status, result.judge_said) == ("error", "It is fine.")

    def test_not_graded_says_why_on_every_criterion(self) -> None:
        criteria = judge_criteria(_case(), TestJudgeCriteria()._scoring(), [])

        results = not_graded(criteria, skipped=True, code="ai_assistance_off", reason="Off")

        assert [(r.status, r.reason_code, r.reason) for r in results] == [
            ("skipped", "ai_assistance_off", "Off"),
            ("skipped", "ai_assistance_off", "Off"),
        ]
