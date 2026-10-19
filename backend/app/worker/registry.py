"""What a worker runs for each kind of job: the task's declaration bound to a function (#2219)."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue

from app.worker.jobs import Payload, Task, TaskKind


class JobHandler(Protocol):
    """A kind of job a worker can run: its declaration, and how to run one payload of it."""

    @property
    def task(self) -> TaskKind: ...

    async def execute(self, raw: dict[str, JsonValue]) -> None:
        """Validate `raw` as the task's payload and run it. Raises what the work raises."""
        ...


@dataclass(frozen=True)
class Handler[P: Payload]:
    """`run` bound to the task whose payload it takes."""

    task: Task[P]
    run: Callable[[P], Awaitable[object]]

    async def execute(self, raw: dict[str, JsonValue]) -> None:
        await self.run(self.task.load(raw))


Handlers = Mapping[str, JobHandler]
"""Handlers by the kind they run."""


def by_kind(handlers: Iterable[JobHandler]) -> dict[str, JobHandler]:
    """Index handlers by kind, refusing two for one kind - the second would silently win."""
    indexed: dict[str, JobHandler] = {}
    for handler in handlers:
        kind = handler.task.kind
        if kind in indexed:
            raise ValueError(f"two handlers for the job kind {kind!r}")
        indexed[kind] = handler
    return indexed
