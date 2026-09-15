"""The process cache behind `tool_contracts()` builds once and does not freeze a
transient failure.

`GET /agents/{id}/exposures` reads this on every load of an agent's availability
page (#1473), so a cold process that rebuilt the whole catalog on each concurrent
request, or that cached one capability's flaky first build as empty for the life
of the process, would pay for it on a routine path (#1621).
"""

from __future__ import annotations

from types import SimpleNamespace

import anyio
import anyio.lowlevel
import pytest

from app.services import capability_contracts

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _cold_cache():
    """Every test starts against a cold process cache and leaves one behind."""
    capability_contracts._CACHED = None
    yield
    capability_contracts._CACHED = None


def _two_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(
        capability_contracts,
        "all_capabilities",
        lambda: [SimpleNamespace(id="alpha"), SimpleNamespace(id="beta")],
    )


async def test_a_cold_cache_builds_each_capability_once_under_concurrency(monkeypatch):
    _two_capabilities(monkeypatch)
    built: list[str] = []

    async def _stub(definition):
        built.append(definition.id)
        await anyio.lowlevel.checkpoint()  # a real await, so both callers race for the lock
        return {}

    monkeypatch.setattr(capability_contracts, "_contracts_for", _stub)

    async with anyio.create_task_group() as tg:
        tg.start_soon(capability_contracts.tool_contracts)
        tg.start_soon(capability_contracts.tool_contracts)

    # Two capabilities, built once each - not four times across the two callers.
    assert sorted(built) == ["alpha", "beta"]


async def test_a_transient_failure_is_not_cached_and_is_retried(monkeypatch):
    _two_capabilities(monkeypatch)
    attempts = {"beta": 0}

    async def _stub(definition):
        if definition.id == "beta":
            attempts["beta"] += 1
            if attempts["beta"] == 1:
                raise RuntimeError("a resource not yet warm")
        return {}

    monkeypatch.setattr(capability_contracts, "_contracts_for", _stub)

    first = await capability_contracts.tool_contracts()
    assert first["beta"] == {}  # the failed capability degrades to empty for this answer
    assert capability_contracts._CACHED is None  # but nothing is frozen

    second = await capability_contracts.tool_contracts()
    assert attempts["beta"] == 2  # the next call retried it
    assert capability_contracts._CACHED is second  # and cached the complete build


async def test_a_complete_build_is_cached_and_not_rebuilt(monkeypatch):
    _two_capabilities(monkeypatch)
    built: list[str] = []

    async def _stub(definition):
        built.append(definition.id)
        return {}

    monkeypatch.setattr(capability_contracts, "_contracts_for", _stub)

    first = await capability_contracts.tool_contracts()
    second = await capability_contracts.tool_contracts()

    assert first is second  # the cached object, returned as-is
    assert sorted(built) == ["alpha", "beta"]  # built once, not twice
