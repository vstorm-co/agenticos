"""Queue a resumed answer with its terminal write, never another model call."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.repositories import routine_delivery as delivery_repo
from app.services.background_jobs import enqueue
from app.worker.jobs import DELIVER_ROUTINE_ANSWER, DeliverRoutineAnswer


class RoutineDeliveryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def queue(self, run: AgentRun, *, answer: str) -> None:
        if (
            run.status != RunStatus.COMPLETED.value
            or run.parent_run_id is not None
            or run.routine_kind != "trigger"
            or run.routine_origin_id is None
            or run.user_id is None
        ):
            return
        if not await delivery_repo.create(
            self.db,
            run_id=run.id,
            organization_id=run.organization_id,
            trigger_id=run.routine_origin_id,
            answer=answer,
        ):
            return
        await enqueue(
            self.db,
            DELIVER_ROUTINE_ANSWER,
            DeliverRoutineAnswer(run_id=run.id, organization_id=run.organization_id),
            organization_id=run.organization_id,
            dedupe_key=f"routine-answer:{run.id}",
        )
