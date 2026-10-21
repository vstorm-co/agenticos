"""A coding task, streamed to the chat as the harness works on it.

Claude Code and Codex are agents of their own, so a task handed to one is shown
the way a delegation to a specialist is: its own panel, its steps as it takes
them, what it says between them. The frames are the delegation frames
(`app.agents.subagent_events`) - the surface already draws them, nests them under
a delegate that handed the task on, and closes the panel when the turn settles -
with the step's subject in `title` and the harness named in `harness`, so the
panel reads "Read src/app.py" under the Claude Code mark rather than "Read".

Nothing here is the record. The tool's result is, and it carries every step
again; a surface with no `subagent_events` - a channel, the API - simply hears
nothing while the harness works.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from app.agents.capabilities.coding_agent._harness import (
    LABELS,
    Harness,
    LiveItem,
    Said,
    StepStarted,
)
from app.agents.capabilities.subagents import acting_delegate
from app.agents.subagent_events import (
    SubagentEvent,
    SubagentEventSink,
    SubagentFinished,
    SubagentStarted,
    SubagentTextDelta,
    SubagentToolCall,
    SubagentToolResult,
)


@dataclass
class Narration:
    """One task's panel: opened once, fed each step, closed however it ends."""

    sink: SubagentEventSink | None
    task_id: str
    harness: Harness
    depth: int
    parent_task_id: str | None
    _open_steps: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_call(cls, deps: Any, task_id: str, harness: Harness) -> Narration:
        """The panel for this tool call, one level inside the delegate making it, if any."""
        sink = getattr(deps, "subagent_events", None)
        acting = acting_delegate()
        return cls(
            sink=sink if callable(sink) else None,
            task_id=task_id,
            harness=harness,
            depth=0 if acting is None else acting.depth + 1,
            parent_task_id=None if acting is None else acting.task_id,
        )

    async def started(self, task: str) -> None:
        await self._send(
            SubagentStarted(
                task_id=self.task_id,
                subagent=LABELS[self.harness],
                depth=self.depth,
                mode="sync",
                prompt=task,
                parent_task_id=self.parent_task_id,
                harness=self.harness,
            )
        )

    async def shown(self, items: list[LiveItem]) -> None:
        for item in items:
            if isinstance(item, Said):
                await self._send(
                    SubagentTextDelta(**self._labels(), delta=f"{item.text.strip()}\n\n")
                )
            elif isinstance(item, StepStarted):
                if item.key in self._open_steps:
                    continue
                self._open_steps[item.key] = item.step.kind
                await self._send(
                    SubagentToolCall(
                        **self._labels(),
                        tool_name=item.step.kind,
                        tool_call_id=item.key,
                        title=item.step.title,
                    )
                )
            else:
                kind = self._open_steps.pop(item.key, None)
                if kind is not None:
                    await self._send(
                        SubagentToolResult(
                            **self._labels(),
                            tool_name=kind,
                            tool_call_id=item.key,
                            ok=not item.failed,
                        )
                    )

    async def finished(
        self, status: Literal["completed", "failed", "cancelled"], error: str | None = None
    ) -> None:
        # A step the harness never answered - it was stopped mid-command - closes
        # with the panel rather than spinning in it.
        for key, kind in list(self._open_steps.items()):
            await self._send(
                SubagentToolResult(**self._labels(), tool_name=kind, tool_call_id=key, ok=False)
            )
        self._open_steps.clear()
        await self._send(SubagentFinished(**self._labels(), status=status, error=error))

    def _labels(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "subagent": LABELS[self.harness], "depth": self.depth}

    async def _send(self, frame: SubagentEvent) -> None:
        if self.sink is not None:
            await self.sink(frame)
