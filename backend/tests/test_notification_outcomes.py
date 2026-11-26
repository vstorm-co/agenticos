"""Finished sessions, tests and question writing are worded without internal codes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.db.models.improvement import CriterionDetail
from app.db.models.notification import Notification
from app.schemas.notification import MovedCriterion, NotificationRead
from app.services.notifications import _improvement_summary, moved_criteria


@pytest.mark.parametrize(
    ("status", "reason", "summary"),
    [
        ("ready", None, "Your improvement of Refund desk is ready to review."),
        (
            "stopped",
            "no_change",
            "Your improvement of Refund desk finished an attempt: "
            "no change made a measurable difference.",
        ),
        (
            "stale",
            "expired",
            "Your improvement of Refund desk stopped: nobody took the next step for seven days.",
        ),
        (
            "waiting",
            "filtering",
            "Your improvement of Refund desk has changes ready. "
            "Look them over, then take the next step to check them.",
        ),
        (
            "failed",
            "eval",
            "Your improvement of Refund desk could not finish: testing the changes failed.",
        ),
        ("stopped", None, "Your improvement of Refund desk stopped."),
        ("failed", "something_new", "Your improvement of Refund desk could not finish."),
        (
            "ready",
            "knowledge_check",
            "The knowledge document check in your improvement of Refund desk finished.",
        ),
        (
            "stopped",
            "attribution_check",
            "Testing each change in your improvement of Refund desk finished.",
        ),
        (
            "published",
            None,
            "The changes from your improvement of Refund desk were published.",
        ),
        (
            "cancelled",
            None,
            "Your improvement of Refund desk was stopped by an administrator.",
        ),
        (
            "stale",
            "stale",
            "Your improvement of Refund desk stopped: the agent or its test questions changed.",
        ),
    ],
)
def test_a_finished_improvement_reads_as_a_sentence(status, reason, summary):
    assert _improvement_summary("Refund desk", status, reason) == summary


def test_a_stop_whose_next_step_is_blocked_says_what_to_do_instead():
    from app.schemas.improvement import NextStepBlocked

    blocked = NextStepBlocked(reason="missing_holdout", needed=2)
    assert _improvement_summary("Refund desk", "waiting", "filtering", blocked=blocked) == (
        "Your improvement of Refund desk has changes, but too few test questions are left to "
        "check them: 2 more are needed, and this session's questions are fixed. End it, add "
        "questions and start a new one."
    )


def _row(event_type: str, context: dict[str, object] | None) -> Notification:
    return Notification(
        id=uuid4(),
        event_type=event_type,
        summary="Your test finished.",
        context_url=None,
        render_context=context,
        read_at=None,
        created_at=datetime.now(UTC),
    )


def test_an_outcome_is_served_only_for_finished_work_with_a_status():
    read = NotificationRead.from_row(
        _row("improvement_finished", {"status": "stopped", "reason": "budget"}),
        strip_context_url=False,
    )
    assert read.outcome is not None
    assert (read.outcome.status, read.outcome.reason) == ("stopped", "budget")
    test = NotificationRead.from_row(
        _row("eval_run_finished", {"status": "completed", "reason": 3}), strip_context_url=False
    )
    assert test.outcome is not None and test.outcome.reason is None
    assert test.outcome.next_step_blocked is None
    blocked = NotificationRead.from_row(
        _row(
            "improvement_finished",
            {
                "status": "waiting",
                "reason": "filtering",
                "next_step_blocked": {"reason": "missing_holdout", "needed": 2},
            },
        ),
        strip_context_url=False,
    ).outcome
    assert blocked is not None and blocked.next_step_blocked is not None
    assert blocked.next_step_blocked.needed == 2
    for event_type, context in [
        ("case_generation_finished", {}),
        ("case_generation_finished", None),
        ("approval_requested", {"status": "pending"}),
    ]:
        assert (
            NotificationRead.from_row(_row(event_type, context), strip_context_url=False).outcome
            is None
        )


_PRICE_BREAK: CriterionDetail = {
    "scorer": "judge",
    "name": "price break",
    "graded": 40,
    "before": 9,
    "after": 40,
    "fixed": 31,
    "broken": 0,
}
_LENGTH: CriterionDetail = {
    "scorer": "check",
    "name": "under 200 words",
    "graded": 40,
    "before": 40,
    "after": 30,
    "fixed": 0,
    "broken": 10,
}
_VALIDITY: CriterionDetail = {
    "scorer": "judge",
    "name": "validity",
    "graded": 40,
    "before": 0,
    "after": 0,
    "fixed": 0,
    "broken": 0,
}


def test_an_attempt_better_on_criteria_names_them_instead_of_saying_no_change():
    moved = moved_criteria("criteria_better", [_VALIDITY, _PRICE_BREAK])

    assert moved == [
        {
            "scorer": "judge",
            "name": "price break",
            "graded": 40,
            "before": 9,
            "after": 40,
            "direction": "better",
        }
    ]
    assert _improvement_summary("Quote Builder", "ready", None, criteria=moved) == (
        "Your improvement of Quote Builder is ready to review. The selected attempt is better "
        "on price break 9/40 → 40/40; no whole question flipped."
    )


def test_a_criterion_that_got_worse_is_named_first():
    moved = moved_criteria("criteria_worse", [_PRICE_BREAK, _LENGTH])

    assert [item["direction"] for item in moved] == ["worse", "better"]
    assert _improvement_summary("Quote Builder", "stopped", "criteria_worse", criteria=moved) == (
        "Your improvement of Quote Builder finished an attempt: a criterion the answers are "
        "graded on got worse, though no question broke. The selected attempt is better on price "
        "break 9/40 → 40/40 and worse on under 200 words 40/40 → 30/40; no whole question "
        "flipped."
    )


def test_a_verdict_a_whole_question_decided_names_no_criterion():
    assert moved_criteria("better", [_PRICE_BREAK]) == []
    assert moved_criteria(None, [_PRICE_BREAK]) == []


def test_the_outcome_carries_the_moved_criteria_and_drops_a_malformed_list():
    moved = {"name": "price break", "graded": 40, "before": 9, "after": 40, "direction": "better"}
    read = NotificationRead.from_row(
        _row("improvement_finished", {"status": "ready", "criteria": [moved]}),
        strip_context_url=False,
    ).outcome
    assert read is not None and read.criteria == [moved]
    broken = NotificationRead.from_row(
        _row("improvement_finished", {"status": "ready", "criteria": [{"name": 3}]}),
        strip_context_url=False,
    ).outcome
    assert broken is not None and broken.criteria == []


def test_an_attempt_only_worse_on_a_criterion_names_no_gain():
    moved = moved_criteria("criteria_worse", [_LENGTH])

    assert _improvement_summary("Quote Builder", "stopped", "criteria_worse", criteria=moved) == (
        "Your improvement of Quote Builder finished an attempt: a criterion the answers are "
        "graded on got worse, though no question broke. The selected attempt is worse on under "
        "200 words 40/40 → 30/40; no whole question flipped."
    )


def test_a_confirmed_fix_with_a_net_pass_decline_is_not_notified_as_better():
    declined = {**_PRICE_BREAK, "before": 30, "after": 20, "fixed": 1}
    assert moved_criteria("criteria_better", [declined]) == []


def test_notification_criteria_preserve_and_disambiguate_scorers():
    moved = moved_criteria(
        "criteria_worse", [{**_PRICE_BREAK, "name": "Validity"}, {**_LENGTH, "name": "Validity"}]
    )
    summary = _improvement_summary("Clerk", "ready", None, criteria=moved)
    assert "Validity [judge]" in summary and "Validity [check]" in summary
    outcome = NotificationRead.from_row(
        _row("improvement_finished", {"status": "ready", "criteria": moved}),
        strip_context_url=False,
    ).outcome
    assert outcome is not None and outcome.criteria == moved
    legacy: MovedCriterion = {
        "name": "Validity",
        "graded": 2,
        "before": 0,
        "after": 1,
        "direction": "better",
    }
    assert "[" not in _improvement_summary("Clerk", "ready", None, criteria=[legacy])


def test_notification_labels_keep_collision_context_when_the_other_scorer_is_truncated():
    gained = {**_PRICE_BREAK, "name": "Validity"}
    broken = {**_LENGTH, "name": "Validity"}
    moved = moved_criteria(
        "criteria_worse", [broken, _PRICE_BREAK, {**_PRICE_BREAK, "name": "Other"}, gained]
    )
    assert len(moved) == 3
    assert moved[0]["name"] == "Validity" and moved[0]["display_name"] == "Validity [check]"
    assert not any(item["scorer"] == "judge" and item["name"] == "Validity" for item in moved)
    assert "Validity [check]" in _improvement_summary("Clerk", "ready", None, criteria=moved)


def test_notification_labels_also_qualify_a_moved_name_shared_with_an_unchanged_criterion():
    moved = moved_criteria(
        "criteria_better",
        [
            {**_PRICE_BREAK, "name": "Validity"},
            {**_VALIDITY, "scorer": "check", "name": "Validity"},
        ],
    )
    assert len(moved) == 1 and moved[0]["display_name"] == "Validity [judge]"
