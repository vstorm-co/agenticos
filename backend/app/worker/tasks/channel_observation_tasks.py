"""Durable observation sweeps and bounded model work."""

from app.db.session import get_db_context
from app.services.channels.handback import ensure_channel_adapters
from app.services.channels.observation import analyze, sweep
from app.worker.jobs import AnalyzeChannel, Tick


async def sweep_channels(tick: Tick) -> int:
    async with get_db_context() as db:
        return await sweep(db, now=tick.scheduled_for)


async def analyze_channel(payload: AnalyzeChannel) -> bool:
    ensure_channel_adapters()
    async with get_db_context() as db:
        return await analyze(db, payload)
