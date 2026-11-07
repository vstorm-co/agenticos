"""Wake a single scheduled human commitment without a model call."""

from app.db.session import get_worker_db_context
from app.services.task_execution import TaskExecution
from app.worker.jobs import WakeTask


async def wake_task(payload: WakeTask) -> None:
    async with get_worker_db_context() as db:
        await TaskExecution(db).wake(payload)
