"""What a worker runs for each kind of job: the task's declaration bound to a function (#2219)."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, JsonValue

from app.worker.jobs import Payload, Task, TaskKind


class JobHandler(Protocol):
    """A kind of job a worker can run: its declaration, and how to run one payload of it."""

    @property
    def task(self) -> TaskKind: ...

    async def execute(self, raw: dict[str, JsonValue]) -> dict[str, JsonValue] | None:
        """Validate `raw` as the task's payload and run it, answering what it reported.

        Raises what the work raises.
        """
        ...


@dataclass(frozen=True)
class Handler[P: Payload]:
    """`run` bound to the task whose payload it takes.

    A run that answers a Pydantic model has that model kept on the job as its
    result - the answer an asynchronous caller reads back. Anything else it
    returns (a sweep's counts) is for its own tests and logs, and is not kept.
    """

    task: Task[P]
    run: Callable[[P], Awaitable[object]]

    async def execute(self, raw: dict[str, JsonValue]) -> dict[str, JsonValue] | None:
        answer = await self.run(self.task.load(raw))
        return answer.model_dump(mode="json") if isinstance(answer, BaseModel) else None


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
