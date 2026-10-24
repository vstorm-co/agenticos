"""An eval worker's answer for an attempt that was closed while it worked."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.eval_run import AttemptFault, CaseAttemptStatus, EvalRunCase
from app.services.eval_run_worker import EvalRunWorker
from app.services.scoring import _kept_answer

pytestmark = pytest.mark.anyio


async def test_an_answer_for_an_attempt_closed_meanwhile_is_dropped_and_said(caplog) -> None:
    """A worker whose lease ran out may still answer after its job's settler failed the
    run; the conditional write misses, and the worker says so rather than retrying."""
    run_id = uuid.uuid4()
    attempt = EvalRunCase(id=uuid.uuid4(), organization_id=uuid.uuid4())
    worker = EvalRunWorker(run_id, attempt.organization_id)
    finish = AsyncMock(return_value=False)

    with (
        patch("app.services.eval_run_worker.eval_run_repo.finish_case", new=finish),
        caplog.at_level("WARNING", logger="app.services.eval_run_worker"),
    ):
        await worker._finish(MagicMock(), attempt, values={"status": CaseAttemptStatus.DONE.value})

    assert finish.await_args.kwargs["values"] == {"status": CaseAttemptStatus.DONE.value}
    [said] = [r for r in caplog.records if r.message == "eval_case_closed_meanwhile"]
    assert said.eval_run_id == str(run_id)
    assert said.case_id == str(attempt.id)


@pytest.mark.parametrize("failed", [False, True])
async def test_attempt_evidence_redacts_answers_nested_calls_and_errors(failed: bool) -> None:
    secret = "ghp_" + "k" * 36
    answer = f"The key is {secret}"
    calls = [
        {
            "tool": "lookup",
            "args": {"nested": [secret, 3, False, None]},
            "result": {"token": secret},
            "outcome": "executed",
            "reason": "No secret",
        }
    ]
    attempt = EvalRunCase(id=uuid.uuid4(), organization_id=uuid.uuid4())
    worker = EvalRunWorker(uuid.uuid4(), attempt.organization_id)
    finish = AsyncMock(return_value=True)
    values = {"answer": answer, "calls": calls, "error": secret}
    with patch("app.services.eval_run_worker.eval_run_repo.finish_case", new=finish):
        if failed:
            await worker._fail(
                MagicMock(),
                attempt,
                secret,
                fault=AttemptFault.INFRASTRUCTURE,
                answer=answer,
                calls=calls,
            )
        else:
            await worker._finish(MagicMock(), attempt, values=values)
    kept = finish.await_args.kwargs["values"]
    assert kept["answer"] == _kept_answer(answer)
    assert "[redacted:" in kept["answer"]
    assert secret not in str(kept)
    assert kept["calls"][0]["args"]["nested"][1:] == [3, False, None]
    assert kept["calls"][0]["reason"] == "No secret"
    assert values["answer"] == answer and calls[0]["result"]["token"] == secret
