"""The three tools of the monitor: start a watch, list the watches, stop one (#2576)."""

import json
from typing import Any

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities.monitor._manager import MonitorManager

NEEDS_SHELL = "Watching needs a workspace with a shell, and this agent has none. Say so."


def build_toolset(manager: MonitorManager) -> FunctionToolset[Any]:
    """The three tools, bound to this run's manager."""
    toolset: FunctionToolset[Any] = FunctionToolset()

    @toolset.tool
    async def start_monitor(
        ctx: RunContext[Any], command: str, label: str | None = None, match: str | None = None
    ) -> str:
        """Watch a long-running command and be told about its output as it appears.

        Use it for things you want to hear about while you keep working: a test or
        build watcher, a log tail for errors, a CI or deploy poll, a dev server. The
        command runs in the background and each new line of its output is shown to
        you on your next steps, so you do NOT need to poll. Stop it with
        `stop_monitor` when you no longer need it.

        Args:
            command: The shell command to run and watch, for example `npm run test:watch`.
            label: A short name for this watch; the command itself if left out.
            match: Optional words, separated by `|`: only output lines containing one
                of them (any case) are shown to you, for example `error|fail|exception`.
                It is plain text, not a regular expression.
        """
        if not ctx.workspace.attached:
            return NEEDS_SHELL
        try:
            watch = await manager.start(ctx.workspace, command, label, match)
        except ValueError as refused:
            return str(refused)
        except WorkspaceError as failed:
            return f"The watch could not start: {failed}"
        return json.dumps({"monitor_id": watch.id, "label": watch.label, "running": True})

    @toolset.tool
    async def list_monitors(ctx: RunContext[Any]) -> str:
        """List this run's watches with their state and the last lines they matched."""
        return json.dumps(
            [
                {
                    "monitor_id": watch.id,
                    "label": watch.label,
                    "command": watch.command,
                    "running": watch.running,
                    "exit_code": watch.exit_code,
                    "matched_lines": watch.reported,
                    "recent": list(watch.recent),
                }
                for watch in manager.watches
            ]
        )

    @toolset.tool
    async def stop_monitor(ctx: RunContext[Any], monitor_id: str) -> str:
        """Stop a watch and the command it runs.

        Args:
            monitor_id: The id `start_monitor` returned.
        """
        if not ctx.workspace.attached:
            return NEEDS_SHELL
        watch = await manager.stop(ctx.workspace, monitor_id)
        return f"No watch has the id {monitor_id}." if watch is None else f"Stopped {watch.label}."

    return toolset
