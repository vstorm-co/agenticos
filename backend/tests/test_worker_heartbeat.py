"""The heartbeat the worker's sweeps leave for the scheduler probe (#2213)."""

from datetime import UTC, datetime

import pytest

from app.services import worker_heartbeat

pytestmark = pytest.mark.anyio


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        self.values[key] = value
        self.ttls[key] = ttl
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


async def test_a_recorded_tick_reads_back_as_when_it_finished() -> None:
    redis = _Redis()
    at = datetime(2026, 10, 18, 21, 30, 5, tzinfo=UTC)

    await worker_heartbeat.record(redis, "agent-triggers-check", at)  # type: ignore[arg-type]

    assert await worker_heartbeat.last(redis, "agent-triggers-check") == at  # type: ignore[arg-type]
    assert redis.ttls == {"worker:sweep:agent-triggers-check": worker_heartbeat.TTL_SECONDS}


async def test_a_sweep_that_never_ticked_reads_as_never() -> None:
    assert await worker_heartbeat.last(_Redis(), "portal-poll") is None  # type: ignore[arg-type]


async def test_a_value_nothing_here_wrote_reads_as_never() -> None:
    redis = _Redis()
    redis.values["worker:sweep:portal-poll"] = "yesterday-ish"

    assert await worker_heartbeat.last(redis, "portal-poll") is None  # type: ignore[arg-type]
