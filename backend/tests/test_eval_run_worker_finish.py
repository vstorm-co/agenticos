"""An eval worker's answer for an attempt closed while it worked, and what it serves
and tells when it closes a run."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.skills import SkillBodyFile
from app.core.exceptions import AuthenticationError
from app.db.models.eval_run import (
    AttemptFault,
    CaseAttemptStatus,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
    EvalRunStatus,
)
from app.schemas.eval_run import KnowledgeCheckRecord, ProposalCheckRecord
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker, _candidate
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
        patch("app.services.eval_run_worker.eval_run_repo.get", new=AsyncMock(return_value=None)),
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
    with (
        patch("app.services.eval_run_worker.eval_run_repo.finish_case", new=finish),
        patch("app.services.eval_run_worker.eval_run_repo.get", new=AsyncMock(return_value=None)),
    ):
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


async def test_an_answer_to_a_withdrawn_draft_is_dropped_though_its_score_is_gone() -> None:
    """A score removed while the answer was written leaves nothing of it to forget, and the
    answer and its run are still not kept."""
    org = uuid.uuid4()
    attempt = EvalRunCase(id=uuid.uuid4(), organization_id=org, agent_run_id=None)
    record = ProposalCheckRecord(
        kind="context",
        base_version=1,
        suggestions=1,
        knowledge=KnowledgeCheckRecord(topic_id=uuid.uuid4(), draft_hash="0" * 64, supported=True),
    )
    run = SimpleNamespace(
        organization_id=org,
        created_by_user_id=uuid.uuid4(),
        created_by_api_key_id=None,
        proposal_check=record.model_dump(mode="json"),
    )
    answered_by, score_id = uuid.uuid4(), uuid.uuid4()
    finish = AsyncMock(return_value=True)
    forget = AsyncMock()

    with (
        patch("app.services.eval_run_worker.eval_run_repo.get", new=AsyncMock(return_value=run)),
        patch("app.services.eval_run_worker.job_context", new=AsyncMock(return_value=None)),
        patch("app.services.eval_run_worker.eval_run_repo.scores", new=AsyncMock(return_value={})),
        patch("app.services.eval_run_worker.personal_data_repo.forget_knowledge_runs", new=forget),
        patch("app.services.eval_run_worker.eval_run_repo.finish_case", new=finish),
    ):
        await EvalRunWorker(uuid.uuid4(), org)._finish(
            AsyncMock(),
            attempt,
            values={
                "status": CaseAttemptStatus.DONE.value,
                "answer": "Returns take 30 days.",
                "agent_run_id": answered_by,
                "case_score_id": score_id,
            },
        )

    assert forget.await_args.args[1] == {answered_by}
    kept = finish.await_args.kwargs["values"]
    assert (kept["status"], kept["answer"], kept["calls"]) == ("failed", None, [])
    assert (kept["error"], kept["fault"]) == (
        "The knowledge draft is no longer available",
        AttemptFault.INFRASTRUCTURE.value,
    )


def test_a_queued_candidate_serves_the_files_it_was_measured_with() -> None:
    """A check of a changed file stores the file on the arm; the worker must serve it, or
    both sides answer with the stored files and the change is never measured."""
    skill_id = uuid.uuid4()
    arm = SimpleNamespace(
        skill_bodies={
            str(skill_id): {
                "description": "Refunds.",
                "content": "Body.",
                "resources": [{"name": "limits.md", "description": None, "content": "$500"}],
            }
        },
        context_bodies=None,
        source="draft",
        agent_version_id=None,
        spec={"name": "Desk"},
    )

    served = _candidate(cast(EvalRunArm, arm)).skill_bodies[skill_id]

    assert served.resources == (SkillBodyFile(name="limits.md", description=None, content="$500"),)


@pytest.mark.parametrize(
    ("check_id", "status"),
    [
        (None, EvalRunStatus.COMPLETED),
        (uuid.uuid4(), EvalRunStatus.COMPLETED),
        (uuid.uuid4(), EvalRunStatus.FAILED),
    ],
)
async def test_a_closed_run_tells_only_its_skill_check(
    check_id: uuid.UUID | None, status: EvalRunStatus
) -> None:
    """Only a completed run's arms are checked for skills that moved under them: a failed
    one stands in as no baseline anyway."""
    org, run_id = uuid.uuid4(), uuid.uuid4()
    record = ProposalCheckRecord(
        kind="skill", base_version=1, suggestions=1, skill_check_id=check_id
    )
    run = SimpleNamespace(
        organization_id=org, id=run_id, status="running", proposal_check=record.model_dump()
    )
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    after_run, forget = AsyncMock(), AsyncMock()
    with (
        patch("app.services.eval_run_worker.eval_run_repo.lock", new=AsyncMock(return_value=run)),
        patch("app.services.eval_run_worker.eval_run_repo.update_run", new=AsyncMock()),
        patch("app.services.eval_run_worker.NotificationService") as notices,
        patch("app.services.skill_check.SkillCheckService.after_run", new=after_run),
        patch.object(EvalRunService, "forget_moved_skills", new=forget),
        patch.object(EvalRunWorker, "_reader", new=AsyncMock(return_value=None)),
    ):
        notices.return_value.eval_run_finished = AsyncMock()
        await EvalRunWorker(run_id, org, sessions=sessions)._close(
            status, only_from=EvalRunStatus.RUNNING
        )

    assert after_run.await_count == (0 if check_id is None else 1)
    assert forget.await_count == (1 if status is EvalRunStatus.COMPLETED else 0)


@pytest.mark.parametrize("gone", [False, True])
async def test_a_runs_reader_is_its_starter_as_they_stand_or_none(gone: bool) -> None:
    ctx = MagicMock()
    rebuilt = AsyncMock(side_effect=AuthenticationError(message="gone") if gone else None)
    rebuilt.return_value = ctx
    run = SimpleNamespace(
        organization_id=uuid.uuid4(), created_by_user_id=uuid.uuid4(), created_by_api_key_id=None
    )

    with patch("app.services.eval_run_worker.job_context", new=rebuilt):
        reader = await EvalRunWorker(uuid.uuid4(), run.organization_id)._reader(
            MagicMock(), cast(EvalRun, run)
        )

    assert reader is (None if gone else ctx)
