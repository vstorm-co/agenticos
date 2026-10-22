"""A person's replayable browse steps in Redis - kept, read back, dropped."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use._plans import PlanStep
from app.clients.redis import RedisClient
from app.services import browse_plans

pytestmark = pytest.mark.anyio

ORG = uuid4()
PERSON = uuid4()
STEPS = (
    PlanStep(op="click", at="example.test/pricing", role="link", label="Plans"),
    PlanStep(op="scroll", at="example.test/plans", direction="down"),
)


class _Redis:
    """The three calls the plans make, against a dict."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        self.values[key] = value
        self.ttls[key] = ttl
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.values.pop(key, None) is not None else 0


@pytest.fixture
def redis() -> Iterator[_Redis]:
    fake = _Redis()
    client = MagicMock(spec=RedisClient)
    client.get = fake.get
    client.set = fake.set
    client.delete = fake.delete
    browse_plans.configure(client)
    yield fake
    browse_plans.configure(None)


async def test_a_kept_plan_is_read_back_by_its_person_and_task(redis: _Redis):
    await browse_plans.keep(ORG, PERSON, "task-1", STEPS)

    assert await browse_plans.recall(ORG, PERSON, "task-1") == STEPS
    [key] = redis.values
    assert redis.ttls[key] == browse_plans.TTL_SECONDS
    # What was pressed, never how a field was filled: there is no value to keep.
    assert "None" not in redis.values[key]


@pytest.mark.security
async def test_nobody_else_in_the_organization_reads_it(redis: _Redis):
    await browse_plans.keep(ORG, PERSON, "task-1", STEPS)

    assert await browse_plans.recall(ORG, uuid4(), "task-1") == ()
    assert await browse_plans.recall(uuid4(), PERSON, "task-1") == ()


async def test_a_forgotten_plan_is_gone(redis: _Redis):
    await browse_plans.keep(ORG, PERSON, "task-1", STEPS)

    await browse_plans.forget(ORG, PERSON, "task-1")

    assert await browse_plans.recall(ORG, PERSON, "task-1") == ()


async def test_an_empty_plan_is_not_kept(redis: _Redis):
    await browse_plans.keep(ORG, PERSON, "task-1", ())
    assert redis.values == {}


async def test_a_plan_written_in_another_shape_is_dropped_rather_than_failing(redis: _Redis):
    redis.values[f"browse-plan:{ORG}:{PERSON}:task-1"] = '[{"op": "teleport"}]'

    assert await browse_plans.recall(ORG, PERSON, "task-1") == ()
    assert redis.values == {}


async def test_without_redis_nothing_is_kept_and_nothing_is_recalled():
    browse_plans.configure(None)

    assert browse_plans.available() is False
    await browse_plans.keep(ORG, PERSON, "task-1", STEPS)
    await browse_plans.forget(ORG, PERSON, "task-1")
    assert await browse_plans.recall(ORG, PERSON, "task-1") == ()


async def test_a_worker_connects_its_own_client_once(monkeypatch: pytest.MonkeyPatch):
    browse_plans.configure(None)
    created: list[MagicMock] = []

    def client() -> MagicMock:
        made = MagicMock(spec=RedisClient)
        made.connect = AsyncMock()
        created.append(made)
        return made

    monkeypatch.setattr(browse_plans, "RedisClient", client)

    await browse_plans.connect_in_worker()
    await browse_plans.connect_in_worker()

    assert len(created) == 1
    assert browse_plans.available() is True
    browse_plans.configure(None)
