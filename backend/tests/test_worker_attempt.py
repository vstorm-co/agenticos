"""Which attempt a handler runs, carried from the worker to it (#2219, Codex on #2248)."""

from datetime import timedelta

import pytest
from pydantic import BaseModel, JsonValue

from app.worker.attempt import Attempt, is_final_attempt, running
from app.worker.child import ChildRequest, run_one
from app.worker.executors import InProcessExecutor, Succeeded, _request
from app.worker.jobs import Pool, Task, Tick
from app.worker.registry import Handler, by_kind

pytestmark = pytest.mark.anyio

_PROBE = Task(
    kind="attempt-probe",
    payload_type=Tick,
    pool=Pool.SYSTEM,
    max_attempts=3,
    timeout=timedelta(seconds=5),
    priority=1,
)


class _Seen(BaseModel):
    final: bool


async def _says_whether_final(_tick: Tick) -> _Seen:
    return _Seen(final=is_final_attempt())


_HANDLERS = by_kind([Handler(_PROBE, _says_whether_final)])
_TICK: dict[str, JsonValue] = {"scheduled_for": "2026-10-19T00:00:00Z"}


def test_unsaid_is_final_so_code_outside_the_queue_settles_as_before() -> None:
    assert is_final_attempt() is True


def test_the_attempt_holds_only_inside_its_block() -> None:
    with running(Attempt(1, 3)):
        assert is_final_attempt() is False
    with running(Attempt(3, 3)):
        assert is_final_attempt() is True
    assert is_final_attempt() is True


@pytest.mark.parametrize(("number", "final"), [(1, False), (3, True)])
async def test_the_in_process_executor_tells_the_handler(number: int, final: bool) -> None:
    executor = InProcessExecutor(_HANDLERS, concurrency=1)
    slot = await executor.acquire()

    outcome = await slot.run(
        _PROBE.kind, _TICK, timeout=timedelta(seconds=5), attempt=Attempt(number, 3)
    )

    assert outcome == Succeeded({"final": final})


async def test_a_child_reads_it_off_the_request() -> None:
    reply = await run_one(
        _HANDLERS, ChildRequest(kind=_PROBE.kind, payload=_TICK, attempt=1, max_attempts=3)
    )
    assert reply.result == {"final": False}
    reply = await run_one(_HANDLERS, ChildRequest(kind=_PROBE.kind, payload=_TICK))
    assert reply.result == {"final": True}


def test_the_request_a_child_is_sent_carries_it() -> None:
    assert _request("k", {}, Attempt(2, 3)) == ChildRequest(
        kind="k", payload={}, attempt=2, max_attempts=3
    )
    assert _request("k", {}, None) == ChildRequest(kind="k", payload={})
