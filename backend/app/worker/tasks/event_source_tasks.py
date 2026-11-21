"""Source dispatch is durable; each subscriber is isolated in its own transaction."""

from app.db.session import get_worker_db_context
from app.services.event_sources import EventSourceService
from app.worker.jobs import DispatchSourceEvent


async def dispatch_source_event(payload: DispatchSourceEvent) -> None:
    async with get_worker_db_context() as db:
        await EventSourceService(db).dispatch(payload.organization_id, payload.dispatch_id)


async def cleanup_source_deliveries() -> None:
    async with get_worker_db_context() as db:
        await EventSourceService(db).cleanup()
