"""Executing an eval run: every case answered, scored and kept, then the flips confirmed.

One worker per eval run, in a background job of its own, so a run survives the
API process that started it. Inside, a few drainers claim attempts one at a time:
each claim counts the organization's running cases under a lock first, so an
organization never has more cases running than its limit however many runs and
workers it has, and a cancelled run hands out nothing more.

Every attempt is an ordinary agent run on its own session - the run path commits
before it calls the model and again when it ends - isolated so that no writing
tool runs without a test connection, and attributed to no version when it runs
a draft. What it answered and called is copied onto the attempt, because a run
without a conversation keeps no transcript.

After the first answer of every case, the cases whose outcome flipped against
the baseline are rerun, and the run ends.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ToolCallPart
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.context import ContextBody
from app.agents.capabilities.skills import SkillBody
from app.agents.failures import run_failure_summary
from app.agents.isolation import RunIsolation, ToolRecording, recorded_args
from app.agents.spec import AgentSpec
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    BadRequestError,
    NotFoundError,
    NothingToScoreError,
)
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.dataset import DatasetCase
from app.db.models.eval_run import (
    ArmSource,
    CaseAttemptStatus,
    EvalRun,
    EvalRunArm,
    EvalRunCase,
    EvalRunStatus,
)
from app.db.models.intercepted_tool_call import InterceptedToolCall, InterceptionOutcome
from app.db.session import get_worker_db_context
from app.repositories import (
    dataset_repo,
    eval_run_repo,
    intercepted_tool_call_repo,
    member_repo,
)
from app.schemas.scoring import DatasetScoring
from app.services.agent_registry import Candidate, PublishedCandidate, UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.eval_comparison import Flip, classify
from app.services.eval_run import EvalRunService
from app.services.message_history import HistoryMessage, build_message_history
from app.services.scorers import ScoredAnswer, ScoredCall
from app.services.scoring import ScoringService
from app.services.transcript import RecordedToolCall

logger = logging.getLogger(__name__)

#: How long a drainer waits when the organization has no free slot.
_FULL_BACKOFF_SECONDS = 2.0


type Sessions = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _candidate(arm: EvalRunArm) -> Candidate:
    bodies = {
        UUID(skill_id): SkillBody(description=body["description"], content=body["content"])
        for skill_id, body in (arm.skill_bodies or {}).items()
    }
    contexts = {
        UUID(context_id): ContextBody(description=body["description"], content=body["content"])
        for context_id, body in (arm.context_bodies or {}).items()
    }
    if arm.source == ArmSource.VERSION.value and arm.agent_version_id is not None:
        return PublishedCandidate(
            arm.agent_version_id, skill_bodies=bodies, context_bodies=contexts
        )
    return UnpublishedCandidate(
        AgentSpec.model_validate(arm.spec), skill_bodies=bodies, context_bodies=contexts
    )


def _latency_ms(run: AgentRun) -> int | None:
    if run.started_at is None or run.ended_at is None:
        return None
    return int((run.ended_at - run.started_at).total_seconds() * 1000)


def trajectory(
    calls: list[RecordedToolCall], intercepted: list[InterceptedToolCall]
) -> list[dict[str, Any]]:
    """An attempt's calls in order, each saying whether it really ran.

    A call isolation answered without executing it - held back because it
    writes, answered from a recording, or matching nothing recorded - carries
    that outcome and why; everything else ran.
    """
    held = {call.tool_call_id: call for call in intercepted}
    rows = []
    for call in calls:
        caught = held.get(call.tool_call_id)
        rows.append(
            {
                "tool": call.tool_name,
                "args": recorded_args(
                    ToolCallPart(call.tool_name, call.args, tool_call_id=call.tool_call_id)
                ),
                "outcome": caught.outcome if caught is not None else "executed",
                "reason": caught.reason if caught is not None else None,
            }
        )
    return rows


class EvalRunWorker:
    """Runs one eval run to its end."""

    def __init__(
        self,
        eval_run_id: UUID,
        organization_id: UUID,
        *,
        sessions: Sessions = get_worker_db_context,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        heartbeat: float | None = None,
    ) -> None:
        self.eval_run_id = eval_run_id
        self.organization_id = organization_id
        self.sessions = sessions
        self.sleep = sleep
        self.heartbeat = settings.EVAL_HEARTBEAT_SECONDS if heartbeat is None else heartbeat

    async def run(self) -> None:
        """Answer every case, confirm the flips, and close the run.

        A run the worker cannot finish ends `failed` here, as an agent run's
        does, rather than live until the sweep finds it silent.
        """
        try:
            await self._work()
        except Exception:
            await self._give_up()
            raise

    async def _work(self) -> None:
        ctx = await self._begin()
        if ctx is None:
            return
        beating = asyncio.create_task(self._beat())
        try:
            await self._wave(ctx)
            if await self._queue_reruns(ctx):
                await self._wave(ctx)
            await self._route_to_review(ctx)
            await self._close(EvalRunStatus.COMPLETED, only_from=EvalRunStatus.RUNNING)
        finally:
            beating.cancel()
            with suppress(asyncio.CancelledError):
                await beating

    async def _give_up(self) -> None:
        """Fail the run and what it had not finished, if it is still live."""
        try:
            async with self.sessions() as db:
                await eval_run_repo.fail_live(
                    db,
                    self.eval_run_id,
                    organization_id=self.organization_id,
                    now=datetime.now(UTC),
                    error="This eval stopped on an error before it finished. Run it again.",
                )
        except Exception:
            # The database that failed the run may refuse this as well; the
            # abandoned-eval sweep is the ceiling for that run.
            logger.exception("eval_run_not_closed", extra={"eval_run_id": str(self.eval_run_id)})

    async def _beat(self) -> None:
        """Say the run is alive every `heartbeat` seconds, for as long as it works.

        A case can outlast the sweep's window, and a full organization can hold
        every attempt back; neither moves an attempt, and only this tells them
        from a worker that died. A beat that fails is not the last: a worker
        that went silent over one dropped connection would be reaped mid-run.
        """
        while True:
            await asyncio.sleep(self.heartbeat)
            try:
                async with self.sessions() as db:
                    await eval_run_repo.heartbeat(
                        db,
                        self.eval_run_id,
                        organization_id=self.organization_id,
                        now=datetime.now(UTC),
                    )
            except Exception:
                logger.warning(
                    "eval_heartbeat_failed",
                    extra={"eval_run_id": str(self.eval_run_id)},
                    exc_info=True,
                )

    async def _begin(self) -> AuthContext | None:
        """Mark the run running and rebuild who it runs as - or end it if it cannot run."""
        async with self.sessions() as db:
            run = await eval_run_repo.lock(
                db, self.eval_run_id, organization_id=self.organization_id
            )
            if run is None or EvalRunStatus(run.status).terminal:
                return None
            ctx = await self._creator(db, run)
            if ctx is None:
                await eval_run_repo.update_run(
                    db,
                    run=run,
                    values={
                        "status": EvalRunStatus.FAILED.value,
                        "error": "Whoever started this eval is no longer a member.",
                        "ended_at": datetime.now(UTC),
                    },
                )
                await eval_run_repo.skip_pending(db, run.id, organization_id=self.organization_id)
                return None
            await eval_run_repo.update_run(
                db,
                run=run,
                values={"status": EvalRunStatus.RUNNING.value, "started_at": datetime.now(UTC)},
            )
            return ctx

    @staticmethod
    async def _creator(db: AsyncSession, run: EvalRun) -> AuthContext | None:
        """The starter's authority as it is now - a role changed since applies.

        An active membership only: a deactivated account keeps its membership
        row, and must not keep spending. Like a trigger's fire, a case is not
        the starter talking, so it reads and writes none of their personal memory.
        """
        user_id = run.created_by_user_id
        membership = (
            None
            if user_id is None
            else await member_repo.get_active(
                db, organization_id=run.organization_id, user_id=user_id
            )
        )
        if user_id is None or membership is None:
            return None
        return AuthContext(
            user_id=user_id,
            organization_id=run.organization_id,
            role=membership.role,
            subject_is_publisher_fallback=True,
        )

    async def _wave(self, ctx: AuthContext) -> None:
        drainers = [
            asyncio.create_task(self._drain(ctx))
            for _ in range(max(1, settings.EVAL_RUN_CONCURRENCY))
        ]
        try:
            await asyncio.gather(*drainers)
        finally:
            # gather leaves the others running when one raises; they must stop
            # before the run is failed, or they write answers to failed attempts.
            for drainer in drainers:
                drainer.cancel()
            await asyncio.gather(*drainers, return_exceptions=True)

    async def _drain(self, ctx: AuthContext) -> None:
        """Claim and answer attempts until none is left, or the run stops."""
        while True:
            async with self.sessions() as db:
                claimed = await eval_run_repo.claim_next(
                    db,
                    self.eval_run_id,
                    organization_id=self.organization_id,
                    org_limit=settings.EVAL_ORG_CONCURRENCY,
                    now=datetime.now(UTC),
                )
                attempt_id = claimed.id if claimed is not None else None
                waiting = 0
                if claimed is None:
                    run = await eval_run_repo.get(
                        db, self.eval_run_id, organization_id=self.organization_id
                    )
                    counts = await eval_run_repo.count_by_status(
                        db, self.eval_run_id, organization_id=self.organization_id
                    )
                    live = run is not None and not EvalRunStatus(run.status).terminal
                    waiting = counts.get(CaseAttemptStatus.PENDING.value, 0) if live else 0
            if attempt_id is None:
                if not waiting:
                    return
                await self.sleep(_FULL_BACKOFF_SECONDS)
                continue
            if await self._answer(ctx, attempt_id):
                return

    async def _answer(self, ctx: AuthContext, attempt_id: UUID) -> bool:
        """Run, record and score one attempt. True when the budget stopped the run."""
        org = self.organization_id
        async with self.sessions() as db:
            attempt = await eval_run_repo.get_case(db, attempt_id, organization_id=org)
            run = await eval_run_repo.get(db, self.eval_run_id, organization_id=org)
            if attempt is None or run is None:
                # Its agent or dataset was deleted meanwhile, and the run with it.
                return True
            arm = await eval_run_repo.get_arm(db, attempt.arm_id, organization_id=org)
            revision = (
                await eval_run_repo.revisions(db, [attempt.case_revision_id], organization_id=org)
            ).get(attempt.case_revision_id)
            dataset = await dataset_repo.get(db, run.dataset_id, organization_id=org)
            # Each cascades to the attempt, so the attempt existing means they do.
            assert arm is not None and revision is not None and dataset is not None
            calls: list[RecordedToolCall] = []
            try:
                output, agent_run = await AgentRunnerService(db).execute(
                    ctx,
                    run.agent_id,
                    revision.input,
                    surface=RunSurface.EVAL,
                    environment_id=run.environment_id,
                    message_history=build_message_history(
                        [
                            HistoryMessage(role=turn["role"], content=turn["content"])
                            for turn in revision.history or []
                        ]
                    ),
                    isolation=RunIsolation(
                        recording=await self._recording(db, ctx, run, revision),
                        live_reads=run.live_reads,
                    ),
                    candidate=_candidate(arm),
                    model_profile_id=arm.model_profile_id,
                    tool_calls=calls,
                )
            except Exception as exc:
                logger.exception("Eval case %s failed to run", attempt_id)
                await self._fail(db, attempt, run_failure_summary(exc))
                return False
            if agent_run.status == RunStatus.BUDGET_EXCEEDED.value:
                await self._fail(db, attempt, agent_run.error or "Budget exceeded", agent_run)
                await self._stop_for_budget(db)
                return True
            if agent_run.status != RunStatus.COMPLETED.value:
                await self._fail(
                    db, attempt, agent_run.error or f"The run ended {agent_run.status}", agent_run
                )
                return False
            intercepted = await intercepted_tool_call_repo.list_for_run(
                db, run_id=agent_run.id, organization_id=org
            )
            rows = trajectory(calls, intercepted)
            answer = ScoredAnswer(
                text=output,
                calls=tuple(
                    ScoredCall(
                        tool=call.tool_name,
                        args=call.args,
                        blocked=row["outcome"] == InterceptionOutcome.BLOCKED.value,
                    )
                    for call, row in zip(calls, rows, strict=True)
                ),
                cost_usd=agent_run.cost_usd,
                latency_ms=_latency_ms(agent_run),
                run_id=agent_run.id,
            )
            try:
                score = await ScoringService(db).score_case(
                    ctx,
                    dataset=dataset,
                    case=revision,
                    answer=answer,
                    scoring=DatasetScoring.model_validate(run.scoring),
                    eval_run_id=run.id,
                    # What deserves a person is sent once the reruns are in.
                    enqueue_review=False,
                )
            except NothingToScoreError as exc:
                # Nothing the scorers check applies to this case: it was answered
                # and stays undecided, which is not a malfunction.
                await eval_run_repo.update_case(
                    db,
                    case=attempt,
                    values={
                        **self._spend(agent_run),
                        "status": CaseAttemptStatus.DONE.value,
                        "answer": output,
                        "calls": rows,
                        "error": exc.message,
                        "ended_at": datetime.now(UTC),
                    },
                )
                return False
            except Exception as exc:
                logger.exception("Eval case %s failed to score", attempt_id)
                await self._fail(
                    db, attempt, run_failure_summary(exc), agent_run, answer=output, calls=rows
                )
                return False
            await eval_run_repo.update_case(
                db,
                case=attempt,
                values={
                    **self._spend(agent_run),
                    "status": CaseAttemptStatus.DONE.value,
                    "answer": output,
                    "calls": rows,
                    "case_score_id": score.id,
                    "ended_at": datetime.now(UTC),
                },
            )
            return False

    @staticmethod
    def _spend(agent_run: AgentRun) -> dict[str, Any]:
        return {
            "agent_run_id": agent_run.id,
            "cost_usd": agent_run.cost_usd,
            "cost_is_partial": agent_run.cost_is_partial,
            "input_tokens": agent_run.input_tokens,
            "output_tokens": agent_run.output_tokens,
            "latency_ms": _latency_ms(agent_run),
        }

    async def _fail(
        self,
        db: AsyncSession,
        attempt: EvalRunCase,
        error: str,
        agent_run: AgentRun | None = None,
        *,
        answer: str | None = None,
        calls: list[dict[str, Any]] | None = None,
    ) -> None:
        await eval_run_repo.update_case(
            db,
            case=attempt,
            values={
                **(self._spend(agent_run) if agent_run is not None else {}),
                "status": CaseAttemptStatus.FAILED.value,
                "answer": answer,
                "calls": calls or [],
                "error": error,
                "ended_at": datetime.now(UTC),
            },
        )

    async def _recording(
        self, db: AsyncSession, ctx: AuthContext, run: EvalRun, revision: DatasetCase
    ) -> ToolRecording | None:
        """The calls of the run this case was taken from, when the run asks for them.

        A case with no source run, or whose run kept no usable recording, runs
        isolated without one: its writes are held all the same.
        """
        if not run.from_recordings or revision.source_run_id is None:
            return None
        try:
            return await AgentRunnerService(db).tool_recording(ctx, revision.source_run_id)
        except BadRequestError, NotFoundError:
            logger.info("No usable recording for eval case %s", revision.case_id)
            return None

    async def _stop_for_budget(self, db: AsyncSession) -> None:
        run = await eval_run_repo.lock(db, self.eval_run_id, organization_id=self.organization_id)
        if run is None or EvalRunStatus(run.status).terminal:
            return
        await eval_run_repo.update_run(
            db,
            run=run,
            values={
                "status": EvalRunStatus.BUDGET_EXCEEDED.value,
                "error": "A case ran into the agent's or the organization's budget.",
                "ended_at": datetime.now(UTC),
            },
        )
        await eval_run_repo.skip_pending(db, run.id, organization_id=self.organization_id)

    async def _queue_reruns(self, ctx: AuthContext) -> bool:
        """Queue the confirmation reruns of every flipped case. True if any were queued.

        A case is rerun on each candidate arm it flipped on, and on this run's
        own baseline arm - one that ran here, or one standing in for an earlier
        run's answers, which is asked the flipped cases again here. A past
        baseline from another run cannot be rerun, so only the candidate side
        confirms against it.

        The run is locked while they are queued, as a cancel locks it: a cancel
        landing between the status check and the insert would skip the pending
        attempts it found and leave these pending in a cancelled run for good.
        """
        org = self.organization_id
        async with self.sessions() as db:
            run = await eval_run_repo.lock(db, self.eval_run_id, organization_id=org)
            if run is None or run.status != EvalRunStatus.RUNNING.value or run.reruns == 0:
                return False
            service = EvalRunService(db)
            attempts = await eval_run_repo.list_cases(db, run.id, organization_id=org)
            firsts = {(a.arm_id, a.case_id): a for a in attempts if a.attempt == 0}
            arms = await eval_run_repo.list_arms(db, [run.id], organization_id=org)
            # Each rerun with the first attempt it repeats: a reused baseline has
            # none of its own here, so it repeats the candidate's case revision.
            queued: dict[tuple[UUID, UUID], EvalRunCase] = {}
            for arm in arms:
                if arm.role != "candidate":
                    continue
                baseline = await service.baseline_for(ctx, run, arm)
                if baseline is None:
                    continue
                mine = await service.outcomes(ctx, arm, attempts)
                theirs = await service.outcomes(
                    ctx,
                    baseline.here or baseline.arm,
                    attempts
                    if baseline.here is not None or baseline.run.id == run.id
                    else await eval_run_repo.list_cases(db, baseline.run.id, organization_id=org),
                )
                rerun_on = (
                    baseline.here
                    if baseline.here is not None
                    else baseline.arm
                    if baseline.paired
                    else None
                )
                for case_id, (outcome, _, _) in mine.items():
                    first = firsts.get((arm.id, case_id))
                    if case_id not in theirs or first is None:
                        continue
                    if classify(theirs[case_id][0], outcome) not in (Flip.REGRESSION, Flip.FIXED):
                        continue
                    queued[(arm.id, case_id)] = first
                    if rerun_on is not None:
                        queued[(rerun_on.id, case_id)] = first
            new = [
                EvalRunCase(
                    eval_run_id=run.id,
                    arm_id=arm_id,
                    case_id=case_id,
                    case_revision_id=first.case_revision_id,
                    position=first.position,
                    attempt=attempt,
                )
                for (arm_id, case_id), first in sorted(
                    queued.items(), key=lambda item: str(item[0])
                )
                for attempt in range(1, run.reruns + 1)
            ]
            await eval_run_repo.add_cases(db, organization_id=org, cases=new)
            return bool(new)

    async def _route_to_review(self, ctx: AuthContext) -> None:
        """Send what deserves a person to the dataset's review queue, once the reruns are in.

        Only what the run itself can stand behind: the regressions it confirmed
        and the answers the judge failed to grade. The rest of its failures go
        when a person sends them.

        The answers and their scores are kept by then, so a refusal here leaves
        the run to complete: what was refused is kept on it as `routing_error`,
        for a person to send the answers by hand.
        """
        async with self.sessions() as db:
            run = await eval_run_repo.get(
                db, self.eval_run_id, organization_id=self.organization_id
            )
            if run is None or run.status != EvalRunStatus.RUNNING.value:
                return
            try:
                async with db.begin_nested():
                    worthy = await EvalRunService(db).review_worthy(ctx, run)
                    routed = await ScoringService(db).route_to_review(
                        ctx, dataset_id=run.dataset_id, score_ids=worthy
                    )
            except AppException as exc:
                logger.warning(
                    "Eval run %s could not send its scores to review: %s", run.id, exc.message
                )
                await eval_run_repo.update_run(
                    db,
                    run=run,
                    values={"routing_error": {"code": exc.code, "message": exc.message}},
                )
                return
            await eval_run_repo.update_run(
                db,
                run=run,
                values={"routed_to_review": routed.queued, "routed_replacing": routed.replaced},
            )

    async def _close(self, status: EvalRunStatus, *, only_from: EvalRunStatus) -> None:
        async with self.sessions() as db:
            run = await eval_run_repo.lock(
                db, self.eval_run_id, organization_id=self.organization_id
            )
            if run is None or run.status != only_from.value:
                return
            await eval_run_repo.update_run(
                db, run=run, values={"status": status.value, "ended_at": datetime.now(UTC)}
            )
