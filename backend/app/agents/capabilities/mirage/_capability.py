"""A Mirage terminal for one run: its mounts, opened on first use and closed after.

The tools are `pydantic-ai-backend`'s console - `ls`, `read_file`, `glob`, `grep`,
`write_file`, `edit_file`, `execute` - the same seven `sandbox` offers, with the
same text, prefixed `mirage_` and pinned to this terminal. Pinned rather than
reached through `ctx.workspace`, which is the run's *one* workspace and belongs
to `sandbox` when the agent has both: the console toolset reads the workspace off
the context, so this hands each call a context whose workspace is the terminal.
An agent can then keep scratch files in its sandbox and read the company's Drive
in the same turn, without the two sets of tools colliding on a name.

The mounts arrive resolved, credentials included (`ResolvedMount`): a capability
never reads the vault or the database, and the runner decides which secret and
which account a mount reaches before the model is called.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from mirage import Workspace
from mirage.policy import CommandsBlock, PathsBlock, SessionProfile
from mirage.policy.types import CommandRule
from mirage.vfs.ram import RAMVFS
from pydantic_ai import DeferredToolRequests, RunContext
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.toolsets import AbstractToolset, WrapperToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.workspaces import Workspace as RunWorkspace
from pydantic_ai_backends import create_console_toolset

from app.agents.capabilities.mirage._backend import BoundedBackend
from app.agents.capabilities.mirage._policy import (
    WriteApproval,
    approve,
    approved_writes,
    ask,
    needs_approval,
)
from app.agents.capabilities.mirage._resolved import PREFIX, ResolvedMount
from app.agents.capabilities.mirage._scratch import ScratchFolder, ScratchState, keep, restore
from app.agents.deps import AgentDeps

_PROFILE = "agent"


@dataclass
class _Pinned(WrapperToolset[AgentDeps]):
    """The console toolset, reaching the terminal instead of the run's workspace."""

    terminal: Mirage = field(kw_only=True)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDeps],
        tool: ToolsetTool[AgentDeps],
    ) -> Any:
        workspace = await self.terminal.workspace()
        approved = False
        if await needs_approval(
            workspace, self.terminal.gated, name.removeprefix(f"{PREFIX}_"), tool_args
        ):
            refused = await approve(ctx, name, tool_args)
            if refused is not None:
                return refused
            approved = True
        pinned = replace(ctx, workspace=RunWorkspace(BoundedBackend(workspace)))
        with approved_writes(approved):
            return await super().call_tool(name, tool_args, pinned, tool)


@dataclass
class Mirage(AbstractCapability[AgentDeps]):
    """A virtual terminal over an author's chosen backends."""

    mounts: tuple[ResolvedMount, ...]
    notes: tuple[str, ...] = ()
    allowed_commands: tuple[str, ...] = ()
    hidden_paths: tuple[str, ...] = ()

    _workspace: Workspace | None = field(default=None, init=False, repr=False, compare=False)

    _ram: dict[str, RAMVFS] = field(default_factory=dict, init=False, repr=False)
    _scratch: ScratchState = field(default_factory=ScratchState, init=False, repr=False)

    async def for_run(self, ctx: RunContext[AgentDeps]) -> Mirage:
        # A fresh instance per run, so one run's open connections and history are
        # never another's.
        instance = replace(self)
        instance._scratch = restore(ctx.messages)
        return instance

    @property
    def gated(self) -> frozenset[str]:
        """The writable folders whose writes a person approves."""
        return frozenset(
            mount.path for mount in self.mounts if mount.mode == "write" and mount.approve_writes
        )

    async def workspace(self) -> Workspace:
        """The terminal, built on the first tool call of the run."""
        if self._workspace is None:
            gated = self.gated
            mounts = {mount.path: mount.build() for mount in self.mounts}
            for path, mount in mounts.items():
                if isinstance(mount.vfs, RAMVFS):
                    saved = self._scratch.folders.get(path)
                    if saved is not None:
                        mount.vfs.load_state(saved.model_dump())
                    self._ram[path] = mount.vfs
            self._workspace = Workspace(
                dict(mounts),
                cache_limit="16MB",
                max_memory="16MB",
                policies=[WriteApproval(gated)] if gated else [],
                on_ask=ask,
                profiles={_PROFILE: _profile(self.allowed_commands, self.hidden_paths)},
                profile=_PROFILE,
            )
        return self._workspace

    async def wrap_run(
        self, ctx: RunContext[AgentDeps], *, handler: WrapRunHandler
    ) -> AgentRunResult[Any]:
        try:
            result = await handler()
            if isinstance(result.output, DeferredToolRequests):
                state = ScratchState(
                    folders={
                        path: ScratchFolder.model_validate(vfs.get_state())
                        for path, vfs in self._ram.items()
                    }
                    if self._ram
                    else self._scratch.folders
                )
                if state.folders:
                    keep(result.all_messages(), state)
            return result
        finally:
            if self._workspace is not None:
                await self._workspace.close()
                self._workspace = None

    def get_toolset(self) -> AbstractToolset[AgentDeps]:
        console = create_console_toolset(
            include_execute=True,
            # The platform's gate decides approval, per tool from the spec and
            # per mount from `WriteApproval`; the library asking as well would
            # be a second queue nobody reads.
            require_execute_approval=False,
            image_support=True,
            document_support=True,
            profile=_PROFILE,
        )
        return _Pinned(console.prefixed(PREFIX), terminal=self)

    def get_instructions(self) -> str:
        return instructions(self.mounts, self.notes)


def _profile(allowed_commands: Sequence[str], hidden_paths: Sequence[str]) -> SessionProfile:
    """The author's policy as Mirage's own, enforced by the shell that parses the line.

    An unstated allowlist admits virtual commands; raw HTTP clients cannot bypass
    the platform's web capabilities or the deployment's mount allowlist.
    """
    return SessionProfile(
        commands=CommandsBlock(
            allow=tuple(allowed_commands) or None,
            deny=tuple(
                CommandRule(
                    reason="Use a mounted service or a web capability for network access",
                    commands=(command,),
                )
                for command in ("curl", "wget")
                if not allowed_commands or command in allowed_commands
            ),
        ),
        paths=PathsBlock(hide=tuple(hidden_paths)),
    )


def instructions(mounts: Sequence[ResolvedMount], notes: Sequence[str] = ()) -> str:
    """What the model reads about the terminal: what is mounted, and how."""
    lines = [
        f"You have a virtual terminal. Its tools are named {PREFIX}_*: "
        f"{PREFIX}_ls, {PREFIX}_read_file, {PREFIX}_glob, {PREFIX}_grep, "
        f"{PREFIX}_write_file, {PREFIX}_edit_file and {PREFIX}_execute, which runs a "
        "shell line (ls, cat, grep, find, head, wc, cp, mv, and pipes). These folders "
        "are mounted:",
    ]
    for mount in mounts:
        if mount.mode == "read":
            access = "read-only"
        elif mount.approve_writes:
            access = "writable; a person approves each write before it happens"
        else:
            access = "writable"
        lines.append(f"- {mount.path}: {mount.title} ({access})")
    lines.extend(notes)
    lines.append(
        "Each folder reads the service behind it, so a file is the service's own record "
        "rendered as text. Start with ls on a folder before reading inside it."
    )
    return "\n".join(lines)
