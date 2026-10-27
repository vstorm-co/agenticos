"""Finished sessions, tests and question writing are worded without internal codes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.db.models.notification import Notification
from app.schemas.notification import NotificationRead
from app.services.notifications import _improvement_summary


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
            "Your improvement of Refund desk has changes to choose from. "
            "Pick the ones to check, then take the next step.",
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
    for event_type, context in [
        ("case_generation_finished", {}),
        ("case_generation_finished", None),
        ("approval_requested", {"status": "pending"}),
    ]:
        assert (
            NotificationRead.from_row(_row(event_type, context), strip_context_url=False).outcome
            is None
        )
