"""The two shell tools, and the text the model reads before calling them.

The same shell twice, over two views of the same mounts. Two tools rather than
a `write` argument, because what may run unattended is decided by which tool it
is - an argument is something the model chooses, and the approval gate keys on
the tool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer

if TYPE_CHECKING:
    from app.agents.capabilities.mirage._capability import _Views

EXPLORE_DESCRIPTION = "Run a read-only shell command across the mounted repositories."
RUN_DESCRIPTION = "Run a shell command that may write into the scratch folder."


@dataclass(frozen=True)
class Terminal:
    """What both tools run a command through."""

    open_views: Callable[[], _Views]
    timeout_seconds: int
    max_output_chars: int

    async def run(self, command: str, *, writable: bool) -> str:
        views = self.open_views()
        workspace = views.run if writable else views.explore
        try:
            # `wait_for` cancels the command on timeout, and Mirage stops at its
            # next gate - a stuck `grep` over a large tree does not hold the run.
            result = await asyncio.wait_for(
                workspace.execute(command), timeout=self.timeout_seconds
            )
        except TimeoutError:
            return (
                f"exit code: timeout\nThe command ran past {self.timeout_seconds}s and was stopped."
            )
        stdout = await result.stdout_str()
        stderr = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else ""
        return _shaped(result.exit_code, stdout, stderr, self.max_output_chars)


def _shaped(exit_code: int, stdout: str, stderr: str, limit: int) -> str:
    """A command's answer as the model reads it, cut at the limit with a note saying so."""
    body = stdout if not stderr else f"{stdout}\n[stderr]\n{stderr}"
    if len(body) > limit:
        body = f"{body[:limit]}\n[output cut at {limit} characters; narrow the command]"
    return f"exit code: {exit_code}\n{body}"


def build_toolset(terminal: Terminal) -> FunctionToolset[Any]:
    """`mirage_explore` and `mirage_run`, bound to one run's terminal."""

    async def mirage_explore(ctx: RunContext[Any], command: str) -> str:
        """Run a read-only shell command across the mounted repositories.

        ls, cat, grep, find, head and wc work as in a shell. Every mount is read-only here, so a write fails with "Read-only file
        system" - use mirage_run for that. Pipes work: `grep -rn TODO /github | head`.

        Args:
            command: One shell line, e.g. `ls /github` or `grep -rl Agent /github`.

        Returns:
            `exit code: N`, then the output; stderr follows under `[stderr]`. Long
            output is cut, and the note at the end says where.
        """
        if not command.strip():
            return steer(ctx, "Pass a shell command, e.g. `ls /github`.")
        return await terminal.run(command, writable=False)

    async def mirage_run(ctx: RunContext[Any], command: str) -> str:
        """Run a shell command that may write into the scratch folder.

        The repositories stay read-only: a write there fails with "Operation
        not supported". Use mirage_explore for anything that only reads.

        Args:
            command: One shell line, e.g. `grep -rn TODO /github > /scratch/todos.txt`.

        Returns:
            `exit code: N`, then the output; stderr follows under `[stderr]`. Long
            output is cut, and the note at the end says where.
        """
        if not command.strip():
            return steer(ctx, "Pass a shell command, e.g. `echo notes > /scratch/notes.md`.")
        return await terminal.run(command, writable=True)

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(mirage_explore)
    toolset.add_function(mirage_run)
    return toolset
