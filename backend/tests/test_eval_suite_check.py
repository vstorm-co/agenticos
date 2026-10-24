"""What the suite a check of suggestions ran on says of the run, as the run's read carries it.

The verdict is judged exactly as the suite judges its own runs, by the
threshold kept when the check started; these pin what reaches the judge and
what a run that did not complete, or a suite that went, reads as.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.eval_run import ArmRole, EvalRunStatus
from app.schemas.eval_threshold import EvalSuiteCheck, EvalSuiteThreshold
from app.services.eval_run import EvalRunService
from tests.test_eval_suite_threshold import _comparison, _summary

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
AGENT = uuid.uuid4()
SUITE = uuid.uuid4()


def _run(status: EvalRunStatus) -> SimpleNamespace:
    check = EvalSuiteCheck(
        suite_id=SUITE, name="nightly", threshold=EvalSuiteThreshold(min_pass_rate=0.5)
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=AGENT,
        status=status.value,
        suite_check=check.model_dump(mode="json"),
        proposal_check=None,
    )


def _read(*, ungraded: int) -> SimpleNamespace:
    summary = _summary(passed=10 - ungraded, ungraded=ungraded)
    candidate = SimpleNamespace(role=ArmRole.CANDIDATE, summary=summary)
    baseline = SimpleNamespace(role=ArmRole.BASELINE)
    return SimpleNamespace(arms=[baseline, candidate])


async def _verdict(run: SimpleNamespace, read: SimpleNamespace, *, suite: object | None):
    service = EvalRunService(MagicMock())
    ctx = SimpleNamespace(organization_id=ORG)
    with (
        patch("app.services.eval_run.eval_suite_repo.get", new=AsyncMock(return_value=suite)),
        patch.object(EvalRunService, "_comparison", new=AsyncMock(return_value=_comparison())),
    ):
        # Stand-ins for the run, its read and the caller: only the fields judged are set.
        return await service._suite_check(ctx, run, read)  # ty: ignore[invalid-argument-type]


async def test_cases_left_ungraded_make_a_passing_run_inconclusive():
    verdict = await _verdict(
        _run(EvalRunStatus.COMPLETED), _read(ungraded=2), suite=SimpleNamespace(agent_id=AGENT)
    )

    assert (verdict.status, [(r.code, r.value) for r in verdict.reasons]) == (
        "inconclusive",
        [("ungraded", 2)],
    )
    assert verdict.suite_exists


async def test_a_run_meeting_the_kept_threshold_passes():
    verdict = await _verdict(
        _run(EvalRunStatus.COMPLETED), _read(ungraded=0), suite=SimpleNamespace(agent_id=AGENT)
    )

    assert (verdict.status, verdict.reasons) == ("passed", [])


@pytest.mark.parametrize(
    "status", [EvalRunStatus.RUNNING, EvalRunStatus.FAILED, EvalRunStatus.CANCELLED]
)
async def test_a_run_that_did_not_complete_has_no_verdict(status):
    verdict = await _verdict(_run(status), _read(ungraded=0), suite=None)

    assert (verdict.status, verdict.reasons, verdict.name) == (None, [], "nightly")
    assert not verdict.suite_exists


async def test_a_suite_of_another_agent_under_the_same_id_is_not_offered_to_open():
    verdict = await _verdict(
        _run(EvalRunStatus.COMPLETED),
        _read(ungraded=0),
        suite=SimpleNamespace(agent_id=uuid.uuid4()),
    )

    assert not verdict.suite_exists
