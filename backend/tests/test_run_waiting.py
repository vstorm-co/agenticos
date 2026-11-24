"""What a parked run is waiting on, as the run reads report it.

`waiting_update` is the whole derivation: the run's unanswered questions and
the instant they expire, read off the loaded row. A run that is not parked on
an answer carries nothing - an empty list and no expiry - so a finished thread
never looks as if it is still waiting.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart

from app.core.config import settings
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.services.parked_runs import waiting_update


def _row(**overrides: object) -> AgentRun:
    """A run row, not persisted - this is about the derivation, not the database."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "surface": RunSurface.WEB.value,
        "status": RunStatus.COMPLETED.value,
        "input_tokens": 56,
        "output_tokens": 5,
        "tool_args_repaired": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": Decimal("0.000030"),
        "cost_is_partial": False,
        "modality": "text",
        "is_test": False,
    }
    return AgentRun(**{**defaults, **overrides})


def _paused_state(*questions: str) -> dict[str, object]:
    calls = [
        ToolCallPart(
            "ask_user_question",
            {
                "questions": [
                    {
                        "header": f"Question {index}",
                        "question": question,
                        "options": [{"label": "A"}, {"label": "B"}],
                    }
                ]
            },
            tool_call_id=f"ask-{index}",
        )
        for index, question in enumerate(questions, start=1)
    ]
    return {
        "messages": ModelMessagesTypeAdapter.dump_python(
            [ModelResponse(parts=[call]) for call in calls], mode="json"
        ),
        "tool_call_ids": {},
        "questions": [f"ask-{index}" for index in range(1, len(questions) + 1)],
    }


def test_a_run_parked_on_an_answer_reports_its_questions_and_their_expiry() -> None:
    """The question text and the park time plus the expiry window."""
    parked_at = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    run = _row(
        status=RunStatus.AWAITING_ANSWER.value,
        ended_at=parked_at,
        paused_state=_paused_state("Which model should I use?", "And the budget?"),
    )

    update = waiting_update(run)

    assert update["waiting_questions"] == ["Which model should I use?", "And the budget?"]
    assert update["waiting_expires_at"] == parked_at + timedelta(
        hours=settings.QUESTION_EXPIRY_HOURS
    )


@pytest.mark.security
def test_a_run_parked_on_an_approval_alone_reports_nothing_to_answer() -> None:
    """Approvals are the approvals tab's business; this read says what a run is
    waiting to be *asked*, and an approval-only park asked nothing."""
    run = _row(
        status=RunStatus.AWAITING_APPROVAL.value,
        ended_at=datetime(2026, 11, 12, 8, 0, tzinfo=UTC),
        paused_state={"questions": []},
    )

    assert waiting_update(run) == {}


def test_a_finished_run_reports_nothing_to_answer() -> None:
    """A completed run's `paused_state` is history, not a question - even if the
    row still carries one from an earlier park."""
    run = _row(
        status=RunStatus.COMPLETED.value,
        ended_at=datetime(2026, 11, 12, 8, 0, tzinfo=UTC),
        paused_state={"questions": ["Which model should I use?"]},
    )

    assert waiting_update(run) == {}


def test_a_parked_run_with_no_park_time_reports_nothing() -> None:
    """Without `ended_at` there is no park time to add the expiry window to, so
    nothing is reported rather than an expiry invented from the read time."""
    run = _row(
        status=RunStatus.AWAITING_ANSWER.value,
        ended_at=None,
        paused_state={"questions": ["Which model should I use?"]},
    )

    assert waiting_update(run) == {}


def test_waiting_question_ids_are_mapped_to_the_question_text() -> None:
    """The persisted ids identify tool calls; the person sees their question text."""
    run = _row(
        status=RunStatus.AWAITING_ANSWER.value,
        ended_at=datetime(2026, 11, 12, 8, 0, tzinfo=UTC),
        paused_state={
            **_paused_state("Which model should I use?"),
            "questions": ["ask-1"],
        },
    )

    assert waiting_update(run)["waiting_questions"] == ["Which model should I use?"]


@pytest.mark.security
def test_waiting_secret_ids_report_only_the_requested_name_and_expiry() -> None:
    parked_at = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
    call = ToolCallPart(
        "request_secret",
        {"secret_name": "acme_api_key", "what_for": "Read contacts", "kind": "api_key"},
        tool_call_id="secret-1",
    )
    run = _row(
        status=RunStatus.AWAITING_ANSWER.value,
        ended_at=parked_at,
        paused_state={
            "messages": ModelMessagesTypeAdapter.dump_python(
                [ModelResponse(parts=[call])], mode="json"
            ),
            "tool_call_ids": {},
            "questions": [],
            "secret_requests": ["secret-1"],
        },
    )

    assert waiting_update(run) == {
        "waiting_questions": [],
        "waiting_secret_requests": ["acme_api_key"],
        "waiting_expires_at": parked_at + timedelta(hours=settings.QUESTION_EXPIRY_HOURS),
    }
