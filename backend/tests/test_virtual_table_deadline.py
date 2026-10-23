"""A page's read deadline: one clock reading per arm, and never a statement with no limit."""

import pytest

from app.services.virtual_tables import ReadDeadline
from app.services.virtual_tables import deadline as deadline_module
from app.services.virtual_tables.exceptions import DeadlineReached

pytestmark = pytest.mark.anyio


class _Clock:
    """A `monotonic` that reads what the test sets, and counts how often it was read."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return self.now


class _Session:
    """Records each statement and its parameters, the way `AsyncSession.execute` takes them."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, object] | None]] = []

    async def execute(self, statement: object, parameters: dict[str, object] | None = None):
        self.executed.append((str(statement), parameters))


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(deadline_module, "monotonic", fake)
    return fake


def _timeouts(session: _Session) -> list[object]:
    return [
        (parameters or {}).get("ms")
        for statement, parameters in session.executed
        if "set_config('statement_timeout'" in statement
    ]


async def test_arm_sets_the_smaller_of_the_query_limit_and_the_time_left(clock):
    session = _Session()
    deadline = ReadDeadline(5, 2_000)

    await deadline.arm(session)
    clock.now = 4.25
    await deadline.arm(session)

    assert deadline.remaining_ms() == 750
    assert _timeouts(session) == ["2000", "750"]


async def test_arm_past_the_deadline_raises_without_touching_the_database(clock):
    session = _Session()
    deadline = ReadDeadline(5, 2_000)
    clock.now = 6

    with pytest.raises(DeadlineReached):
        await deadline.arm(session)

    assert deadline.remaining_ms() < 0
    assert session.executed == []


async def test_arm_with_under_a_millisecond_left_raises_and_never_sets_zero(clock):
    session = _Session()

    with pytest.raises(DeadlineReached):
        await ReadDeadline(0.0004, 2_000).arm(session)
    assert session.executed == []

    await ReadDeadline(0.001, 2_000).arm(session)

    assert _timeouts(session) == ["1"]


async def test_arm_reads_the_clock_once(clock):
    session = _Session()
    deadline = ReadDeadline(5, 2_000)
    before = clock.reads

    await deadline.arm(session)

    assert clock.reads - before == 1
