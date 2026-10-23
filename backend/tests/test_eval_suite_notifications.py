"""What the owner of a failing suite is told: which suite, on what, why, and which cases."""

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models.agent import Agent
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult
from app.schemas.eval_suite import EvalSuiteSummary, FailingCase, ThresholdReason
from app.services.notifications import NotificationService, _suite_summary

pytestmark = pytest.mark.anyio


def _rows(**result: Any) -> tuple[EvalSuite, EvalSuiteResult, Agent]:
    org = uuid.uuid4()
    agent = Agent(id=uuid.uuid4(), organization_id=org, name="Clerk", slug="clerk", draft_spec={})
    suite = EvalSuite(
        id=uuid.uuid4(),
        organization_id=org,
        agent_id=agent.id,
        name="Refunds",
        owner_user_id=uuid.uuid4(),
    )
    row = EvalSuiteResult(
        id=uuid.uuid4(), organization_id=org, suite_id=suite.id, **{"version_number": 7, **result}
    )
    return suite, row, agent


def _failing(count: int) -> list[FailingCase]:
    return [
        FailingCase(case_id=uuid.uuid4(), input=f"Question {index}", kind="failed")
        for index in range(count)
    ]


def test_a_failure_names_why_and_the_first_cases() -> None:
    summary = EvalSuiteSummary(
        pass_rate=0.4,
        first_pass_rate=0.4,
        cases=10,
        reasons=[
            ThresholdReason(code="pass_rate_below", value=0.4, limit=0.8),
            ThresholdReason(code="regressions", value=2, limit=0),
        ],
        failing_cases=_failing(7),
    )
    suite, result, agent = _rows(status="failed")

    line = _suite_summary(suite, result, agent=agent, summary=summary)

    assert line.startswith(
        "Refunds failed on Clerk v7: pass rate 40% is below 80%; 2 case(s) break"
    )
    assert "'Question 0', 'Question 1', 'Question 2', 'Question 3', 'Question 4'" in line
    assert line.endswith("and 2 more.")


@pytest.mark.parametrize(
    ("reason", "said"),
    [
        (ThresholdReason(code="nothing_graded", limit=0.8), "no case could be graded"),
        (
            ThresholdReason(code="cost_per_pass_rise", value=0.5, limit=0.2),
            "cost per passed case rose 50%",
        ),
        (ThresholdReason(code="p95_rise", value=1.0, limit=0.5), "p95 latency rose 100%"),
        (ThresholdReason(code="invalid_comparison"), "the comparison is invalid"),
    ],
)
def test_each_reason_is_said_in_words(reason: ThresholdReason, said: str) -> None:
    summary = EvalSuiteSummary(pass_rate=None, first_pass_rate=None, cases=0, reasons=[reason])
    suite, result, agent = _rows(status="failed")

    assert f": {said}." in _suite_summary(suite, result, agent=agent, summary=summary)


def test_an_undecided_result_names_the_cases_nobody_graded() -> None:
    summary = EvalSuiteSummary(
        pass_rate=1.0,
        first_pass_rate=1.0,
        cases=4,
        reasons=[ThresholdReason(code="ungraded", value=1)],
        failing_cases=[
            FailingCase(case_id=uuid.uuid4(), input="Where is it?", kind="ungraded"),
            FailingCase(case_id=uuid.uuid4(), input="Can I return it?", kind="failed"),
        ],
    )
    suite, result, agent = _rows(status="inconclusive")

    assert _suite_summary(suite, result, agent=agent, summary=summary) == (
        "Refunds could not decide on Clerk v7: 1 case(s) could not be graded. "
        "Not graded: 'Where is it?'."
    )


def test_a_cancelled_run_says_it_was_cancelled_rather_than_below_a_threshold() -> None:
    suite, result, agent = _rows(status="inconclusive", reason="cancelled")
    told = EvalSuiteSummary(
        pass_rate=None, first_pass_rate=None, cases=0, message="Its eval run was cancelled."
    )

    assert _suite_summary(suite, result, agent=agent, summary=told) == (
        "Refunds could not decide on Clerk v7: Its eval run was cancelled."
    )


def test_a_failure_with_nothing_recorded_still_reads() -> None:
    suite, result, agent = _rows(status="failed", version_number=None)
    assert _suite_summary(suite, result, agent=agent, summary=None) == (
        "Refunds failed on Clerk: below its threshold."
    )


def test_a_run_that_did_not_happen_says_why() -> None:
    suite, result, agent = _rows(status="skipped", reason="budget")
    told = EvalSuiteSummary(
        pass_rate=None, first_pass_rate=None, cases=0, message="It would cost more than is left."
    )

    assert _suite_summary(suite, result, agent=agent, summary=told) == (
        "Refunds did not run on Clerk v7: It would cost more than is left."
    )
    assert _suite_summary(suite, result, agent=agent, summary=None) == (
        "Refunds did not run on Clerk v7: budget."
    )


async def test_an_owner_who_is_no_longer_a_member_is_told_nothing() -> None:
    suite, result, agent = _rows(status="failed")
    service = NotificationService(AsyncMock())
    with (
        patch(
            "app.services.notifications.member_repo.list_member_ids_for",
            AsyncMock(return_value=set()),
        ),
        patch.object(service._center, "write", AsyncMock()) as write,
    ):
        await service.eval_suite_failed(suite, result, agent=agent)

    write.assert_not_awaited()
