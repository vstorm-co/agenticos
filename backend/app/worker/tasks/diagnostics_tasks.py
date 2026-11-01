"""Hourly, non-blocking diagnostics on the existing durable system queue."""

from app.core.config import settings
from app.db.session import get_db_context
from app.services.diagnostics import DiagnosticsService
from app.worker.jobs import Tick


async def send_diagnostics(_tick: Tick) -> str:
    if not settings.DIAGNOSTICS_ENABLED:
        return "disabled"
    # The key must survive a cancelled or partially acknowledged network send.
    async with get_db_context() as db:
        await DiagnosticsService(db).initialize()
    async with get_db_context() as db:
        return await DiagnosticsService(db).send()
