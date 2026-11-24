"""The Architect reads an attempt judged on criteria in the same plain words as the wizard."""

from typing import Any

from app.services.platform_mcp._tools import _attempt, _attempt_sentence, _keep_actions

_PRICE_BREAK = {
    "scorer": "judge",
    "name": "price break",
    "graded": 40,
    "before": 9,
    "after": 40,
    "fixed": 31,
    "broken": 0,
}
_VALIDITY = {
    "scorer": "judge",
    "name": "validity",
    "graded": 40,
    "before": 0,
    "after": 0,
    "fixed": 0,
    "broken": 0,
    "skill": "Quote rules",
}
_LENGTH = {
    "scorer": "check",
    "name": "under 200 words",
    "graded": 40,
    "before": 40,
    "after": 30,
    "fixed": 0,
    "broken": 10,
}


def _attempt_row(number: int, verdict: str, *criteria: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"it-{number}",
        "number": number,
        "verdict": verdict,
        "verdict_detail": {"fixed": 0, "broken": 0, "criteria": list(criteria)},
    }


def test_an_attempt_better_on_criteria_says_what_moved_and_what_still_fails():
    sentence = _attempt_sentence(_attempt_row(1, "criteria_better", _PRICE_BREAK, _VALIDITY))

    assert sentence == (
        "Attempt 1 makes the agent better on some criteria, though no whole question flipped. "
        "Criteria that got better: price break 9/40 → 40/40. No additional question passes yet: other "
        'criteria still fail - validity 0/40 → 0/40 (skill "Quote rules").'
    )


def test_an_attempt_worse_on_criteria_is_a_warning_that_names_the_criterion():
    sentence = _attempt_sentence(_attempt_row(2, "criteria_worse", _PRICE_BREAK, _LENGTH))

    assert sentence == (
        "Warning: attempt 2 makes the agent worse on some criteria, though no question broke. "
        "Criteria that got worse: under 200 words 40/40 → 30/40."
    )


def test_a_better_attempt_still_names_a_criterion_that_got_worse():
    sentence = _attempt_sentence(_attempt_row(3, "better", _LENGTH))

    assert sentence.endswith("Criteria that got worse: under 200 words 40/40 → 30/40.")


def test_an_attempt_lists_its_criteria_in_plain_numbers():
    row = {**_attempt_row(1, "criteria_better", _VALIDITY), "cost_usd": "0.10"}

    assert _attempt(row, None)["criteria"] == [
        {
            "scorer": "judge",
            "name": "validity",
            "passed_before": 0,
            "passed_after": 0,
            "graded": 40,
            "fixed": 0,
            "broken": 0,
            "skill": "Quote rules",
        }
    ]


def test_keeping_an_attempt_better_on_criteria_is_not_keeping_it_anyway():
    session = {
        "status": "stopped",
        "max_iterations": 3,
        "best_iteration_id": None,
        "iterations": [
            _attempt_row(1, "criteria_better", _PRICE_BREAK),
            _attempt_row(2, "no_change"),
        ],
    }

    assert _keep_actions(session) == ["Keep attempt 1", "Keep attempt 2 anyway"]


def test_an_attempt_that_left_nothing_failing_says_no_more_than_what_moved():
    sentence = _attempt_sentence(_attempt_row(1, "criteria_better", _PRICE_BREAK))

    assert sentence.endswith("Criteria that got better: price break 9/40 → 40/40.")


def test_a_chosen_criterion_gain_is_also_a_best_attempt():
    row = _attempt_row(1, "criteria_better", _PRICE_BREAK)
    assert _attempt(row, "it-1")["chosen"] is True
    assert _attempt(row, "it-1")["best"] is True
    assert _attempt(_attempt_row(2, "criteria_worse", _LENGTH), "it-1")["best"] is False


def test_a_net_pass_decline_is_not_described_as_a_criterion_gain():
    declined = {**_PRICE_BREAK, "name": "net decline", "before": 30, "after": 20, "fixed": 1}
    sentence = _attempt_sentence(_attempt_row(1, "criteria_better", _PRICE_BREAK, declined))
    assert "Criteria that got better: price break" in sentence
    assert "net decline" not in sentence.split("Criteria that got better:")[1].split(".")[0]


def test_equal_criterion_names_keep_the_scorer_across_opposite_movements():
    gained = {**_PRICE_BREAK, "name": "Validity"}
    lost = {**_LENGTH, "name": "Validity"}

    sentence = _attempt_sentence(_attempt_row(1, "criteria_better", gained, lost))

    assert "Criteria that got worse: Validity [check] 40/40 → 30/40." in sentence
    assert "Criteria that got better: Validity [judge] 9/40 → 40/40." in sentence


def test_equal_criterion_names_are_qualified_even_in_separate_result_sentences():
    gained = {**_PRICE_BREAK, "name": "Validity"}
    failing = {**_VALIDITY, "scorer": "check", "name": "Validity"}

    sentence = _attempt_sentence(_attempt_row(1, "criteria_better", gained, failing))

    assert "Criteria that got better: Validity [judge] 9/40 → 40/40." in sentence
    assert 'criteria still fail - Validity [check] 0/40 → 0/40 (skill "Quote rules").' in sentence
