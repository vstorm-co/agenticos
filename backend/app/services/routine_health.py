"""Pause unsuccessful responsibilities without treating acknowledgements as recovery."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.watch import Watch, WatchAttemptStatus
from app.repositories import agent_trigger as trigger_repo
from app.repositories import routine_health as health_repo
from app.repositories import watch as watch_repo

# A budget stop is absent: a refused activation waits for the next one and says
# nothing about whether the routine works.
_JUDGED = frozenset(
    {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.LOOP_STOPPED.value,
        RunStatus.GUARDRAIL_BLOCKED.value,
        RunStatus.TIMED_OUT.value,
    }
)


class RoutineHealthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run_result(self, run: AgentRun) -> None:
        if (
            run.parent_run_id is not None
            or run.routine_origin_id is None
            or run.status not in _JUDGED
        ):
            return
        activation = run.routine_activation_at or run.started_at
        if activation is None:
            return
        if run.routine_kind == "trigger":
            trigger = await trigger_repo.get_by_id(
                self.db, run.routine_origin_id, fresh=True, for_update=True
            )
            if (
                trigger is None
                or trigger.organization_id != run.organization_id
                or (run.user_id is not None and trigger.created_by_user_id != run.user_id)
            ):
                return
            await self._record(
                trigger, at=activation, healthy=run.status == RunStatus.COMPLETED.value
            )
        elif run.routine_kind == "watch" and run.status != RunStatus.COMPLETED.value:
            watch = await watch_repo.get_by_id(
                self.db, run.routine_origin_id, fresh=True, for_update=True
            )
            if (
                watch is None
                or watch.organization_id != run.organization_id
                or watch.user_id != run.user_id
            ):
                return
            await self._record(watch, at=activation, healthy=False)

    async def watch_result(
        self,
        watch: Watch,
        *,
        at: datetime,
        status: WatchAttemptStatus,
        run: AgentRun | None = None,
    ) -> None:
        if status in (WatchAttemptStatus.DELIVERY_UNAVAILABLE, WatchAttemptStatus.BUDGET_PAUSED):
            return
        if run is not None and run.status not in _JUDGED:
            return
        current = await watch_repo.get_by_id(self.db, watch.id, fresh=True, for_update=True)
        if (
            current is None
            or current.organization_id != watch.organization_id
            or current.user_id != watch.user_id
        ):
            return
        await self._record(current, at=at, healthy=status is WatchAttemptStatus.COMPLETED)

    async def _record(self, parent: AgentTrigger | Watch, *, at: datetime, healthy: bool) -> None:
        if not parent.is_active or parent.max_failures is None:
            return
        if parent.ends_at is not None and parent.ends_at <= datetime.now(UTC):
            return
        if parent.health_reset_at is not None and at < parent.health_reset_at:
            return
        kind: health_repo.RoutineKind = "watch" if isinstance(parent, Watch) else "trigger"
        owner = parent.user_id if isinstance(parent, Watch) else parent.created_by_user_id
        if owner is None:
            return
        parent.consecutive_failures = await health_repo.observe(
            self.db,
            kind=kind,
            routine_id=parent.id,
            organization_id=parent.organization_id,
            user_id=owner,
            activation_at=at,
            healthy=healthy,
            reset_at=parent.health_reset_at,
        )
        if parent.consecutive_failures >= parent.max_failures:
            parent.is_active = False
            parent.auto_stopped_at = datetime.now(UTC)
        await self.db.flush()
