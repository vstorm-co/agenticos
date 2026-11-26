"""An eval worker's answer for an attempt closed while it worked, and what it serves
and tells when it closes a run."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.skills import SkillBodyFile
from app.core.exceptions import AuthenticationError
from app.db.models.agent_run import AgentRun
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


_ARM_ID = uuid.uuid4()


def _attempt(**fields: object) -> EvalRunCase:
    defaults: dict[str, object] = {
        "attempt": 0,
        "arm_id": _ARM_ID,
        "status": CaseAttemptStatus.DONE.value,
        "agent_run_id": uuid.uuid4(),
    }
    return EvalRunCase(id=uuid.uuid4(), case_revision_id=uuid.uuid4(), **{**defaults, **fields})


async def _ask_lost_again(
    attempts: list[EvalRunCase],
    *,
    status: str = EvalRunStatus.RUNNING.value,
    session: bool = True,
    linked: bool = True,
    budget: str = "10",
    spent: str = "4",
    prices: dict[uuid.UUID, Decimal] | None = None,
    anonymised: frozenset[uuid.UUID] = frozenset(),
) -> tuple[bool, list[EvalRunCase], set[uuid.UUID]]:
    """Run the step on a check of `len(attempts)` first answers estimated at 4 USD with
    1 USD of reruns; what it returned, what it queued and which runs it forgot."""
    org = uuid.uuid4()
    firsts = [attempt for attempt in attempts if attempt.attempt == 0]
    price_by_arm = (
        prices
        if prices is not None
        else {attempt.arm_id: Decimal(4) / len(firsts) for attempt in firsts}
    )
    arm_ids = list(price_by_arm) or list(dict.fromkeys(attempt.arm_id for attempt in firsts))
    arms = [EvalRunArm(id=arm_id, position=position) for position, arm_id in enumerate(arm_ids)]
    record = ProposalCheckRecord(
        kind="agent",
        answer_estimates_usd=list(price_by_arm.values()),
        base_version=None,
        on_draft=True,
        suggestions=1,
        improvement_run_id=uuid.uuid4() if linked else None,
    )
    run = SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        proposal_check=record.model_dump(mode="json"),
        estimate_usd=Decimal("4"),
        rerun_ceiling_usd=Decimal("1"),
    )
    revisions = {
        a.case_revision_id: SimpleNamespace(
            anonymised_at=datetime.now(UTC) if a.case_revision_id in anonymised else None
        )
        for a in attempts
    }
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    queued, forgotten = AsyncMock(), AsyncMock()
    with (
        patch("app.services.eval_run_worker.eval_run_repo.lock", new=AsyncMock(return_value=run)),
        patch(
            "app.services.eval_run_worker.eval_run_repo.list_cases",
            new=AsyncMock(return_value=attempts),
        ),
        patch(
            "app.services.eval_run_worker.eval_run_repo.revisions",
            new=AsyncMock(return_value=revisions),
        ),
        patch(
            "app.services.eval_run_worker.improvement_repo.get_run",
            new=AsyncMock(
                return_value=SimpleNamespace(budget_usd=Decimal(budget)) if session else None
            ),
        ),
        patch(
            "app.services.eval_run_worker.improvement_repo.spent",
            new=AsyncMock(return_value=Decimal(spent)),
        ),
        patch(
            "app.services.eval_run_worker.eval_run_repo.list_arms", new=AsyncMock(return_value=arms)
        ),
        patch("app.services.eval_run_worker.eval_run_repo.ask_again", new=queued),
        patch("app.services.eval_run_worker.personal_data_repo.forget_runs", new=forgotten),
    ):
        asked = await EvalRunWorker(run.id, org, sessions=sessions)._ask_lost_again()
    queued_call, forgotten_call = queued.await_args, forgotten.await_args
    return (
        asked,
        [] if queued_call is None else list(queued_call.kwargs["cases"]),
        set() if forgotten_call is None else set(forgotten_call.args[1]),
    )


async def test_only_the_answers_the_infrastructure_lost_are_asked_again() -> None:
    """A timed-out answer is asked again and what its run kept of the question is forgotten;
    an answer the agent failed on is a result, a rerun is not a first answer, and an
    anonymised case is never asked again."""
    timed_out = _attempt(status="failed", fault=AttemptFault.INFRASTRUCTURE.value)
    before_faults = _attempt(status="failed", fault=None, agent_run_id=None)
    crashed = _attempt(status="failed", fault=AttemptFault.AGENT.value)
    rerun = _attempt(status="failed", fault=AttemptFault.INFRASTRUCTURE.value, attempt=1)
    erased = _attempt(status="failed", fault=AttemptFault.INFRASTRUCTURE.value)
    answered = _attempt()

    asked, queued, forgotten = await _ask_lost_again(
        [timed_out, before_faults, crashed, rerun, erased, answered],
        anonymised=frozenset({erased.case_revision_id}),
    )

    assert asked
    assert queued == [timed_out, before_faults]
    assert forgotten == {timed_out.agent_run_id}


@pytest.mark.security
@pytest.mark.parametrize(
    ("status", "linked", "session", "budget"),
    [
        (EvalRunStatus.BUDGET_EXCEEDED.value, True, True, "10"),
        (EvalRunStatus.RUNNING.value, False, True, "10"),
        (EvalRunStatus.RUNNING.value, True, False, "10"),
        # 4 spent + 2 of 4 answers at 1 USD each + 1 of reruns is 7: over a 6.5 budget.
        (EvalRunStatus.RUNNING.value, True, True, "6.5"),
    ],
)
async def test_lost_answers_are_left_when_the_check_or_its_session_cannot_pay_for_them(
    status: str, linked: bool, session: bool, budget: str
) -> None:
    lost = [_attempt(status="failed", fault=AttemptFault.INFRASTRUCTURE.value) for _ in range(2)]

    asked, queued, forgotten = await _ask_lost_again(
        [*lost, _attempt(), _attempt()],
        status=status,
        linked=linked,
        session=session,
        budget=budget,
    )

    assert (asked, queued, forgotten) == (False, [], set())


@pytest.mark.security
async def test_lost_answers_are_asked_again_when_the_budget_just_covers_them() -> None:
    lost = [_attempt(status="failed", fault=AttemptFault.INFRASTRUCTURE.value) for _ in range(2)]

    asked, queued, _ = await _ask_lost_again([*lost, _attempt(), _attempt()], budget="7")

    assert asked and queued == lost


@pytest.mark.security
@pytest.mark.parametrize(
    ("lost_expensive", "budget", "expected"),
    [(True, "7.5", False), (True, "8.9", True), (False, "5.1", True)],
)
async def test_replacement_budget_uses_the_lost_answers_arm(lost_expensive, budget, expected):
    cheap, expensive = uuid.uuid4(), uuid.uuid4()
    lost = _attempt(
        arm_id=expensive if lost_expensive else cheap,
        status="failed",
        fault=AttemptFault.INFRASTRUCTURE.value,
    )
    answered = _attempt(arm_id=cheap if lost_expensive else expensive)
    asked, queued, forgotten = await _ask_lost_again(
        [lost, answered], budget=budget, prices={cheap: Decimal("0.1"), expensive: Decimal("3.9")}
    )
    assert asked is expected
    assert queued == ([lost] if expected else [])
    assert forgotten == ({lost.agent_run_id} if expected else set())


@pytest.mark.security
async def test_an_older_check_without_frozen_prices_does_not_guess_a_replacement_budget(caplog):
    lost = _attempt(status="failed", fault=AttemptFault.INFRASTRUCTURE.value)
    with caplog.at_level("INFO", logger="app.services.eval_run_worker"):
        assert await _ask_lost_again([lost], prices={}) == (False, [], set())
    assert "eval_answer_retry_estimate_missing" in caplog.text


async def test_a_check_with_nothing_lost_asks_nothing_again() -> None:
    asked, queued, _ = await _ask_lost_again([_attempt(), _attempt()])

    assert (asked, queued) == (False, [])


async def test_a_manual_eval_does_not_ask_its_lost_answers_again() -> None:
    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    run = SimpleNamespace(status=EvalRunStatus.RUNNING.value, proposal_check=None)
    listed = AsyncMock()
    with (
        patch("app.services.eval_run_worker.eval_run_repo.lock", new=AsyncMock(return_value=run)),
        patch("app.services.eval_run_worker.eval_run_repo.list_cases", new=listed),
    ):
        assert not await EvalRunWorker(
            uuid.uuid4(), uuid.uuid4(), sessions=sessions
        )._ask_lost_again()

    assert listed.await_count == 0


@pytest.mark.parametrize("asked_again", [False, True])
async def test_lost_answers_are_asked_before_the_flips_are_confirmed(asked_again: bool) -> None:
    """A case settled by asking again is then confirmed like any other."""
    worker = EvalRunWorker(uuid.uuid4(), uuid.uuid4(), heartbeat=3600)
    steps: list[str] = []

    async def step(name: str, result: bool = False):
        steps.append(name)
        return result

    with (
        patch.object(EvalRunWorker, "_begin", new=AsyncMock(return_value=MagicMock())),
        patch.object(EvalRunWorker, "_wave", new=lambda self, ctx: step("wave")),
        patch.object(EvalRunWorker, "_ask_lost_again", new=lambda self: step("ask", asked_again)),
        patch.object(EvalRunWorker, "_queue_reruns", new=lambda self, ctx: step("reruns")),
        patch.object(EvalRunWorker, "_route_to_review", new=AsyncMock()),
        patch.object(EvalRunWorker, "_close", new=AsyncMock()),
    ):
        await worker._work()

    assert steps == ["wave", "ask", *(["wave"] if asked_again else []), "reruns"]


@pytest.mark.parametrize(
    ("before", "partial"), [(None, False), (Decimal("0.02"), False), (Decimal("0.02"), True)]
)
def test_an_answer_asked_again_keeps_what_its_failed_try_spent(
    before: Decimal | None, partial: bool
) -> None:
    attempt = EvalRunCase(cost_usd=before, cost_is_partial=partial)
    agent_run = SimpleNamespace(
        id=uuid.uuid4(),
        cost_usd=Decimal("0.01"),
        cost_is_partial=False,
        input_tokens=10,
        output_tokens=2,
        started_at=None,
        ended_at=None,
    )

    spend = EvalRunWorker._spend(cast(AgentRun, agent_run), attempt)

    assert spend["cost_usd"] == Decimal("0.01") + (before or 0)
    assert spend["cost_is_partial"] is partial
    assert (spend["input_tokens"], spend["output_tokens"]) == (10, 2)


@pytest.mark.security
async def test_paired_criteria_read_score_json_in_bounded_batches(mock_db_session, monkeypatch):
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.permissions import AuthContext
    from app.db.models.case_score import CaseScore
    from app.services.eval_comparison import family_flipped

    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    candidate, baseline = EvalRunArm(id=uuid.uuid4()), EvalRunArm(id=uuid.uuid4())
    case_ids = [uuid.uuid4() for _ in range(51)]
    score_cases: dict[UUID, tuple[UUID, bool]] = {}

    def attempts(arm: EvalRunArm, is_candidate: bool) -> list[EvalRunCase]:
        result: list[EvalRunCase] = []
        for case_id in case_ids:
            score_id = uuid.uuid4()
            score_cases[score_id] = (case_id, is_candidate)
            result.append(
                EvalRunCase(arm_id=arm.id, case_id=case_id, case_score_id=score_id, attempt=0)
            )
        return result

    mine, theirs = attempts(candidate, True), attempts(baseline, False)
    read_sizes: list[int] = []

    async def scores(
        _db: AsyncSession, score_ids: Sequence[UUID], *, organization_id: UUID
    ) -> dict[UUID, CaseScore]:
        assert organization_id == ctx.organization_id
        read_sizes.append(len(score_ids))
        assert len(score_ids) <= 50
        result: dict[UUID, CaseScore] = {}
        for score_id in score_ids:
            case_id, is_candidate = score_cases[score_id]
            result[score_id] = CaseScore(
                id=score_id,
                results=[
                    {
                        "scorer": "check",
                        "name": f"{case_id} check {number}",
                        "required": True,
                        "status": "fail"
                        if is_candidate and case_id == case_ids[-1] and number == 49
                        else "pass",
                    }
                    for number in range(50)
                ],
            )
        return result

    monkeypatch.setattr("app.services.eval_run.eval_run_repo.scores", scores)
    service = EvalRunService(mock_db_session)
    pages = [
        page
        async for page in service.criterion_batches(
            ctx,
            candidate,
            mine,
            baseline,
            theirs,
            case_ids=[*case_ids, uuid.uuid4()],
        )
    ]
    assert [len(page) for page in pages] == [50, 1]
    assert read_sizes == [50, 50, 1, 1]
    assert {case_id for page in pages for case_id, _ in page} == set(case_ids)
    last = pages[-1][0][1]
    assert family_flipped(last.baseline, last.candidate, last.named, {f"{case_ids[-1]} check 49"})


@pytest.mark.parametrize(
    ("before", "current", "expected"),
    [(7, 10, 17), (None, 10, 10), (7, None, 7), (None, None, None)],
)
async def test_requeueing_an_answer_retains_and_accumulates_its_usage(
    mock_db_session, before, current, expected
):
    from app.repositories import eval_run_repo

    attempt = EvalRunCase(
        status="failed",
        input_tokens=before,
        output_tokens=before,
        latency_ms=before,
        cost_usd=Decimal("0.02"),
        agent_run_id=uuid.uuid4(),
    )
    await eval_run_repo.ask_again(mock_db_session, cases=[attempt])
    assert attempt.input_tokens == attempt.output_tokens == attempt.latency_ms == before
    assert attempt.agent_run_id is None and attempt.status == "pending"
    agent_run = SimpleNamespace(
        id=uuid.uuid4(),
        cost_usd=Decimal("0.01"),
        cost_is_partial=False,
        input_tokens=current,
        output_tokens=current,
        started_at=datetime(2026, 11, 19, tzinfo=UTC),
        ended_at=None
        if current is None
        else datetime(2026, 11, 19, tzinfo=UTC) + timedelta(milliseconds=current),
    )
    spent = EvalRunWorker._spend(cast(AgentRun, agent_run), attempt)
    assert spent["input_tokens"] == spent["output_tokens"] == spent["latency_ms"] == expected
    assert spent["cost_usd"] == Decimal("0.03")
