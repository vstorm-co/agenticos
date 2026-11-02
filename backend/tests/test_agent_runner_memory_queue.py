"""A finished run asks for its chat to be read for memory without ever risking the run (#2090)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.audience import RunAudience
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio


def _service(*, nested_fails: bool = False) -> SimpleNamespace:
    @asynccontextmanager
    async def nested():
        if nested_fails:
            raise RuntimeError("savepoint refused")
        yield

    return SimpleNamespace(db=SimpleNamespace(begin_nested=nested))


def _prepared() -> SimpleNamespace:
    person = uuid4()
    return SimpleNamespace(
        spec=MagicMock(model_dump=MagicMock(return_value={"capabilities": []})),
        built=SimpleNamespace(
            deps=SimpleNamespace(
                impersonated=False,
                run_person=person,
                audience=RunAudience(user_id=person),
            )
        ),
    )


async def test_the_run_is_offered_with_its_spec_as_stored() -> None:
    run = SimpleNamespace(id=uuid4())
    queue = AsyncMock(return_value=True)
    prepared = _prepared()
    with patch("app.services.memory.extraction.queue_extraction", new=queue):
        await AgentRunnerService._queue_memory_extraction(_service(), run, prepared)

    assert queue.await_args.args[1:] == (run, {"capabilities": []})
    assert queue.await_args.kwargs["audience"] == prepared.built.deps.audience


@pytest.mark.parametrize(
    "field,value", [("impersonated", True), ("run_person", None), ("audience", None)]
)
async def test_automatic_capture_needs_an_unimpersonated_admitted_person(
    field: str, value: object
) -> None:
    prepared = _prepared()
    setattr(prepared.built.deps, field, value)
    with patch("app.services.memory.extraction.queue_extraction", new=AsyncMock()) as queue:
        await AgentRunnerService._queue_memory_extraction(
            _service(), SimpleNamespace(id=uuid4()), prepared
        )
    queue.assert_not_awaited()


async def test_a_failure_to_queue_is_logged_and_the_run_still_finishes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    await AgentRunnerService._queue_memory_extraction(
        _service(nested_fails=True), SimpleNamespace(id=uuid4()), _prepared()
    )

    assert "memory_extraction_queue_failed" in caplog.text
